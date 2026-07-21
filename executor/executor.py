"""
executor/executor.py

The Executor runs an ExecutionPlan by dispatching each Step to a handler
provided by a Registry. Integrates with the Safety & Confirmation Framework
to validate actions, request confirmation, and audit every command.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from brain.execution_plan import ExecutionPlan, Step
from executor.registry import Registry
from safety.policy import SafetyPolicy
from safety.audit import AuditLog
from safety.validator import validate_file_path, validate_app_exists, validate_parameters, validate_url


@dataclass(frozen=True)
class Response:
    """A structured summary of an execution attempt."""

    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    needs_clarification: bool = False
    clarification_question: str = ""


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
    ) -> None:
        self._registry = registry
        self._voice_input = voice_input
        self._policy = safety_policy or SafetyPolicy()
        self._audit = audit_log or AuditLog(self._policy)

    def execute(self, plan: ExecutionPlan) -> Response:
        """
        Execute every Step in a plan, in order.

        Safety checks performed before each step:
          1. Parameter sanitisation — reject known dangerous patterns.
          2. URL validation — reject unsafe or malformed URLs.
          3. File-path validation — reject non-existent or unsafe paths.
          4. Confirmation check — if the action is dangerous, return a
             clarification Response.
          5. File-path re-validation for destructive operations.
          6. App-existence validation — warn if the app may not be installed.

        After execution the result is recorded in the audit log.
        """
        if not plan.steps:
            return Response(
                success=False,
                message=f"Unknown command: '{plan.raw_text}'.",
                data={"intent": plan.intent, "raw_text": plan.raw_text},
            )

        results: list[dict[str, Any]] = []
        confirmed = plan.metadata.get("confirmed", False)
        step_actions = [s.action for s in plan.steps]

        for index, step in enumerate(plan.steps):
            action = step.action
            params = step.parameters or {}
            validation_failed = ""
            validation_message = ""
            fallback_rejected = ""
            parameter_details = ""

            # --- 0. Safe Mode check (before anything else) ---
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
                return Response(
                    success=False, message=safe_mode_block,
                    data={"intent": plan.intent, "action": action},
                    error=safe_mode_block,
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
                return Response(
                    success=False, message=msg,
                    data={"intent": plan.intent, "action": action},
                    error=msg,
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
                        return Response(
                            success=False, message=msg,
                            data={"intent": plan.intent, "action": action, "url": url},
                            error=msg,
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
                        return Response(
                            success=False, message=msg,
                            data={"intent": plan.intent, "action": action, "path": file_path},
                            error=msg,
                        )

            # --- 4. Confirmation check ---
            if not confirmed and self._policy.needs_confirmation(action, params):
                reason = self._policy.confirmation_reason(action)
                question = f"{reason}. Are you sure?"
                print(f"[SAFETY] Confirmation required for {action!r}: {reason}")
                return Response(
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
                        return Response(
                            success=False, message=msg,
                            data={"intent": plan.intent, "action": action, "path": file_path},
                            error=msg,
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

            # --- 7. Execute step ---
            print(f"[EXECUTOR] Executing step {index}: action={action!r} target={step.target!r}")
            try:
                handler = self._registry.get_handler(action)
                print(f"[EXECUTOR]   Handler: {type(handler).__name__}")
                result = handler.run(step, voice_input=self._voice_input)
                print(f"[EXECUTOR]   Result: {result!r}")

                # Check if the result is a structured dict with success=False
                if isinstance(result, dict):
                    if not result.get("success", True):
                        error_msg = result.get("message", "Step failed.")
                        error_detail = result.get("error", "")
                        print(f"[EXECUTOR]   Step returned failure: {error_msg}")
                        self._audit.record_command(
                            plan.intent, plan.raw_text, step_actions,
                            confirmed=confirmed, success=False, details=error_msg,
                            validation_failed=validation_failed,
                            validation_message=validation_message,
                            fallback_rejected=fallback_rejected,
                            parameter_details=parameter_details,
                        )
                        return Response(
                            success=False,
                            message=error_msg,
                            data={
                                "intent": plan.intent,
                                "results": results,
                                "step_result": result,
                            },
                            error=error_detail or error_msg,
                        )

                    # Check if the result needs clarification
                    if result.get("needs_clarification"):
                        question = result.get("clarification_question", "Could you clarify?")
                        print(f"[EXECUTOR]   Step needs clarification: {question}")
                        return Response(
                            success=False,
                            message=question,
                            data={
                                "intent": plan.intent,
                                "results": results,
                                "step_result": result,
                            },
                            needs_clarification=True,
                            clarification_question=question,
                        )

                results.append({
                    "step_index": index,
                    "action": action,
                    "success": True,
                    "result": result,
                })

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
                return Response(
                    success=False,
                    message=f"Step {index} (action={action!r}) failed: {exc}",
                    data={
                        "intent": plan.intent,
                        "results": results,
                    },
                    error=error_message,
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
            res = r.get("result", {})
            if isinstance(res, dict):
                msg = res.get("message", f"Step {r['step_index']} completed.")
                final_messages.append(msg)
            else:
                final_messages.append(f"Step {r['step_index']} completed.")

        final_message = " | ".join(final_messages) if final_messages else f"All {len(results)} step(s) executed successfully."

        print(f"[EXECUTOR] All {len(results)} step(s) executed successfully.")
        return Response(
            success=True,
            message=final_message,
            data={
                "intent": plan.intent,
                "results": results,
            },
        )

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
