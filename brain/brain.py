"""
brain/brain.py

Brain is the single entry point and coordinator of the full pipeline:

    Brain.process(text)
        -> Parser.parse(text)            -> ParsedCommand
        -> Planner.create_plan(parsed)   -> ExecutionPlan
        -> Executor.execute(plan)        -> Response

Brain receives its dependencies (Parser, Planner, Executor) via its
constructor. It does not create them internally.

Brain handles ambiguity, speech-confidence rejection, and dangerous-intent
confirmation.
"""

from __future__ import annotations

from brain.parser import Parser
from brain.planner import Planner
from models.response import Response


class Brain:
    """
    Coordinates Parser -> Planner -> Executor -> Response.

    Dependencies are injected via the constructor.
    """

    def __init__(
        self,
        parser: Parser,
        planner: Planner,
        executor: Executor,
        safety_policy: SafetyPolicy | None = None,
    ) -> None:
        self._parser = parser
        self._planner = planner
        self._executor = executor
        self._policy = safety_policy
        if self._policy is None:
            from safety.policy import SafetyPolicy
            self._policy = SafetyPolicy()

    def process(self, text: str, confirmed: bool = False) -> Response:
        """
        Run the full pipeline for a single piece of user input.

        Steps:
            1. Parser.parse(text) -> ParsedCommand
            2. Speech-confidence check (reject very low confidence voice input)
            3. Planner.create_plan(parsed) -> ExecutionPlan
            4. Executor.execute(plan) -> Response

        When *confirmed* is True the dangerous-intent confirmation check
        is skipped (because the user already confirmed).
        """
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

        # Speech confidence check — reject or flag low-confidence input
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

        # Dangerous-intent confirmation (skipped when already confirmed)
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
