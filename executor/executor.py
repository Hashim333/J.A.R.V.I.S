"""
executor/executor.py

The Executor runs an ExecutionPlan by dispatching each Step to a handler
provided by a Registry. Integrates with the Safety & Confirmation Framework
to validate actions, request confirmation, and audit every command.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from brain.execution_plan import ExecutionPlan, Step
from executor.registry import Registry
from models.action_result import ActionResult
from models.task_result import TaskResult
from safety.policy import SafetyPolicy
from safety.audit import AuditLog
from safety.validator import validate_file_path, validate_app_exists, validate_parameters, validate_url
from monitoring.instrumentation import timed
from monitoring.pipeline_trace import stage_entry, stage_exit

logger = logging.getLogger(__name__)

# Actions that open a new Chrome tab. A plan may only run ONE of these per
# request — otherwise a single command produces duplicate tabs/searches.
_TAB_OPENING_ACTIONS: frozenset[str] = frozenset({
    "open_website", "search", "browser_search", "navigate",
})


class Executor:
    """
    Runs an ExecutionPlan step by step via a handler registry.
    Each step is checked against the SafetyPolicy before execution.
    """

    def __init__(
        self,
        registry: Registry,
        voice_input: Callable[[], str | None] | None = None,
        safety_policy: SafetyPolicy | None = None,
        audit_log: AuditLog | None = None,
        debug_safe_mode: bool | None = None,
    ) -> None:
        self._registry = registry
        self._voice_input = voice_input
        self._policy = safety_policy or SafetyPolicy()
        self._audit = audit_log or AuditLog(self._policy)
        if debug_safe_mode is None:
            from config.settings import settings as _settings
            debug_safe_mode = _settings.debug_safe_mode
        self._debug_safe_mode = bool(debug_safe_mode)

    @timed("executor.execute")
    def execute(
        self,
        plan: ExecutionPlan,
        cancel_event: threading.Event | None = None,
    ) -> ActionResult:
        """Run a plan and return a fully-structured ``ActionResult``.

        When *cancel_event* is provided it is checked before every step: a
        superseded task sets the event, so a background worker aborts at
        the next step boundary instead of continuing to act.  The plan
        also runs at most one tab-opening browser action per request.

        The result carries the plan's verification spec (``verification``),
        the wall-clock execution time (``duration_ms``) and the number of
        step retries (``retry_count``) so callers can audit every execution.
        """
        start_trace = stage_entry("executor.execute", input_=plan.intent)
        start = time.monotonic()
        retries = {"count": 0}
        result = self._execute_inner(plan, retries, cancel_event=cancel_event)
        elapsed_ms = (time.monotonic() - start) * 1000
        out = ActionResult(
            success=result.success,
            message=result.message,
            data=result.data,
            error=result.error,
            needs_clarification=result.needs_clarification,
            clarification_question=result.clarification_question,
            task_result=result.task_result,
            verification=self._verification_spec(plan),
            duration_ms=elapsed_ms,
            retry_count=retries["count"],
        )
        stage_exit("executor.execute", start_trace, status=out.task_result.value, output=out.message)
        return out

    def _execute_inner(
        self,
        plan: ExecutionPlan,
        retries: dict[str, int],
        cancel_event: threading.Event | None = None,
    ) -> ActionResult:
        """
        Execute every Step in a plan, in order.

        Safety checks performed before each step:
          1. Parameter sanitisation — reject known dangerous patterns.
          2. URL validation — reject unsafe or malformed URLs.
          3. File-path validation — reject non-existent or unsafe paths.
          4. Confirmation check — if the action is dangerous, return a
             clarification ActionResult.
          5. File-path re-validation for destructive operations.
          6. App-existence validation — warn if the app may not be installed.

        After execution the result is recorded in the audit log.
        """
        if not plan.steps:
            if plan.intent == "noop":
                return ActionResult(
                    success=True,
                    message="Okay, no action taken.",
                    data={"intent": plan.intent, "raw_text": plan.raw_text},
                    task_result=TaskResult.SUCCESS,
                )
            return ActionResult(
                success=False,
                message=(
                    "That request isn't something I can execute yet. "
                    "Rephrase it, or ask me what skills are missing to see "
                    "the roadmap."
                ),
                data={"intent": plan.intent, "raw_text": plan.raw_text},
                task_result=TaskResult.UNSUPPORTED,
            )

        results: list[dict[str, Any]] = []
        confirmed = plan.metadata.get("confirmed", False)
        step_actions = [s.action for s in plan.steps]
        browser_action_seen = False

        # --- 0c. Debug Safe Mode: never launch anything while enabled ---
        debug_block = self._debug_safe_mode_block(plan, step_actions)
        if debug_block:
            print(f"[DEBUG SAFE MODE] {debug_block}")
            self._audit.record_command(
                plan.intent, plan.raw_text, step_actions,
                confirmed=confirmed, success=False,
                details=debug_block,
                validation_failed="debug_safe_mode",
                validation_message=debug_block,
            )
            return ActionResult(
                success=False, message=debug_block,
                data={"intent": plan.intent, "raw_text": plan.raw_text},
                error="debug_safe_mode",
                task_result=TaskResult.FAILED,
            )

        for index, step in enumerate(plan.steps):
            action = step.action
            params = step.parameters or {}
            validation_failed = ""
            validation_message = ""
            fallback_rejected = ""
            parameter_details = ""

            # --- 0. Cancellation check (before anything else) ---
            if cancel_event is not None and cancel_event.is_set():
                logger.info(
                    "[EXECUTOR] Task cancelled before step %d (action=%r) — aborting",
                    index, action,
                )
                return self._cancelled_result(plan, results)

            # --- 0b. Safe Mode check ---
            safe_mode_block = self._execution_guard_check_safe_mode(action)
            if safe_mode_block:
                print(f"[SAFETY] Blocked by Safe Mode: {action}")
                self._audit.record_command(
                    plan.intent, plan.raw_text, step_actions,
                    confirmed=confirmed, success=False,
                    details=safe_mode_block,
                    validation_failed="safe_mode",
                    validation_message=safe_mode_block,
                )
                return ActionResult(
                    success=False, message=safe_mode_block,
                    data={"intent": plan.intent, "action": action},
                    error=safe_mode_block,
                    task_result=TaskResult.FAILED,
                )

            # --- 1. Parameter sanitisation (always, before anything else) ---
            pv = validate_parameters(action, params)
            if not pv.get("valid"):
                msg = pv.get("message", "Dangerous parameters detected")
                print(f"[SAFETY] Parameter validation failed: {msg}")
                self._audit.record_validation(action, False, msg)
                self._audit.record_command(
                    plan.intent, plan.raw_text, step_actions,
                    confirmed=confirmed, success=False, details=msg,
                    validation_failed="parameter_sanitisation",
                    validation_message=msg,
                )
                return ActionResult(
                    success=False, message=msg,
                    data={"intent": plan.intent, "action": action},
                    error=msg,
                    task_result=TaskResult.FAILED,
                )

            # --- 2. URL validation (for website navigation / search) ---
            if action in ("open_website", "search", "navigate", "browser_search"):
                url = params.get("url", "") or step.target or ""
                if url and not url.startswith(("http://", "https://")):
                    known = self._known_website_url(url)
                    if known:
                        params["url"] = known
                        url = known
                if url:
                    uv = validate_url(url)
                    if not uv.get("valid"):
                        msg = uv.get("message", f"Invalid URL: {url!r}")
                        print(f"[SAFETY] URL validation failed: {msg}")
                        self._audit.record_validation(action, False, msg)
                        self._audit.record_command(
                            plan.intent, plan.raw_text, step_actions,
                            confirmed=confirmed, success=False, details=msg,
                            validation_failed="url_validation",
                            validation_message=msg,
                        )
                        return ActionResult(
                            success=False, message=msg,
                            data={"intent": plan.intent, "action": action, "url": url},
                            error=msg,
                            task_result=TaskResult.FAILED,
                        )

            # --- 3. File-path validation (before confirmation so the user
            #        knows the path is valid before being asked) ---
            if self._policy.check_file_exists and action in (
                "open_file", "read_pdf", "ocr_image",
                "delete_file", "move_file", "copy_file", "rename_file",
            ):
                file_path = params.get("file_path") or params.get("file_query") or params.get("source", "")
                if file_path:
                    v = validate_file_path(file_path, action)
                    if not v.get("valid"):
                        msg = v.get("message", f"Invalid file path: {file_path!r}")
                        print(f"[SAFETY] Path validation failed: {msg}")
                        self._audit.record_validation(action, False, msg)
                        self._audit.record_command(
                            plan.intent, plan.raw_text, step_actions,
                            confirmed=confirmed, success=False, details=msg,
                            validation_failed="file_path_validation",
                            validation_message=msg,
                        )
                        return ActionResult(
                            success=False, message=msg,
                            data={"intent": plan.intent, "action": action, "path": file_path},
                            error=msg,
                            task_result=TaskResult.FAILED,
                        )

            # --- 4. Confirmation check ---
            if not confirmed and self._policy.needs_confirmation(action, params):
                reason = self._policy.confirmation_reason(action)
                question = f"{reason}. Are you sure?"
                print(f"[SAFETY] Confirmation required for {action!r}: {reason}")
                return ActionResult(
                    success=False,
                    message=question,
                    data={
                        "intent": plan.intent,
                        "raw_text": plan.raw_text,
                        "step_action": action,
                        "results": results,
                    },
                    needs_clarification=True,
                    clarification_question=question,
                    task_result=TaskResult.CLARIFICATION,
                )

            # --- 5. App-existence validation (for destructive file ops) ---
            if self._policy.check_file_exists and action in (
                "open_file", "read_pdf", "ocr_image",
                "delete_file", "move_file", "copy_file", "rename_file",
            ):
                file_path = params.get("file_path") or params.get("file_query") or params.get("source", "")
                if file_path:
                    v = validate_file_path(file_path, action)
                    if not v.get("valid"):
                        msg = v.get("message", f"Invalid file path: {file_path!r}")
                        print(f"[SAFETY] Path validation failed: {msg}")
                        self._audit.record_validation(action, False, msg)
                        self._audit.record_command(
                            plan.intent, plan.raw_text, step_actions,
                            confirmed=confirmed, success=False, details=msg,
                            validation_failed="file_path_validation",
                            validation_message=msg,
                        )
                        return ActionResult(
                            success=False, message=msg,
                            data={"intent": plan.intent, "action": action, "path": file_path},
                            error=msg,
                            task_result=TaskResult.FAILED,
                        )

            # --- 6. App-existence validation ---
            if self._policy.check_app_exists and action in (
                "open_app", "focus_app", "restart_app",
                "close_app", "minimize_app", "maximize_app", "restore_app",
            ):
                app_name = params.get("app_name") or params.get("original_app", "")
                if app_name:
                    v = validate_app_exists(app_name)
                    if not v.get("exists"):
                        msg = v.get("message", f"App {app_name!r} may not be installed")
                        print(f"[SAFETY] App validation: {msg}")
                        self._audit.record_validation(action, False, msg)
                        parameter_details = f"app={app_name}"

            # --- 7. One browser tab-opening action per request ---
            if action in _TAB_OPENING_ACTIONS:
                if browser_action_seen:
                    logger.warning(
                        "[EXECUTOR] Duplicate browser action %r — skipped to prevent "
                        "duplicate tabs/searches",
                        action,
                    )
                    results.append({
                        "step_index": index,
                        "action": action,
                        "success": True,
                        "skipped": True,
                        "result": None,
                    })
                    continue
                browser_action_seen = True

            # --- 8. Execute step ---
            logger.info(
                "Execution: step %d action=%r target=%r", index, action, step.target,
            )
            print(f"[EXECUTOR] Executing step {index}: action={action!r} target={step.target!r}")
            try:
                handler = self._registry.get_handler(action)
                print(f"[EXECUTOR]   Handler: {type(handler).__name__}")

                # Handlers that emit RETRYING are retried a few times
                # before we give up and report the in-progress state.
                max_attempts = 3
                attempt = 0
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        logger.info(
                            "[EXECUTOR] Task cancelled during step %d — aborting",
                            index,
                        )
                        return self._cancelled_result(plan, results)
                    attempt += 1
                    result = handler.run(step, voice_input=self._voice_input)
                    print(f"[EXECUTOR]   Result: {result!r}")
                    if cancel_event is not None and cancel_event.is_set():
                        logger.info(
                            "[EXECUTOR] Task cancelled after step %d returned — "
                            "discarding stale handler result",
                            index,
                        )
                        return self._cancelled_result(plan, results)
                    step_result = ActionResult.from_handler(result)
                    if (
                        step_result.task_result == TaskResult.RETRYING
                        and attempt < max_attempts
                    ):
                        retries["count"] += 1
                        print(f"[EXECUTOR]   Step retrying ({attempt}/{max_attempts}): {step_result.message}")
                        time.sleep(0.5)
                        continue
                    break

                results.append({
                    "step_index": index,
                    "action": action,
                    "success": step_result.success,
                    "result": step_result,
                })

                # Handlers asking the user a question: surface the distinct
                # USER_CONFIRMATION status (not a generic clarification).
                if step_result.task_result == TaskResult.USER_CONFIRMATION:
                    question = step_result.clarification_question or step_result.message
                    print(f"[EXECUTOR]   Step requires user confirmation: {question}")
                    return ActionResult(
                        success=False,
                        message=question,
                        data={
                            "intent": plan.intent,
                            "results": results,
                            "step_result": step_result.data,
                        },
                        needs_clarification=True,
                        clarification_question=question,
                        task_result=TaskResult.USER_CONFIRMATION,
                    )

                # Long-running steps: report the pending state so the caller
                # keeps the status instead of treating it as a hard failure.
                if step_result.task_result in (TaskResult.WAITING, TaskResult.RETRYING):
                    return ActionResult(
                        success=step_result.success,
                        message=step_result.message,
                        data={
                            "intent": plan.intent,
                            "results": results,
                            "step_result": step_result.data,
                        },
                        error=step_result.error,
                        task_result=step_result.task_result,
                    )

                if step_result.needs_clarification:
                    question = step_result.clarification_question or step_result.message
                    print(f"[EXECUTOR]   Step needs clarification: {question}")
                    return ActionResult(
                        success=False,
                        message=question,
                        data={
                            "intent": plan.intent,
                            "results": results,
                            "step_result": step_result.data,
                        },
                        needs_clarification=True,
                        clarification_question=question,
                        task_result=TaskResult.CLARIFICATION,
                    )

                if not step_result.success:
                    error_msg = step_result.message
                    error_detail = step_result.error or error_msg
                    print(f"[EXECUTOR]   Step returned failure: {error_msg}")
                    self._audit.record_command(
                        plan.intent, plan.raw_text, step_actions,
                        confirmed=confirmed, success=False, details=error_msg,
                        validation_failed=validation_failed,
                        validation_message=validation_message,
                        fallback_rejected=fallback_rejected,
                        parameter_details=parameter_details,
                    )
                    return ActionResult(
                        success=False,
                        message=error_msg,
                        data={
                            "intent": plan.intent,
                            "results": results,
                            "step_result": step_result.data,
                        },
                        error=error_detail,
                        task_result=TaskResult.FAILED,
                    )

            except Exception as exc:
                if isinstance(exc, KeyError) and exc.args:
                    error_message = f"KeyError: '{exc.args[0]}'"
                else:
                    error_message = f"{type(exc).__name__}: {exc}"

                print(f"[EXECUTOR]   EXCEPTION: {error_message}")
                self._audit.record_command(
                    plan.intent, plan.raw_text, step_actions,
                    confirmed=confirmed, success=False, details=error_message,
                    validation_failed=validation_failed,
                    validation_message=validation_message,
                    fallback_rejected=fallback_rejected,
                    parameter_details=parameter_details,
                )
                return ActionResult(
                    success=False,
                    message="I couldn't complete that request.",
                    data={
                        "intent": plan.intent,
                        "results": results,
                    },
                    error=error_message,
                    task_result=TaskResult.INTERNAL_ERROR,
                )

        # --- 8. Audit success ---
        self._audit.record_command(
            plan.intent, plan.raw_text, step_actions,
            confirmed=confirmed, success=True,
            parameter_details=parameter_details,
        )

        # Build a meaningful final message from step results
        final_messages = []
        for r in results:
            res = r.get("result")
            if isinstance(res, ActionResult):
                if res.success:
                    msg = res.message or f"Step {r['step_index']} completed."
                    final_messages.append(msg)
                else:
                    final_messages.append(res.message or f"Step {r['step_index']} failed.")
            else:
                final_messages.append(f"Step {r['step_index']} completed.")

        final_message = " | ".join(final_messages) if final_messages else f"All {len(results)} step(s) executed successfully."

        print(f"[EXECUTOR] All {len(results)} step(s) executed successfully.")
        return ActionResult(
            success=True,
            message=final_message,
            data={
                "intent": plan.intent,
                "results": results,
            },
            task_result=TaskResult.SUCCESS,
        )

    @staticmethod
    def _cancelled_result(
        plan: ExecutionPlan,
        results: list[dict[str, Any]],
    ) -> ActionResult:
        """Build the ActionResult returned when a task is cancelled mid-run."""
        logger.info("[EXECUTOR] Plan %r cancelled by task manager", plan.intent)
        return ActionResult(
            success=False,
            message="Operation cancelled.",
            data={
                "intent": plan.intent,
                "raw_text": plan.raw_text,
                "results": results,
            },
            error="cancelled",
            task_result=TaskResult.CANCELLED,
        )

    @staticmethod
    def _verification_spec(plan: ExecutionPlan) -> dict[str, Any] | None:
        """Extract the verification spec attached by the Intelligent Planner.

        Returns ``{"checks": [...]}`` (the per-plan ``VerificationCheck``
        dicts) or ``None`` when the plan carries no verification contract.
        """
        metadata = getattr(plan, "metadata", None) or {}
        checks = metadata.get("verification") or []
        if not checks:
            return None
        return {"checks": checks}

    @staticmethod
    def _known_website_url(name: str) -> str | None:
        """Resolve a known website short name to a full URL."""
        known = {
            "google": "https://www.google.com",
            "youtube": "https://www.youtube.com",
            "github": "https://github.com",
            "chatgpt": "https://chatgpt.com",
            "gmail": "https://mail.google.com",
            "stackoverflow": "https://stackoverflow.com",
            "reddit": "https://www.reddit.com",
            "wikipedia": "https://www.wikipedia.org",
            "twitter": "https://twitter.com",
            "facebook": "https://www.facebook.com",
            "instagram": "https://www.instagram.com",
            "linkedin": "https://www.linkedin.com",
            "amazon": "https://www.amazon.com",
            "netflix": "https://www.netflix.com",
            "spotify": "https://open.spotify.com",
            "maps": "https://maps.google.com",
            "drive": "https://drive.google.com",
            "docs": "https://docs.google.com",
            "calendar": "https://calendar.google.com",
            "meet": "https://meet.google.com",
            "bing": "https://www.bing.com",
            "duckduckgo": "https://duckduckgo.com",
        }
        return known.get(name.strip().casefold())

    # ------------------------------------------------------------------
    # Execution Guard — formal safety barrier
    # ------------------------------------------------------------------

    def _execution_guard_check_safe_mode(self, action: str) -> str:
        """Check if *action* is blocked by Safe Mode.

        Returns an error message if blocked, or empty string if allowed.
        """
        if self._policy.is_blocked_in_safe_mode(action):
            return (
                f"That action ({action!r}) is disabled while Safe Mode is enabled. "
                f"Disable Safe Mode to proceed."
            )
        return ""

    def _debug_safe_mode_block(self, plan: ExecutionPlan, step_actions: list[str]) -> str:
        """Return a Debug Safe Mode block message, or empty string when disabled.

        When Debug Safe Mode is enabled NO action is ever executed.  The
        message reports the detected intent and the target application so a
        developer can verify what *would* have run, then marks the execution
        as blocked.
        """
        if not self._debug_safe_mode:
            return ""
        target = ""
        for step in plan.steps:
            params = step.parameters or {}
            candidate = (
                params.get("app_name")
                or params.get("original_app")
                or params.get("website")
                or params.get("url")
                or params.get("file_path")
                or step.target
                or ""
            )
            if candidate:
                target = candidate
                break
        intent = plan.intent or "unknown"
        if step_actions:
            return (
                f"Detected Intent: {intent} | Target: {target or step_actions[0]} | "
                f"Execution blocked (Debug Mode)"
            )
        return (
            f"Detected Intent: {intent} | Target: {target or 'none'} | "
            f"Execution blocked (Debug Mode)"
        )

    def execution_guard(
        self,
        action: str,
        params: dict[str, Any],
        confirmed: bool,
    ) -> dict[str, Any] | None:
        """Run the full Execution Guard chain.

        Returns a Response dict if a check fails, or None if all checks pass.
        This is the formalised sequential guard described in the Stability Release:
            Intent validation → Target validation → Safety validation → Execution
        """
        # 1. Safe Mode
        safe_mode_block = self._execution_guard_check_safe_mode(action)
        if safe_mode_block:
            return {"success": False, "message": safe_mode_block}

        # 1b. Debug Safe Mode — never launch anything while enabled
        if self._debug_safe_mode:
            target = (
                params.get("app_name")
                or params.get("original_app")
                or params.get("website")
                or params.get("url")
                or params.get("file_path")
                or ""
            )
            return {
                "success": False,
                "message": (
                    f"Detected Intent: {action} | Target: {target or action} | "
                    f"Execution blocked (Debug Mode)"
                ),
            }

        # 2. Parameter sanitisation
        pv = validate_parameters(action, params)
        if not pv.get("valid"):
            return {
                "success": False,
                "message": pv.get("message", "Dangerous parameters detected"),
            }

        # 3. URL validation
        if action in ("open_website", "search", "navigate", "browser_search"):
            url = params.get("url", "")
            if url:
                uv = validate_url(url)
                if not uv.get("valid"):
                    return {
                        "success": False,
                        "message": uv.get("message", f"Invalid URL: {url!r}"),
                    }

        # 4. File path validation
        if action in (
            "open_file", "read_pdf", "ocr_image",
            "delete_file", "move_file", "copy_file", "rename_file",
        ):
            file_path = params.get("file_path") or params.get("file_query") or params.get("source", "")
            if file_path:
                fpv = validate_file_path(file_path, action)
                if not fpv.get("valid"):
                    return {
                        "success": False,
                        "message": fpv.get("message", f"Invalid file path: {file_path!r}"),
                    }

        # 5. Confirmation check
        if not confirmed and self._policy.needs_confirmation(action, params):
            return {
                "success": False,
                "needs_clarification": True,
                "clarification_question": f"{self._policy.confirmation_reason(action)}. Are you sure?",
                "message": f"{self._policy.confirmation_reason(action)}. Are you sure?",
            }

        # All checks passed
        return None
