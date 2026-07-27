from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from models.response import Response as ModelResponse
from thinking.decision_engine import Decision, DecisionEngine, DecisionType
from thinking.intent_recognizer import IntentRecognizer, RecognizedIntent
from thinking.response_generator import ResponseGenerator
from thinking.task_supervisor import TaskSupervisor
from thinking.verification_engine import VerificationEngine, VerificationResult

if TYPE_CHECKING:
    from brain.execution_plan import ExecutionPlan
    from brain.parsed_command import ParsedCommand
    from brain.parser import Parser
    from brain.planner import Planner
    from executor.executor import Executor
    from thinking.context_snapshot import ContextSnapshot
    from verification.task_verifier import TaskVerifier


class PipelineEngine:
    def __init__(
        self,
        parser: Parser = None,
        planner: Planner = None,
        executor: Executor = None,
        intent_recognizer: IntentRecognizer | None = None,
        decision_engine: DecisionEngine | None = None,
        task_supervisor: TaskSupervisor | None = None,
        verification_engine: VerificationEngine | None = None,
        response_generator: ResponseGenerator | None = None,
        context_manager: Any = None,
        task_verifier: Any = None,
    ) -> None:
        self._parser = parser
        self._planner = planner
        self._executor = executor

        self._intent_recognizer = intent_recognizer or IntentRecognizer()
        self._decision_engine = decision_engine or DecisionEngine()
        self._task_supervisor = task_supervisor or TaskSupervisor(task_verifier=task_verifier)
        self._verification_engine = verification_engine or VerificationEngine(task_verifier=task_verifier)
        self._response_generator = response_generator or ResponseGenerator()

        self._context_manager = context_manager
        self._task_verifier = task_verifier

        self._pending_parsed: ParsedCommand | None = None
        self._pending_recognized: RecognizedIntent | None = None
        self._original_text: str = ""

    @property
    def pending_clarification_exists(self) -> bool:
        return self._pending_parsed is not None

    def process(self, text: str, confirmed: bool = False) -> ModelResponse:
        print(f"\n{'='*60}")
        print(f"[PIPELINE] Engine.process() INPUT: {text!r} confirmed={confirmed}")
        print(f"{'='*60}")

        parsed = self._parse(text)
        if parsed is None:
            return ModelResponse(
                success=False,
                message="Parser failed while processing input.",
                data={"raw_text": text},
                error="Parser exception",
            )

        special = self._handle_special_intents(parsed)
        if special is not None:
            return special

        recognized = self._intent_recognizer.recognize(parsed)
        print(f"[PIPELINE] IntentRecognizer -> intent={recognized.intent} category={recognized.category} reasoning={recognized.reasoning}")

        snapshot = self._capture_context(recognized)
        print(f"[PIPELINE] ContextSnapshot -> apps={len(snapshot.apps)} browsers={len(snapshot.browsers)} protected_tabs={len(snapshot.protected_tabs)}")

        decision = self._decision_engine.decide(
            recognized=recognized,
            snapshot=snapshot,
            context_manager=self._context_manager,
            clarification=getattr(self._context_manager, "clarification", None) if self._context_manager else None,
        )
        print(f"[PIPELINE] DecisionEngine -> type={decision.type.name} reasoning={decision.reasoning}")

        if decision.type == DecisionType.ASK_CLARIFICATION:
            self._pending_parsed = parsed
            self._pending_recognized = recognized
            self._original_text = text
            return decision.response

        if decision.type == DecisionType.ABORT:
            self._pending_parsed = None
            self._pending_recognized = None
            self._original_text = ""
            return decision.response

        self._task_supervisor.start_supervision(recognized.intent, 1)

        plan = self._build_plan(parsed, recognized, decision, confirmed)
        if plan is None:
            self._task_supervisor.end_supervision()
            return ModelResponse(
                success=False,
                message="Planner failed while creating an execution plan.",
                data={"raw_text": text},
                error="Planner exception",
            )

        print(f"[PIPELINE] Planner -> steps={len(plan.steps)} intent={plan.intent}")
        for i, step in enumerate(plan.steps):
            print(f"[PIPELINE]   Step {i}: action={step.action!r} target={step.target!r}")

        if not confirmed and decision.metadata.get("requires_confirmation"):
            reason = decision.metadata.get("confirmation_reason", "This action may be destructive.")
            print(f"[PIPELINE] Dangerous intent — confirmation required: {reason}")
            self._pending_parsed = parsed
            self._pending_recognized = recognized
            self._original_text = text
            self._task_supervisor.end_supervision()
            return ModelResponse(
                success=False,
                message=f"Confirmation required: {reason}",
                data={"raw_text": text, "intent": plan.intent},
                needs_clarification=True,
                clarification_question=f"Are you sure you want to {plan.intent}?",
            )

        response = self._execute_with_supervision(plan, recognized)
        self._task_supervisor.end_supervision()

        verification = self._verify(response, recognized)
        if not verification.passed and verification.retry_response is not None:
            if getattr(verification.retry_response, "needs_clarification", False):
                self._pending_parsed = parsed
                self._pending_recognized = recognized
                self._original_text = text
                return verification.retry_response
            return verification.retry_response
        final_response = verification.details.get("verified_response", response)

        result = self._response_generator.generate(
            executor_response=final_response,
            intent=recognized.intent,
            raw_text=text,
            pipeline_reasoning=decision.reasoning,
        )

        print(f"{'='*60}\n")
        return result

    def resolve_context(self, answer: str) -> ModelResponse:
        if self._pending_parsed is None:
            return ModelResponse(success=False, message="No pending clarification.")

        parsed = self._pending_parsed
        recognized = self._pending_recognized
        text = self._original_text
        self._pending_parsed = None
        self._pending_recognized = None
        self._original_text = ""

        decision = self._decision_engine.decide_follow_up(
            answer=answer,
            recognized=recognized,
            context_manager=self._context_manager,
            task_supervisor=self._task_supervisor,
        )

        print(f"[PIPELINE] Follow-up DecisionEngine -> type={decision.type.name} reasoning={decision.reasoning}")

        if decision.type == DecisionType.ASK_CLARIFICATION:
            self._pending_parsed = parsed
            self._pending_recognized = recognized
            self._original_text = text
            return decision.response

        if decision.type == DecisionType.ABORT:
            return decision.response

        resolved_response = decision.response
        action = resolved_response.data.get("action", "unknown") if resolved_response else "unknown"
        context_data = resolved_response.data.get("context", {}) if resolved_response else {}

        if action == "none" or not resolved_response.data.get("intent"):
            return resolved_response

        if action == "select_browser":
            return resolved_response

        plan = self._build_resolved_plan(action, context_data, parsed, recognized, text)
        if plan is None:
            return ModelResponse(success=False, message="Could not build execution plan from resolved context.")

        self._task_supervisor.start_supervision(plan.intent, len(plan.steps))

        response = self._execute_with_supervision(plan, recognized)
        self._task_supervisor.end_supervision()

        verification = self._verify(response, recognized)
        final_response = verification.details.get("verified_response", response)

        result = self._response_generator.generate(
            executor_response=final_response,
            intent=plan.intent,
            raw_text=text,
        )
        print(f"[PIPELINE] Context resolve -> success={result.success} message={result.message!r}")
        return result

    def _parse(self, text: str) -> ParsedCommand | None:
        try:
            from brain.parser import Parser
            return self._parser.parse(text)
        except Exception as exc:
            print(f"[PIPELINE] Parser EXCEPTION: {type(exc).__name__}: {exc}")
            return None

    def _handle_special_intents(self, parsed: ParsedCommand) -> ModelResponse | None:
        if parsed.intent == "ambiguous":
            question = parsed.entities.get("question", "Could you clarify?")
            print(f"[PIPELINE] Ambiguous command — clarification needed.")
            return ModelResponse(
                success=False,
                message=question,
                data={"raw_text": parsed.raw_text, "app_phrase": parsed.entities.get("app_phrase", "")},
                needs_clarification=True,
                clarification_question=question,
            )

        if parsed.intent == "unknown":
            print(f"[PIPELINE] Unknown intent — returning friendly message")
            return ModelResponse(
                success=False,
                message="I don't know how to do that yet. You can try: open <app>, close <app>, search <query>, or type 'help'.",
                data={"raw_text": parsed.raw_text},
            )

        if parsed.confidence < 1.0:
            from safety.policy import SafetyPolicy
            policy = SafetyPolicy()
            confidence_check = policy.check_speech_confidence(parsed.confidence)
            if not confidence_check["accepted"]:
                reason = confidence_check["reason"]
                print(f"[PIPELINE] Speech confidence REJECTED: {reason}")
                return ModelResponse(
                    success=False,
                    message=reason,
                    data={"raw_text": parsed.raw_text, "confidence": parsed.confidence},
                )

        return None

    def _capture_context(self, recognized: RecognizedIntent) -> ContextSnapshot:
        from thinking.context_snapshot import BrowserTabInfo, BrowserWindowInfo, ContextSnapshot, RunningAppInfo

        snapshot = ContextSnapshot(timestamp=time.monotonic())

        if self._context_manager is None:
            return snapshot

        app_detector = getattr(self._context_manager, "app_detector", None)
        browser_detector = getattr(self._context_manager, "browser_detector", None)

        if app_detector is not None:
            try:
                apps = []
                running = getattr(app_detector, "get_all_running", None)
                if running is not None:
                    all_apps = running()
                    for a in all_apps:
                        if isinstance(a, dict):
                            apps.append(RunningAppInfo(
                                process_name=a.get("process_name", ""),
                                display_name=a.get("display_name", ""),
                                windows=a.get("windows", []),
                                is_focused=a.get("is_focused", False),
                            ))
                        elif hasattr(a, "process_name"):
                            apps.append(RunningAppInfo(
                                process_name=getattr(a, "process_name", ""),
                                display_name=getattr(a, "display_name", ""),
                                windows=getattr(a, "windows", []),
                                is_focused=getattr(a, "is_focused", False),
                            ))
                object.__setattr__(snapshot, "apps", apps)
            except Exception:
                pass

        if browser_detector is not None:
            try:
                browsers_data = []
                protected_tabs_list: list[BrowserTabInfo] = list(snapshot.protected_tabs)
                for browser in getattr(browser_detector, "_browsers", []):
                    tabs = []
                    active_tab = None
                    for tab in getattr(browser, "tabs", []):
                        tab_info = BrowserTabInfo(
                            id=getattr(tab, "id", 0),
                            window_id=getattr(tab, "window_id", 0),
                            title=getattr(tab, "title", ""),
                            url=getattr(tab, "url", ""),
                            active=getattr(tab, "active", False),
                            content_classification=browser_detector.classify_tab_content(tab) if hasattr(browser_detector, "classify_tab_content") else "unknown",
                        )
                        tabs.append(tab_info)
                        if tab_info.active:
                            active_tab = tab_info
                        url_lower = tab_info.url.casefold()
                        title_lower = tab_info.title.casefold()
                        protected_patterns = [
                            "chatgpt", "gmail", "docs.google.com/document",
                            "github.com", "bank", "paypal", "venmo",
                            "notion.so", "figma.com",
                        ]
                        if any(p in url_lower or p in title_lower for p in protected_patterns):
                            protected_tabs_list.append(tab_info)

                    browser_info = BrowserWindowInfo(
                        name=getattr(browser, "name", ""),
                        display_name=getattr(browser, "display_name", ""),
                        debug_port=getattr(browser, "debug_port", None),
                        process_name=getattr(browser, "process_name", ""),
                        tabs=tabs,
                        active_tab=active_tab,
                    )
                    browsers_data.append(browser_info)

                object.__setattr__(snapshot, "browsers", browsers_data)
                object.__setattr__(snapshot, "protected_tabs", protected_tabs_list)

                if browsers_data:
                    active = browser_detector.get_active_tab_across_browsers() if hasattr(browser_detector, "get_active_tab_across_browsers") else None
                    if active:
                        active_tab_info = BrowserTabInfo(
                            id=active.tab.id,
                            window_id=active.tab.window_id,
                            title=active.tab.title,
                            url=active.tab.url,
                            active=True,
                            content_classification=active.tab.content_classification if hasattr(active.tab, "content_classification") else "unknown",
                        )
                        object.__setattr__(snapshot, "active_tab", active_tab_info)
                        content = active_tab_info.content_classification
                        if content == "music":
                            object.__setattr__(snapshot, "music_playing", True)
                        elif content == "video":
                            object.__setattr__(snapshot, "video_playing", True)
            except Exception:
                pass

        return snapshot

    def _build_plan(
        self,
        parsed: ParsedCommand,
        recognized: RecognizedIntent,
        decision: Decision,
        confirmed: bool,
    ) -> ExecutionPlan | None:
        from brain.parsed_command import ParsedCommand as ParsedCmd
        try:
            if decision.metadata.get("requires_confirmation"):
                plan_parsed = ParsedCmd(
                    raw_text=parsed.raw_text,
                    intent=parsed.intent,
                    entities=parsed.entities,
                    confidence=parsed.confidence,
                )
                return self._planner.create_plan(plan_parsed, confirmed=False)
            return self._planner.create_plan(parsed, confirmed=confirmed)
        except Exception as exc:
            print(f"[PIPELINE] Planner EXCEPTION: {type(exc).__name__}: {exc}")
            return None

    def _execute_with_supervision(self, plan: ExecutionPlan, recognized: RecognizedIntent) -> ModelResponse:
        try:
            response = self._executor.execute(plan)
            print(f"[PIPELINE] Executor -> success={response.success} message={response.message!r}")
            return ModelResponse(
                success=response.success,
                message=response.message,
                data=response.data,
                error=getattr(response, "error", None),
                needs_clarification=getattr(response, "needs_clarification", False),
                clarification_question=getattr(response, "clarification_question", ""),
            )
        except Exception as exc:
            print(f"[PIPELINE] Executor EXCEPTION: {type(exc).__name__}: {exc}")
            return ModelResponse(
                success=False,
                message="Executor failed while running the execution plan.",
                data={"raw_text": plan.raw_text, "intent": plan.intent},
                error=f"{type(exc).__name__}: {exc}",
            )

    def _verify(self, response: ModelResponse, recognized: RecognizedIntent) -> VerificationResult:
        if not recognized.requires_verification:
            return VerificationResult(passed=True, message="Verification skipped for this intent.")
        return self._verification_engine.verify_execution(
            response,
            recognized.intent,
            recognized.entities,
        )

    def _build_resolved_plan(
        self,
        action: str,
        context: dict[str, Any],
        parsed: ParsedCommand,
        recognized: RecognizedIntent,
        text: str,
    ) -> ExecutionPlan | None:
        from brain.execution_plan import ExecutionPlan, Step
        from brain.parsed_command import ParsedCommand as ParsedCmd

        if action == "switch_to_existing":
            app_name = context.get("app_name") or context.get("display_name") or parsed.entities.get("app_name", "")
            return self._build_simple_plan(text, "focus_app", {"app_name": app_name}, parsed.confidence)

        if action == "switch_to_tab":
            port = context.get("debug_port")
            tab_id = context.get("tab_id")
            browser_name = context.get("browser_name", "chrome")
            cm = self._context_manager
            if port and tab_id and cm and hasattr(cm, "browser_detector"):
                cm.browser_detector.activate_tab(port, tab_id)
            return self._build_simple_plan(text, "focus_app", {"app_name": browser_name}, parsed.confidence)

        if action == "open_new_window":
            app_name = context.get("app_name") or context.get("display_name") or parsed.entities.get("app_name", "")
            browser_name = context.get("browser_name", "")
            if browser_name or app_name in ("chrome", "msedge", "brave", "opera", "vivaldi", "firefox"):
                app_name = browser_name or app_name
                return self._build_simple_plan(text, "open_app", {
                    "app_name": app_name, "focus_if_running": False, "new_window": True,
                }, parsed.confidence)
            return self._build_simple_plan(text, "open_app", {
                "app_name": app_name, "focus_if_running": False,
            }, parsed.confidence)

        if action == "open_new_tab":
            website = context.get("website", "") or parsed.entities.get("website", "")
            url_input = context.get("url", "") or parsed.entities.get("url", "")
            steps = [
                Step(action="new_tab", target=None, parameters={}, description="Open new tab."),
                Step(action="open_website", target=website, parameters={
                    "url": url_input, "open_in_new_tab": True,
                }, description=f"Open {website}."),
            ]
            return ExecutionPlan(
                raw_text=text, intent="open_website", confidence=parsed.confidence,
                steps=steps, metadata={"confirmed": True},
            )

        if action == "continue_current":
            return ExecutionPlan(
                raw_text=text, intent="noop", confidence=parsed.confidence,
                steps=[], metadata={"confirmed": True, "noop": True},
            )

        if action == "use_current_tab":
            query = context.get("query", "") or parsed.entities.get("query", "")
            provider = context.get("provider", "google") or parsed.entities.get("provider", "google")
            in_current = context.get("in_current_tab", False)
            return self._build_simple_plan(text, "search", {
                "query": query, "provider": provider, "in_current_tab": in_current,
            }, parsed.confidence)

        if action == "replace_music":
            query = context.get("query", "")
            return self._build_simple_plan(text, "search", {
                "query": query, "provider": "youtube", "in_current_tab": True,
            }, parsed.confidence)

        if action == "queue_music":
            query = context.get("query", "")
            steps = [
                Step(action="new_tab", target=None, parameters={}, description="Open new tab."),
                Step(action="search", target=query, parameters={
                    "query": query, "provider": "youtube", "open_in_new_tab": True,
                }, description=f"Search {query} on YouTube."),
            ]
            return ExecutionPlan(
                raw_text=text, intent="play_music", confidence=parsed.confidence,
                steps=steps, metadata={"confirmed": True},
            )

        if action == "replace_search":
            query = context.get("query", "")
            provider = context.get("provider", "google")
            return self._build_simple_plan(text, "search", {
                "query": query, "provider": provider, "in_current_tab": True,
            }, parsed.confidence)

        if action == "search_here":
            query = context.get("query", "")
            return self._build_simple_plan(text, "search", {
                "query": query, "provider": "youtube", "in_current_tab": True,
            }, parsed.confidence)

        if action == "search_there":
            query = context.get("query", "")
            return self._build_simple_plan(text, "search", {
                "query": query, "provider": "google", "in_current_tab": True,
            }, parsed.confidence)

        if action == "keep_music" or action == "keep":
            return ExecutionPlan(
                raw_text=text, intent="noop", confidence=parsed.confidence,
                steps=[], metadata={"confirmed": True, "noop": True},
            )

        print(f"[PIPELINE] Unknown resolved action: {action}")
        return None

    def _build_simple_plan(self, text: str, intent: str, entities: dict, confidence: float) -> ExecutionPlan:
        from brain.parsed_command import ParsedCommand as ParsedCmd
        new_parsed = ParsedCmd(raw_text=text, intent=intent, entities=entities, confidence=confidence)
        return self._planner.create_plan(new_parsed, confirmed=True)
