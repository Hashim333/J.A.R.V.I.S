from __future__ import annotations

from brain.parser import Parser
from brain.planner import Planner
from brain.parsed_command import ParsedCommand
from models.response import Response


class Brain:
    def __init__(
        self,
        parser: Parser,
        planner: Planner,
        executor: Executor,
        safety_policy: SafetyPolicy | None = None,
        context_manager: ContextManager | None = None,
    ) -> None:
        self._parser = parser
        self._planner = planner
        self._executor = executor
        self._policy = safety_policy
        if self._policy is None:
            from safety.policy import SafetyPolicy
            self._policy = SafetyPolicy()
        self._context_manager = context_manager
        self._pending_parsed: ParsedCommand | None = None
        self._original_text: str = ""

    def process(self, text: str, confirmed: bool = False) -> Response:
        print(f"\n{'='*60}")
        print(f"[PIPELINE] Brain.process() INPUT: {text!r} confirmed={confirmed}")
        print(f"{'='*60}")

        try:
            parsed = self._parser.parse(text)
        except Exception as exc:
            print(f"[PIPELINE] Parser EXCEPTION: {type(exc).__name__}: {exc}")
            return Response(
                success=False,
                message="Parser failed while processing input.",
                data={"raw_text": text},
                error=f"{type(exc).__name__}: {exc}",
            )

        print(f"[PIPELINE] Parser -> intent={parsed.intent!r} entities={parsed.entities} confidence={parsed.confidence}")

        # Handle ambiguity at the Brain level
        if parsed.intent == "ambiguous":
            question = parsed.entities.get("question", "Could you clarify?")
            print(f"[PIPELINE] Ambiguous command — clarification needed.")
            print(f"[PIPELINE] Question: {question}")
            return Response(
                success=False,
                message=question,
                data={"raw_text": text, "app_phrase": parsed.entities.get("app_phrase", "")},
                needs_clarification=True,
                clarification_question=question,
            )

        # Handle unknown intents gracefully
        if parsed.intent == "unknown":
            print(f"[PIPELINE] Unknown intent — returning friendly message")
            return Response(
                success=False,
                message=f"I don't know how to do that yet. You can try: open <app>, close <app>, search <query>, or type 'help'.",
                data={"raw_text": text},
            )

        # Speech confidence check
        if parsed.confidence < 1.0:
            confidence_check = self._policy.check_speech_confidence(parsed.confidence)
            if not confidence_check["accepted"]:
                reason = confidence_check["reason"]
                print(f"[PIPELINE] Speech confidence REJECTED: {reason}")
                return Response(
                    success=False,
                    message=reason,
                    data={"raw_text": text, "confidence": parsed.confidence},
                )
            if confidence_check.get("needs_confirmation"):
                reason = confidence_check["reason"]
                print(f"[PIPELINE] Speech confidence — needs confirmation: {reason}")

        # Context awareness check (before planning)
        if not confirmed and self._context_manager is not None:
            context_check = self._context_manager.check_before_execution(
                parsed.intent, parsed.entities, text
            )
            if context_check is not None:
                print(f"[PIPELINE] Context Manager — needs clarification: {context_check.message}")
                self._pending_parsed = parsed
                self._original_text = text
                return context_check

        try:
            plan = self._planner.create_plan(parsed, confirmed=confirmed)
        except Exception as exc:
            print(f"[PIPELINE] Planner EXCEPTION: {type(exc).__name__}: {exc}")
            return Response(
                success=False,
                message="Planner failed while creating an execution plan.",
                data={"raw_text": text},
                error=f"{type(exc).__name__}: {exc}",
            )

        print(f"[PIPELINE] Planner -> intent={plan.intent} reasoning={plan.metadata.get('reasoning', 'N/A')[:80]}...")
        print(f"[PIPELINE] Planner -> steps={len(plan.steps)}")
        for i, step in enumerate(plan.steps):
            print(f"[PIPELINE]   Step {i}: action={step.action!r} target={step.target!r} params={step.parameters}")

        # Dangerous-intent confirmation
        if not confirmed and plan.metadata.get("requires_confirmation"):
            reason = plan.metadata.get("confirmation_reason", "This action may be destructive.")
            print(f"[PIPELINE] Dangerous intent — confirmation required: {reason}")
            return Response(
                success=False,
                message=f"Confirmation required: {reason}",
                data={"raw_text": text, "intent": plan.intent},
                needs_clarification=True,
                clarification_question=f"Are you sure you want to {plan.intent}?",
            )

        try:
            response = self._executor.execute(plan)
        except Exception as exc:
            print(f"[PIPELINE] Executor EXCEPTION: {type(exc).__name__}: {exc}")
            return Response(
                success=False,
                message="Executor failed while running the execution plan.",
                data={"raw_text": text, "intent": plan.intent},
                error=f"{type(exc).__name__}: {exc}",
            )

        print(f"[PIPELINE] Executor -> success={response.success} message={response.message!r}")
        if hasattr(response, 'error') and response.error:
            print(f"[PIPELINE] Executor -> error={response.error!r}")
        print(f"{'='*60}\n")
        return response

    def resolve_context(self, answer: str) -> Response:
        if self._context_manager is None or self._pending_parsed is None:
            return Response(
                success=False,
                message="No pending context clarification.",
            )

        resolved = self._context_manager.handle_follow_up(answer)
        if resolved is None or not resolved.success:
            return resolved or Response(
                success=False,
                message="Could not resolve context.",
            )

        action = resolved.data.get("action", "unknown")
        new_intent = resolved.data.get("intent", "")
        context = resolved.data.get("context", {})

        print(f"[PIPELINE] Context resolved: action={action} intent={new_intent}")

        # Get the original parsed command
        parsed = self._pending_parsed
        text = self._original_text

        # Build a new ParsedCommand based on the resolved action
        if new_intent:
            new_entities = dict(parsed.entities)
            if new_intent == "focus_app":
                new_entities["focus_if_running"] = True
            elif new_intent == "open_app":
                new_entities["focus_if_running"] = False
            elif new_intent == "search":
                new_entities["in_new_tab"] = True
            elif new_intent == "open_website":
                new_entities["open_in_new_tab"] = True

            new_parsed = ParsedCommand(
                raw_text=text,
                intent=new_intent,
                entities=new_entities,
                confidence=parsed.confidence,
            )
        else:
            new_parsed = parsed

        self._pending_parsed = None
        self._original_text = ""

        try:
            plan = self._planner.create_plan(new_parsed, confirmed=True)
        except Exception as exc:
            print(f"[PIPELINE] Planner EXCEPTION (context resolve): {type(exc).__name__}: {exc}")
            return Response(
                success=False,
                message="Planner failed while creating execution plan.",
                data={"raw_text": text},
                error=f"{type(exc).__name__}: {exc}",
            )

        try:
            response = self._executor.execute(plan)
        except Exception as exc:
            print(f"[PIPELINE] Executor EXCEPTION (context resolve): {type(exc).__name__}: {exc}")
            return Response(
                success=False,
                message="Executor failed while running execution plan.",
                data={"raw_text": text, "intent": plan.intent},
                error=f"{type(exc).__name__}: {exc}",
            )

        print(f"[PIPELINE] Context resolve -> success={response.success} message={response.message!r}")
        return response
