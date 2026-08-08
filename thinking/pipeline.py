from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from intelligence.intelligent_planner import (
    IntelligentPlanner,
    UserChoice,
    VerificationCheck,
)
from models.diagnostic import DiagnosticReport
from models.response import Response as ModelResponse
from models.task_result import TaskResult
from monitoring.performance import log_duration
from monitoring.instrumentation import timed
from monitoring.pipeline_trace import stage_entry, stage_exit
from thinking.confirmation import ConfirmationEngine
from thinking.decision_engine import Decision, DecisionEngine, DecisionType
from thinking.intent_recognizer import IntentRecognizer, RecognizedIntent
from thinking.reasoner import Reasoner, ReasonedPlan
from thinking.response_generator import ResponseGenerator
from thinking.task_supervisor import TaskSupervisor
from thinking.utterance_classifier import (
    NON_ACTION_CATEGORIES,
    ClassificationResult,
    UtteranceCategory,
    UtteranceClassifier,
)
from thinking.verification_engine import VerificationEngine, VerificationResult

if TYPE_CHECKING:
    from brain.execution_plan import ExecutionPlan
    from brain.parsed_command import ParsedCommand
    from brain.parser import Parser
    from brain.planner import Planner
    from executor.executor import Executor
    from thinking.context_snapshot import ContextSnapshot
    from verification.task_verifier import TaskVerifier

logger = logging.getLogger(__name__)

# Intents that never represent a real task (excluded from context-switch
# detection in resolve_context).
_NON_ACTIONABLE_INTENTS: frozenset[str] = frozenset({
    "unknown", "ambiguous", "noop", "help", "compound",
})

# Primary entity used to decide whether two commands are the "same request".
_PRIMARY_ENTITY: dict[str, str] = {
    "open_app": "app_name",
    "open_website": "website",
    "search": "query",
    "play_music": "query",
    "play_video": "query",
    "focus_app": "app_name",
    "close_app": "app_name",
}


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
        utterance_classifier: UtteranceClassifier | None = None,
        intelligent_planner: IntelligentPlanner | None = None,
        world_state: Any = None,
        reasoner: Reasoner | None = None,
        working_memory: Any = None,
        system_awareness: Any = None,
        skill_manager: Any = None,
    ) -> None:
        self._parser = parser
        self._planner = planner
        self._executor = executor

        self._intent_recognizer = intent_recognizer or IntentRecognizer()
        self._decision_engine = decision_engine or DecisionEngine()
        self._task_supervisor = task_supervisor or TaskSupervisor(task_verifier=task_verifier)
        self._verification_engine = verification_engine or VerificationEngine(task_verifier=task_verifier)
        self._response_generator = response_generator or ResponseGenerator()
        self._confirmation = ConfirmationEngine()
        self._classifier = utterance_classifier or UtteranceClassifier()

        self._context_manager = context_manager
        self._task_verifier = task_verifier
        self._world_state = world_state
        self._reasoner = reasoner
        self._working_memory = working_memory
        self._system_awareness = system_awareness
        self._skill_manager = skill_manager
        self._intelligent_planner = intelligent_planner or IntelligentPlanner(
            world_state=world_state,
        )

        self._pending_parsed: ParsedCommand | None = None
        self._pending_recognized: RecognizedIntent | None = None
        self._original_text: str = ""
        self._pending_confirmation: bool = False
        self._pending_choice: UserChoice | None = None
        # Reasoner clarification state: an LLM question awaiting an answer.
        self._pending_reasoned: ReasonedPlan | None = None
        self._pending_reasoned_text: str = ""
        # Context-switch state: a brand-new task detected while waiting on a
        # pending clarification. The user is asked "cancel X and do Y instead?".
        self._pending_switch_parsed: ParsedCommand | None = None
        self._pending_switch_text: str = ""
        self._pending_switch_question: str = ""
        self._pending_switch_original_question: str = ""
        # ASR confidence of the current utterance (None for typed input).
        self._speech_confidence: float | None = None
        self._request_started_at: float = 0.0

    @property
    def pending_clarification_exists(self) -> bool:
        return self._pending_parsed is not None or self._pending_reasoned is not None

    @timed("pipeline.process")
    @log_duration()
    def process(
        self,
        text: str,
        confirmed: bool = False,
        cancel_event: Any = None,
        speech_confidence: float | None = None,
    ) -> ModelResponse:
        logger.info(
            "Pipeline INPUT: %r confirmed=%s speech_confidence=%s",
            text, confirmed,
            f"{speech_confidence:.3f}" if speech_confidence is not None else None,
        )
        self._speech_confidence = speech_confidence
        self._request_started_at = time.monotonic()
        result = self._process_inner(text, confirmed, cancel_event)
        return self._with_speech_confidence(result)

    def _process_inner(
        self,
        text: str,
        confirmed: bool,
        cancel_event: Any,
    ) -> ModelResponse:
        self._remember_command(text)

        # -- 0a. System Awareness gate (instant, no LLM) --
        # Questions about the live computer state (battery, RAM, tabs,
        # downloads, processes, storage, ...) are answered directly from the
        # continuously-maintained awareness snapshot.  Deterministic and
        # instant — the brain never has to search.  Falls through unchanged
        # when the utterance is not a system-awareness question.
        instant = self._try_system_answer(text)
        if instant is not None:
            return instant

        # -- 0b. Skill Awareness gate (deterministic, no LLM) --
        # Capability meta-commands ("what can you do?", "what skills are
        # missing?") and requests that map to acknowledged-but-unimplemented
        # skills are answered directly by the Skill Manager.  Missing
        # capabilities are registered in the persistent Skill Registry and
        # replied to with the closest available capability.
        skill_reply = self._try_skill_answer(text)
        if skill_reply is not None:
            return skill_reply

        # -- 0c. Local command dictionary gate (deterministic, no LLM) --
        # Simple commands that the rule-based parser understands (open apps,
        # volume, media control, shutdown, time/settings, ...) execute
        # directly.  This runs BEFORE the LLM reasoner so common commands
        # like "Open Chrome" / "What time is it" / "Play music" begin
        # execution instantly (under one second) without any LLM round-trip.
        fast = self._try_deterministic_command(text, confirmed, cancel_event)
        if fast is not None:
            return fast

        # -- 0d. Reasoning gate (LLM) --
        # The reasoner decides ANSWER / ASK / ACT for anything the local
        # command dictionary did not resolve.  ANSWER and ASK are handled
        # directly; ACT hands off to the deterministic stages below.  When
        # the LLM is unreachable it returns None and the classic
        # classification gate takes over unchanged — the rule pipeline is
        # always the fallback.
        reasoned = self._try_reason(text)
        if reasoned is not None:
            return self._handle_reasoned(reasoned, text, confirmed, cancel_event)

        # -- 0e. Classification gate (default pipeline) --
        # Every utterance is classified first. CHAT / QUESTION /
        # CONFIRMATION / CANCELLATION are answered directly by the LLM and
        # never reach the executor. Action categories continue to the
        # Parser → Planner → Executor path below.
        cls_start = stage_entry("pipeline.classify", input_=text)
        classification = self._classifier.classify(text)
        stage_exit("pipeline.classify", cls_start, status=classification.category.value)
        self._log_classification(text, classification)

        if classification.category in NON_ACTION_CATEGORIES:
            return self._chat_response(text, classification)

        # -- 1. Parse --
        parse_start = stage_entry("pipeline.parse", input_=text)
        parsed, diag = self._try_parse(text)
        stage_exit("pipeline.parse", parse_start, status="OK" if parsed else "FAIL")
        if parsed is None:
            return self._fail(TaskResult.INTERNAL_ERROR, "Parser failed while processing input.",
                              "Parser exception", diag, text)

        # -- 2. Special intents (ambiguous/unknown/low confidence) --
        special = self._handle_special_intents(parsed)
        if special is not None:
            return special

        # -- 3..10. Deterministic stages --
        return self._run_stages(parsed, text, confirmed, cancel_event)

    # ------------------------------------------------------------------
    # System Awareness gate helpers
    # ------------------------------------------------------------------

    def _try_system_answer(self, text: str) -> ModelResponse | None:
        """Answer a system-awareness question instantly from the live snapshot.

        Returns a finished ``ModelResponse`` when the utterance maps to a
        known awareness domain, otherwise ``None`` (continue the pipeline).
        Never raises.
        """
        if self._system_awareness is None:
            return None
        try:
            from system_awareness import answer
            snapshot = self._system_awareness.current()
            reply = answer(snapshot, text)
        except Exception as exc:
            logger.warning("System awareness answer failed: %s", exc, exc_info=True)
            return None
        if reply is None:
            return None
        logger.info("System awareness ANSWER: %r → %r", text, reply)
        return ModelResponse(
            success=True,
            message=reply,
            data={"raw_text": text, "category": "system_awareness"},
            task_result=TaskResult.SUCCESS,
            confidence=0.95,
            reasoning="Answered instantly from the live system-awareness snapshot.",
        )

    # ------------------------------------------------------------------
    # Skill Awareness gate helpers
    # ------------------------------------------------------------------

    def _try_skill_answer(self, text: str) -> ModelResponse | None:
        """Answer capability meta-commands and missing-capability requests.

        Runs before the LLM reasoner so capability questions and requests
        for acknowledged-but-unimplemented skills are answered determin-
        istically, registered in the Skill Registry, and never fall through
        to a generic "I can only..." / "Command not found" reply.
        """
        if self._skill_manager is None:
            return None
        try:
            reply = self._skill_manager.answer(text)
        except Exception as exc:
            logger.warning("SkillManager.answer raised %s — continuing", exc, exc_info=True)
            reply = None
        if reply is not None:
            return reply

        # Classify an unparseable request into a missing capability.  Only
        # fires when the deterministic parser could not handle it, so real
        # commands are never intercepted.
        try:
            if self._parser is not None:
                parsed = self._parser.parse(text)
                if parsed is None or parsed.intent == "unknown":
                    match = self._skill_manager.classify_missing(text)
                    if match is not None:
                        return self._skill_manager.respond_missing(
                            text, match, speech_confidence=self._speech_confidence,
                        )
        except Exception as exc:
            logger.warning("SkillManager missing-classify raised %s — continuing", exc, exc_info=True)
        return None

    def _skill_unknown_response(self, parsed: ParsedCommand) -> ModelResponse:
        """Reply to an unparseable request without a canned refusal.

        Tries the Skill Manager (register + closest capability); when the
        request cannot be classified, asks for a rephrase.  Never replies
        "I can only open and close apps" / "Command not found" / "I don't
        know."
        """
        text = parsed.raw_text
        if self._skill_manager is not None:
            try:
                match = self._skill_manager.classify_missing(text)
                if match is not None:
                    return self._skill_manager.respond_missing(
                        text, match, speech_confidence=self._speech_confidence,
                    )
            except Exception as exc:
                logger.warning("SkillManager missing-classify raised %s", exc, exc_info=True)
            try:
                return self._skill_manager.respond_unintelligible(
                    text, speech_confidence=self._speech_confidence,
                )
            except Exception as exc:
                logger.warning("SkillManager unintelligible raised %s", exc, exc_info=True)
        # Safety net when no Skill Manager is wired in.
        return ModelResponse(
            success=False,
            message="I couldn't determine the requested action. Could you rephrase it?",
            data={"raw_text": parsed.raw_text},
        )

    # ------------------------------------------------------------------
    # Local command dictionary gate helpers
    # ------------------------------------------------------------------

    def _try_deterministic_command(
        self,
        text: str,
        confirmed: bool,
        cancel_event: Any,
    ) -> ModelResponse | None:
        """Execute a simple, rule-parsed command with no LLM round-trip.

        Runs the deterministic parser ahead of the LLM reasoner.  Only
        concrete, actionable intents short-circuit — chat / questions /
        ambiguous / unknown utterances fall through to the LLM.  Returns a
        finished ``ModelResponse`` or ``None`` (continue the pipeline).
        """
        parsed = self._parse(text)
        if parsed is None:
            return None
        if parsed.intent in _NON_ACTIONABLE_INTENTS:
            return None

        special = self._handle_special_intents(parsed)
        if special is not None:
            return special

        logger.info(
            "LOCAL COMMAND — intent=%s (no LLM) raw=%r",
            parsed.intent, text,
        )
        return self._run_stages(parsed, text, confirmed, cancel_event)

    # ------------------------------------------------------------------
    # Reasoning gate helpers
    # ------------------------------------------------------------------

    def _try_reason(self, text: str) -> ReasonedPlan | None:
        """Ask the LLM reasoner to decide ANSWER / ASK / ACT.

        Never raises and returns ``None`` when the reasoner is not wired
        in or the LLM is unreachable, so the rule pipeline is the fallback.
        """
        if self._reasoner is None:
            return None
        try:
            world = self._world_state.current() if self._world_state is not None else None
        except Exception:
            world = None
        try:
            awareness = self._system_awareness.current() if self._system_awareness is not None else None
        except Exception:
            awareness = None
        try:
            return self._reasoner.reason(
                text, memory=self._working_memory, world_state=world,
                awareness=awareness,
            )
        except Exception as exc:
            logger.warning("Reasoner.reason raised %s — falling back to rule pipeline", exc, exc_info=True)
            return None

    def _try_continue_reasoning(self, text: str, question: str, answer: str) -> ReasonedPlan | None:
        if self._reasoner is None:
            return None
        try:
            world = self._world_state.current() if self._world_state is not None else None
        except Exception:
            world = None
        try:
            awareness = self._system_awareness.current() if self._system_awareness is not None else None
        except Exception:
            awareness = None
        try:
            return self._reasoner.continue_(
                original_text=text, question=question, answer=answer,
                memory=self._working_memory, world_state=world,
                awareness=awareness,
            )
        except Exception as exc:
            logger.warning("Reasoner.continue_ raised %s — falling back", exc, exc_info=True)
            return None

    def _handle_reasoned(
        self,
        reasoned: ReasonedPlan,
        text: str,
        confirmed: bool,
        cancel_event: Any,
    ) -> ModelResponse:
        """Dispatch a reasoner decision.  ACT hands off to the
        deterministic stages; ASK and ANSWER are answered directly."""
        if reasoned.mode == "ANSWER":
            return self._reasoned_answer_response(text, reasoned)
        if reasoned.mode == "ASK":
            return self._reasoned_ask_response(text, reasoned)

        parsed = self._parsed_from_reasoned(text, reasoned)
        if parsed is None:
            return ModelResponse(
                success=False,
                message="I couldn't turn that request into an action. Could you rephrase it?",
                data={"raw_text": text},
                task_result=TaskResult.FAILED,
                confidence=reasoned.confidence,
                reasoning=reasoned.reasoning,
            )
        return self._run_stages(parsed, text, confirmed, cancel_event, reasoned=reasoned)

    @staticmethod
    def _parsed_from_reasoned(text: str, plan: Any) -> Any:
        """Build a ParsedCommand from a ReasonedPlan or Alternative."""
        from brain.parsed_command import ParsedCommand as ParsedCmd
        try:
            return ParsedCmd(
                raw_text=text,
                intent=plan.intent,
                entities=dict(plan.entities),
                confidence=plan.confidence if hasattr(plan, "confidence") else 0.5,
            )
        except Exception as exc:
            logger.error("Could not build ParsedCommand from reasoned plan: %s", exc)
            return None

    def _reasoned_answer_response(self, text: str, reasoned: ReasonedPlan) -> ModelResponse:
        answer = reasoned.answer or "I understood that as a question, but I don't have a confident answer."
        return ModelResponse(
            success=True,
            message=ResponseGenerator._hedge(answer, reasoned.confidence),
            data={"raw_text": text, "category": "reasoner_answer", "reasoning": reasoned.reasoning},
            task_result=TaskResult.SUCCESS,
            confidence=reasoned.confidence,
            reasoning=reasoned.reasoning,
        )

    def _reasoned_ask_response(self, text: str, reasoned: ReasonedPlan) -> ModelResponse:
        self._pending_reasoned = reasoned
        self._pending_reasoned_text = text
        question = reasoned.question or "Could you clarify what you'd like me to do?"
        return ModelResponse(
            success=False,
            message=question,
            data={"raw_text": text, "intent": reasoned.intent},
            needs_clarification=True,
            clarification_question=question,
            task_result=TaskResult.CLARIFICATION,
            confidence=reasoned.confidence,
            reasoning=reasoned.reasoning,
        )

    def _continue_reasoning(self, answer: str, cancel_event: Any) -> ModelResponse:
        """Re-reason after the user answers a reasoner clarification."""
        reasoned = self._pending_reasoned
        text = self._pending_reasoned_text
        if reasoned is None:
            return ModelResponse(success=False, message="No pending question.", task_result=TaskResult.FAILED)

        next_plan = self._try_continue_reasoning(text, reasoned.question, answer)
        if next_plan is None:
            # LLM unreachable — keep the question pending and say so honestly.
            return ModelResponse(
                success=False,
                message=(
                    f"I couldn't reach my language model to process your answer. "
                    f"{reasoned.question or 'Could you try again?'}"
                ),
                data={"raw_text": answer},
                needs_clarification=True,
                clarification_question=reasoned.question,
                task_result=TaskResult.CLARIFICATION,
                confidence=reasoned.confidence,
                reasoning=reasoned.reasoning,
            )

        if next_plan.mode == "ANSWER":
            self._pending_reasoned = None
            self._pending_reasoned_text = ""
            return self._reasoned_answer_response(answer, next_plan)

        if next_plan.mode == "ASK":
            self._pending_reasoned = next_plan
            self._pending_reasoned_text = text
            return self._reasoned_ask_response(text, next_plan)

        # ACT — run the deterministic stages with the resolved plan.
        self._pending_reasoned = None
        self._pending_reasoned_text = ""
        parsed = self._parsed_from_reasoned(text, next_plan)
        if parsed is None:
            return ModelResponse(
                success=False,
                message="I couldn't turn that into an action. Could you rephrase it?",
                data={"raw_text": answer},
                task_result=TaskResult.FAILED,
                confidence=next_plan.confidence,
            )
        return self._run_stages(parsed, text, confirmed=False, cancel_event=cancel_event, reasoned=next_plan)

    # ------------------------------------------------------------------
    # Working memory
    # ------------------------------------------------------------------

    def _remember_command(self, text: str) -> None:
        if self._working_memory is None:
            return
        try:
            self._working_memory.add_command(text)
        except Exception as exc:
            logger.warning("WorkingMemory.add_command failed: %s", exc)

    def _remember_action(self, text: str, outcome: str) -> None:
        if self._working_memory is None:
            return
        try:
            self._working_memory.add_action(f"{text} → {outcome}")
        except Exception as exc:
            logger.warning("WorkingMemory.add_action failed: %s", exc)

    # ------------------------------------------------------------------
    # Deterministic stages 3..10 (shared by rule and reasoner paths)
    # ------------------------------------------------------------------

    def _run_stages(
        self,
        parsed: ParsedCommand,
        text: str,
        confirmed: bool,
        cancel_event: Any,
        reasoned: ReasonedPlan | None = None,
        retried: bool = False,
    ) -> ModelResponse:
        """Recognize → context → decide → plan → confirm → execute → verify
        → respond.

        When ``reasoned`` carries alternatives and execution or verification
        fails, the pipeline auto-retries ONCE with the first alternative,
        then explains both failures and asks the user how to proceed.
        """
        confidence = reasoned.confidence if reasoned is not None else parsed.confidence
        category_label = "REASONED_ACT" if reasoned is not None else "RULE"

        # -- 3. Recognize intent --
        recog_start = stage_entry("pipeline.recognize")
        recognized, diag = self._try_recognize(parsed)
        stage_exit("pipeline.recognize", recog_start, status="OK" if recognized else "FAIL")
        if recognized is None:
            return self._fail(TaskResult.INTERNAL_ERROR, "Intent recognition failed.",
                              "IntentRecognizer exception", diag, text)
        logger.info("  intent=%s category=%s", recognized.intent, recognized.category)

        # -- 4. Capture context --
        snap_start = stage_entry("pipeline.context")
        snapshot, diag = self._try_capture_context(recognized)
        stage_exit("pipeline.context", snap_start, status="OK" if snapshot else "FAIL")
        if snapshot is None:
            return self._fail(TaskResult.INTERNAL_ERROR, "Context capture failed.",
                              "ContextSnapshot exception", diag, text)

        # -- 5. Decide --
        decide_start = stage_entry("pipeline.decide")
        decision, diag = self._try_decide(recognized, snapshot)
        stage_exit("pipeline.decide", decide_start, status="OK" if decision else "FAIL")
        if decision is None:
            return self._fail(TaskResult.INTERNAL_ERROR, "Decision engine failed.",
                              "DecisionEngine exception", diag, text)
        logger.info("  decision=%s reasoning=%s", decision.type.name, decision.reasoning)

        if decision.type == DecisionType.ASK_CLARIFICATION:
            self._pending_parsed = parsed
            self._pending_recognized = recognized
            self._original_text = text
            return self._patch_result(decision.response, TaskResult.CLARIFICATION)

        if decision.type == DecisionType.ABORT:
            self._pending_parsed = None
            self._pending_recognized = None
            self._original_text = ""
            return self._patch_result(decision.response, TaskResult.UNSUPPORTED)

        # -- 6. Plan (intelligent, world-state-aware) --
        self._task_supervisor.start_supervision(recognized.intent, 1)
        plan_start = stage_entry("pipeline.plan")
        plan_result, diag = self._try_intelligent_plan(parsed, recognized, decision, confirmed)
        stage_exit("pipeline.plan", plan_start, status="OK" if plan_result is not None else "FAIL")
        if plan_result is None:
            self._task_supervisor.end_supervision()
            return self._fail(TaskResult.FAILED, "Planner failed while creating an execution plan.",
                              "Planner exception", diag, text)
        plan = plan_result.plan

        # The planner asked the user a state-aware question (e.g. which
        # window to close). Hold the intent and ask it.
        if plan_result.user_choice is not None:
            self._task_supervisor.end_supervision()
            self._pending_parsed = parsed
            self._pending_recognized = recognized
            self._original_text = text
            self._pending_choice = plan_result.user_choice
            question = plan_result.user_choice.question
            logger.info("IntelligentPlanner choice: %s — %s", plan_result.user_choice.kind, question)
            return ModelResponse(
                success=False,
                message=question,
                data={"raw_text": text, "intent": recognized.intent},
                needs_clarification=True,
                clarification_question=question,
                task_result=TaskResult.USER_CONFIRMATION,
                confidence=confidence,
            )

        logger.info("  plan steps=%d intent=%s", len(plan.steps), plan.intent)

        # -- 7. Confirmation gate --
        if not confirmed and decision.metadata.get("requires_confirmation"):
            reason = decision.metadata.get("confirmation_reason", "This action may be destructive.")
            logger.info("  confirmation required: %s", reason)
            self._pending_parsed = parsed
            self._pending_recognized = recognized
            self._original_text = text
            self._pending_confirmation = True
            self._task_supervisor.end_supervision()
            question = self._confirmation.build_question(recognized.intent, recognized.entities)
            return ModelResponse(
                success=False,
                message=question,
                data={"raw_text": text, "intent": recognized.intent},
                needs_clarification=True,
                clarification_question=question,
                task_result=TaskResult.CLARIFICATION,
                confidence=confidence,
            )

        # -- 8. Execute --
        exec_start = stage_entry("pipeline.execute", input_=plan.intent)
        response, diag = self._try_execute(plan, recognized, cancel_event=cancel_event)
        stage_exit("pipeline.execute", exec_start, status=response.task_result.value, output=response.message)
        self._task_supervisor.end_supervision()
        logger.info("IntelligentPlanner ACTION: success=%s status=%s message=%r",
                     response.success, response.task_result.value, response.message)

        # Superseded task: surface the cancellation as-is, never run
        # verification or regenerate a response that claims it worked.
        if response.task_result == TaskResult.CANCELLED:
            self._log_final_result(text, response)
            return response

        # Executor asked the user to confirm before completing: route the
        # answer through the confirmation flow (re-process with confirmed=True).
        if response.task_result == TaskResult.USER_CONFIRMATION:
            self._pending_parsed = parsed
            self._pending_recognized = recognized
            self._original_text = text
            self._pending_confirmation = True
            question = response.clarification_question or response.message
            logger.info("Executor USER_CONFIRMATION: %s", question)
            return ModelResponse(
                success=False,
                message=question,
                data={"raw_text": text, "intent": recognized.intent},
                needs_clarification=True,
                clarification_question=question,
                task_result=TaskResult.USER_CONFIRMATION,
                confidence=confidence,
            )

        # Still in progress: don't run verification, keep the pending status.
        if response.task_result in (TaskResult.WAITING, TaskResult.RETRYING):
            self._log_final_result(text, response)
            return response

        # Generic clarification requested mid-plan: surface it as-is.
        if response.needs_clarification:
            self._pending_parsed = parsed
            self._pending_recognized = recognized
            self._original_text = text
            return response

        # -- 9. Verify against the plan's verification spec --
        verify_start = stage_entry("pipeline.verify")
        verification, ver_diag = self._try_verify(response, recognized, plan)
        stage_exit("pipeline.verify", verify_start, status="PASS" if verification.passed else "FAIL", output=verification.message)

        # Task verifier asked the user something (not a strategy retry).
        if not verification.passed and verification.retry_response is not None:
            self._log_verification_outcome(verification)
            retry = verification.retry_response
            if getattr(retry, "needs_clarification", False):
                self._pending_parsed = parsed
                self._pending_recognized = recognized
                self._original_text = text
            return self._patch_result(retry, TaskResult.CLARIFICATION)

        failed = not response.success or not verification.passed

        # Auto-retry ONCE with the first alternative strategy.
        if failed and not retried and reasoned is not None and reasoned.alternatives:
            self._log_verification_outcome(verification) if not verification.passed else None
            alt_response = self._maybe_retry(parsed, text, confirmed, cancel_event, reasoned)
            if alt_response is not None:
                return alt_response

        # Give up: explain honestly and ask the user how to proceed.
        if failed:
            self._log_verification_outcome(verification) if not verification.passed else None
            logger.warning("IntelligentPlanner: FAILURE for intent=%s retried=%s", recognized.intent, retried)
            data = {"raw_text": text, "intent": recognized.intent}
            if not verification.passed:
                data["verification_passed"] = False
            if retried:
                data["retry_attempted"] = True
            return ModelResponse(
                success=False,
                message=self._explain_failure(text, response, verification, reasoned, retried),
                data=data,
                error=response.error,
                task_result=TaskResult.FAILED,
                confidence=confidence,
            )

        final_response = verification.details.get("verified_response", response)
        final_reasoning = (
            reasoned.reasoning if reasoned is not None and reasoned.reasoning else decision.reasoning
        )

        # -- 10. Generate final response --
        # Hedge honestly when EITHER the intent or the speech recognition
        # was uncertain — the brain now knows the ASR confidence.
        gen_confidence = confidence
        if self._speech_confidence is not None:
            gen_confidence = (
                min(confidence, self._speech_confidence)
                if confidence is not None
                else self._speech_confidence
            )
        gen_start = stage_entry("pipeline.generate", input_=recognized.intent)
        result = self._response_generator.generate(
            executor_response=final_response,
            intent=recognized.intent,
            raw_text=text,
            pipeline_reasoning=decision.reasoning,
            confidence=gen_confidence,
        )
        stage_exit("pipeline.generate", gen_start, status="OK" if result.success else "FAIL", output=result.message)

        if not result.success:
            reply = self._patch_confidence(
                self._patch_result(result, TaskResult.FAILED, ver_diag or diag),
                confidence, final_reasoning,
            )
        else:
            reply = self._patch_confidence(
                ModelResponse(
                    success=result.success,
                    message=result.message,
                    data=result.data,
                    error=result.error,
                    task_result=TaskResult.SUCCESS,
                ),
                confidence, final_reasoning,
            )

        self._remember_action(text, reply.message)
        self._log_action_outcome(text, category_label, plan, reply)
        self._log_final_result(text, reply)
        reasoning_confidence = (
            reasoned.confidence
            if reasoned is not None and reasoned.confidence is not None
            else None
        )
        self._log_request_summary(
            text,
            recognized.intent,
            plan,
            execution=(f"success={response.success} status={response.task_result.value}"),
            verification=(f"passed={verification.passed} {verification.message or ''}".strip()),
            final=reply.message,
            intent_confidence=confidence,
            reasoning_confidence=reasoning_confidence,
        )

        return reply

    def _maybe_retry(
        self,
        parsed: ParsedCommand,
        text: str,
        confirmed: bool,
        cancel_event: Any,
        reasoned: ReasonedPlan,
    ) -> ModelResponse | None:
        """Auto-retry with the first alternative strategy.  Returns the
        alternative's full pipeline response, or ``None`` when there is
        nothing sensible to retry."""
        alternative = reasoned.alternatives[0]
        alt_parsed = self._parsed_from_reasoned(text, alternative)
        if alt_parsed is None:
            return None
        logger.info(
            "Auto-retry with alternative strategy: intent=%s — %s",
            alternative.intent, alternative.description,
        )
        return self._run_stages(
            alt_parsed, text, confirmed=confirmed, cancel_event=cancel_event,
            reasoned=reasoned, retried=True,
        )

    @staticmethod
    def _explain_failure(
        text: str,
        response: ModelResponse,
        verification: VerificationResult,
        reasoned: ReasonedPlan | None,
        retried: bool,
    ) -> str:
        """Explain why a request failed and ask the user how to proceed."""
        if not verification.passed:
            base = (
                f"The action ran, but I couldn't verify the result "
                f"({verification.message or 'verification failed'})."
            )
        else:
            base = response.message or "That didn't work."

        remaining = []
        if reasoned is not None:
            start = 1 if retried else 0
            remaining = reasoned.alternatives[start:]

        if retried:
            if remaining:
                names = ", ".join(f"'{a.description or a.intent}'" for a in remaining)
                return (
                    f"{base} I tried an alternative approach and it failed too. "
                    f"I could still try: {names}. Which should I try?"
                )
            return (
                f"{base} I tried an alternative approach and it failed too. "
                "What would you like me to do next?"
            )
        if remaining:
            names = ", ".join(f"'{a.description or a.intent}'" for a in remaining)
            return f"{base} Would you like me to try a different approach ({names})?"
        return f"{base} What would you like me to do next?"

    @staticmethod
    def _patch_confidence(
        r: ModelResponse,
        confidence: float | None,
        reasoning: str,
    ) -> ModelResponse:
        return ModelResponse(
            success=r.success, message=r.message, data=r.data, error=r.error,
            needs_clarification=r.needs_clarification,
            clarification_question=r.clarification_question,
            alternatives=r.alternatives,
            task_result=r.task_result, diagnostic=r.diagnostic,
            confidence=confidence if confidence is not None else r.confidence,
            speech_confidence=r.speech_confidence,
            reasoning=reasoning or r.reasoning,
        )

    def _with_speech_confidence(self, r: ModelResponse | None) -> ModelResponse | None:
        """Attach the incoming ASR confidence to the final response."""
        if r is None or self._speech_confidence is None:
            return r
        if r.speech_confidence is not None:
            return r
        return ModelResponse(
            success=r.success, message=r.message, data=r.data, error=r.error,
            needs_clarification=r.needs_clarification,
            clarification_question=r.clarification_question,
            alternatives=r.alternatives,
            task_result=r.task_result, diagnostic=r.diagnostic,
            confidence=r.confidence, reasoning=r.reasoning,
            speech_confidence=self._speech_confidence,
        )

    @timed("pipeline.resolve_context")
    @log_duration()
    def resolve_context(self, answer: str, cancel_event: Any = None) -> ModelResponse:
        # -- Pending reasoner (LLM) clarification: re-reason with the answer --
        if self._pending_reasoned is not None:
            return self._continue_reasoning(answer, cancel_event)

        if self._pending_parsed is None:
            return ModelResponse(success=False, message="No pending clarification.", task_result=TaskResult.FAILED)

        # -- Pending context-switch question: interpret the user's yes/no --
        if self._pending_switch_parsed is not None:
            return self._resolve_context_switch(answer)

        parsed = self._pending_parsed
        recognized = self._pending_recognized
        text = self._original_text

        # -- Context switch: the user issued a brand-new task while we wait --
        switch = self._detect_context_switch(answer)
        if switch is not None:
            return self._ask_context_switch(switch, text)

        # -- Handle a planner UserChoice (world-state question) --
        if self._pending_choice is not None:
            choice = self._pending_choice
            self._pending_choice = None
            self._pending_parsed = None
            self._pending_recognized = None
            self._original_text = ""

            choice_plan = self._intelligent_planner.build_choice_plan(
                choice, answer, parsed,
            )
            if choice_plan is None:
                return ModelResponse(
                    success=False,
                    message=f"I didn't catch that. {choice.question} "
                            f"({', '.join(choice.options)}).",
                    needs_clarification=True,
                    clarification_question=choice.question,
                    task_result=TaskResult.USER_CONFIRMATION,
                )

            logger.info("IntelligentPlanner choice '%s' resolved: intent=%s",
                         choice.kind, choice_plan.intent)
            refined = self._intelligent_planner.refine(
                choice_plan, parsed, world_state=self._world_state.current()
                if self._world_state is not None else None,
            )
            self._task_supervisor.start_supervision(refined.plan.intent, len(refined.plan.steps))
            response, diag = self._try_execute(refined.plan, recognized, cancel_event=cancel_event)
            self._task_supervisor.end_supervision()
            verification, ver_diag = self._try_verify(response, recognized, refined.plan)
            if not verification.passed:
                self._log_verification_outcome(verification)
                return ModelResponse(
                    success=False,
                    message=f"I couldn't verify the result ({verification.message or 'verification failed'}).",
                    data={"raw_text": text, "verification_passed": False},
                    task_result=TaskResult.FAILED,
                )
            final_response = verification.details.get("verified_response", response)
            result = self._response_generator.generate(
                executor_response=final_response,
                intent=refined.plan.intent,
                raw_text=text,
            )
            reply = ModelResponse(
                success=result.success,
                message=result.message,
                data=result.data,
                error=result.error,
                task_result=TaskResult.SUCCESS if result.success else TaskResult.FAILED,
            )
            self._log_final_result(text, reply)
            self._log_request_summary(
                text,
                refined.plan.intent,
                refined.plan,
                execution=(f"success={response.success} status={response.task_result.value}"),
                verification=(f"passed={verification.passed} {verification.message or ''}".strip()),
                final=reply.message,
                intent_confidence=parsed.confidence,
            )
            return reply

        # -- Handle confirmation yes/no --
        if self._pending_confirmation:
            self._pending_confirmation = False
            verdict = self._confirmation.classify_answer(answer)

            if verdict == "affirmative":
                # Re-process with confirmed=True
                self._pending_parsed = None
                self._pending_recognized = None
                self._original_text = ""
                logger.info("Confirmation ACCEPTED — re-processing '%s' with confirmed=True", text)
                return self.process(text, confirmed=True)

            if verdict == "negative":
                self._pending_parsed = None
                self._pending_recognized = None
                self._original_text = ""
                logger.info("Confirmation REJECTED — cancelling '%s'", text)
                return ModelResponse(
                    success=True,
                    message="Cancelled.",
                    data={"raw_text": text, "intent": recognized.intent if recognized else ""},
                    task_result=TaskResult.CANCELLED,
                )

            # Unknown → re-ask
            logger.info("Confirmation answer unclear: %r — re-asking", answer)
            self._pending_parsed = parsed
            self._pending_recognized = recognized
            self._original_text = text
            self._pending_confirmation = True
            question = self._confirmation.build_question(recognized.intent, recognized.entities) if recognized else "Are you sure?"
            return ModelResponse(
                success=False,
                message=question,
                data={"raw_text": text, "intent": recognized.intent if recognized else ""},
                needs_clarification=True,
                clarification_question=question,
                task_result=TaskResult.CLARIFICATION,
            )

        self._pending_parsed = None
        self._pending_recognized = None
        self._original_text = ""

        try:
            decision = self._decision_engine.decide_follow_up(
                answer=answer,
                recognized=recognized,
                context_manager=self._context_manager,
                task_supervisor=self._task_supervisor,
            )
        except Exception as exc:
            diag = DiagnosticReport(component="DecisionEngine", exception=f"{type(exc).__name__}: {exc}",
                                    attempted_action=f"decide_follow_up({answer})")
            logger.error("Follow-up DecisionEngine exception: %s", exc, exc_info=True)
            return ModelResponse(success=False, message="Follow-up decision failed.", error=str(exc),
                                 task_result=TaskResult.INTERNAL_ERROR, diagnostic=diag)

        logger.info("Follow-up decision: type=%s reasoning=%s", decision.type.name, decision.reasoning)

        if decision.type == DecisionType.ASK_CLARIFICATION:
            self._pending_parsed = parsed
            self._pending_recognized = recognized
            self._original_text = text
            return self._patch_result(decision.response, TaskResult.CLARIFICATION)

        if decision.type == DecisionType.ABORT:
            return self._patch_result(decision.response, TaskResult.UNSUPPORTED)

        resolved_response = decision.response
        action = resolved_response.data.get("action", "unknown") if resolved_response else "unknown"
        context_data = resolved_response.data.get("context", {}) if resolved_response else {}

        if action == "none" or not resolved_response.data.get("intent"):
            return resolved_response

        if action == "select_browser":
            return resolved_response

        plan = self._build_resolved_plan(action, context_data, parsed, recognized, text)
        if plan is None:
            return ModelResponse(success=False, message="Could not build execution plan from resolved context.",
                                 task_result=TaskResult.FAILED)

        # Route resolved plans through the Intelligent Planner so state
        # rewrites (Ctrl+N instead of a second process) and verification
        # specs apply uniformly.
        refined = self._intelligent_planner.refine(
            plan, parsed,
            world_state=self._world_state.current()
            if self._world_state is not None else None,
        )
        plan = refined.plan
        verification_checks = refined.verification

        self._task_supervisor.start_supervision(plan.intent, len(plan.steps))

        response, diag = self._try_execute(plan, recognized, cancel_event=cancel_event)
        self._task_supervisor.end_supervision()

        verification, ver_diag = self._try_verify(response, recognized, plan)
        if not verification.passed:
            self._log_verification_outcome(verification)
            return ModelResponse(
                success=False,
                message=f"I couldn't verify the result ({verification.message or 'verification failed'}).",
                data={"raw_text": text, "verification_passed": False},
                task_result=TaskResult.FAILED,
            )
        final_response = verification.details.get("verified_response", response)

        result = self._response_generator.generate(
            executor_response=final_response,
            intent=plan.intent,
            raw_text=text,
        )

        if not result.success:
            return self._patch_result(result, TaskResult.FAILED, diag or ver_diag)
        reply = ModelResponse(success=result.success, message=result.message, data=result.data,
                              task_result=TaskResult.SUCCESS)
        self._log_final_result(text, reply)
        self._log_request_summary(
            text,
            plan.intent,
            plan,
            execution=(f"success={response.success} status={response.task_result.value}"),
            verification=(f"passed={verification.passed} {verification.message or ''}".strip()),
            final=reply.message,
            intent_confidence=parsed.confidence,
        )
        return reply

    def _parse(self, text: str) -> ParsedCommand | None:
        try:
            from brain.parser import Parser
            return self._parser.parse(text)
        except Exception as exc:
            print(f"[PIPELINE] Parser EXCEPTION: {type(exc).__name__}: {exc}")
            return None

    # ------------------------------------------------------------------
    # Context switching (milestone Task 3)
    # ------------------------------------------------------------------

    def _detect_context_switch(self, answer: str) -> ParsedCommand | None:
        """Detect whether the follow-up answer is actually a brand-new task
        rather than an answer to the pending clarification.

        Returns the parsed new command when a context switch is warranted,
        otherwise ``None`` (let the normal clarification flow proceed).
        """
        # A legitimate expected answer to a pending context-manager
        # clarification (e.g. "existing", "new window", "switch to it")
        # always wins over context-switch detection.
        if self._context_manager is not None and self._context_manager.clarification.has_pending:
            if self._context_manager.clarification.matches_expected(answer):
                return None

        new_parsed = self._parse(answer)
        if new_parsed is None:
            return None
        if new_parsed.intent in _NON_ACTIONABLE_INTENTS:
            return None

        # Must differ from the pending request to count as a switch.
        pending_parsed = self._pending_parsed
        if pending_parsed is not None and self._same_request(pending_parsed, new_parsed):
            return None
        return new_parsed

    @staticmethod
    def _same_request(a: ParsedCommand, b: ParsedCommand) -> bool:
        """True when two commands target the same primary entity."""
        if a.intent != b.intent:
            return False
        key = _PRIMARY_ENTITY.get(a.intent)
        if key is None:
            return True
        a_val = str(a.entities.get(key, "")).strip().casefold()
        b_val = str(b.entities.get(key, "")).strip().casefold()
        if not a_val or not b_val:
            return False
        return a_val == b_val

    def _ask_context_switch(self, new_parsed: ParsedCommand, original_text: str) -> ModelResponse:
        """Ask the user whether to cancel the original request in favour of the
        brand-new task they just uttered."""
        self._pending_switch_parsed = new_parsed
        self._pending_switch_text = new_parsed.raw_text or ""
        self._pending_switch_original_question = self._current_pending_question()
        question = (
            f"Would you like to cancel the {original_text or 'previous request'} "
            f"request and {self._pending_switch_text} instead?"
        )
        self._pending_switch_question = question
        logger.info("Context switch proposed: cancel %r → do %r", original_text, self._pending_switch_text)
        return ModelResponse(
            success=False,
            message=question,
            data={"raw_text": original_text, "intent": new_parsed.intent},
            needs_clarification=True,
            clarification_question=question,
            task_result=TaskResult.CLARIFICATION,
        )

    def _resolve_context_switch(self, answer: str) -> ModelResponse:
        """Interpret the user's reply to a context-switch question (yes/no)."""
        verdict = self._confirmation.classify_answer(answer)
        new_parsed = self._pending_switch_parsed
        original_text = self._original_text

        if verdict == "affirmative":
            # Cancel the original request and run the new task instead.
            new_text = self._pending_switch_text
            self._pending_switch_parsed = None
            self._pending_switch_text = ""
            self._pending_switch_question = ""
            self._pending_switch_original_question = ""
            self._pending_parsed = None
            self._pending_recognized = None
            self._original_text = ""
            self._pending_confirmation = False
            self._pending_choice = None
            if self._context_manager is not None:
                self._context_manager.clarification.clear_pending()
            logger.info("Context switch ACCEPTED — re-processing '%s'", new_text)
            return self.process(new_text)

        if verdict == "negative":
            # Keep the original request; re-ask its pending question.
            self._pending_switch_parsed = None
            self._pending_switch_text = ""
            self._pending_switch_question = ""
            question = self._pending_switch_original_question
            self._pending_switch_original_question = ""
            logger.info("Context switch DECLINED — resuming '%s'", original_text)
            return ModelResponse(
                success=False,
                message=question,
                data={"raw_text": original_text},
                needs_clarification=True,
                clarification_question=question,
                task_result=TaskResult.CLARIFICATION,
            )

        # Unclear → re-ask the switch question.
        return ModelResponse(
            success=False,
            message=self._pending_switch_question,
            data={"raw_text": original_text},
            needs_clarification=True,
            clarification_question=self._pending_switch_question,
            task_result=TaskResult.CLARIFICATION,
        )

    def _current_pending_question(self) -> str:
        """Reconstruct the currently pending question for re-asking."""
        if self._context_manager is not None and self._context_manager.clarification.has_pending:
            return self._context_manager.get_pending_question()
        if self._pending_confirmation and self._pending_recognized is not None:
            return self._confirmation.build_question(
                self._pending_recognized.intent, self._pending_recognized.entities,
            )
        if self._pending_choice is not None:
            return self._pending_choice.question
        return "Is there anything else you'd like me to do?"

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
            return self._skill_unknown_response(parsed)

        # Low-confidence gate: use the preserved ASR confidence when the
        # utterance was spoken; otherwise fall back to the parser's own
        # confidence (which defaults to 1.0, so the gate is a no-op for
        # typed input unless the parser is genuinely unsure).
        confidence_for_gate = (
            self._speech_confidence
            if self._speech_confidence is not None
            else parsed.confidence
        )
        if confidence_for_gate < 1.0:
            from safety.policy import SafetyPolicy
            policy = SafetyPolicy()
            confidence_check = policy.check_speech_confidence(confidence_for_gate)
            if not confidence_check["accepted"]:
                print(f"[PIPELINE] Speech confidence REJECTED: {confidence_for_gate:.3f}")
                return ModelResponse(
                    success=False,
                    message="I'm sorry, sir. I didn't catch that.",
                    data={"raw_text": parsed.raw_text, "confidence": confidence_for_gate},
                    speech_confidence=self._speech_confidence,
                )

        return None

    # ------------------------------------------------------------------
    # Classification gate helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _log_classification(text: str, classification: ClassificationResult) -> None:
        """Emit the structured classification log block."""
        if classification.category in NON_ACTION_CATEGORIES:
            llm_text = classification.response or "-"
            executor_text = "Skipped"
        else:
            llm_text = "-"
            executor_text = "Pending"
        logger.info(
            "\n---- USER ------------\n%s\n"
            "---- CLASSIFICATION --\n%s\n"
            "---- LLM -------------\n%s\n"
            "---- EXECUTOR --------\n%s",
            text.strip(), classification.category.value, llm_text, executor_text,
        )

    @staticmethod
    def _log_action_outcome(text: str, category: str, plan: Any, response: ModelResponse) -> None:
        """Emit the structured action log block with plan + executor result."""
        steps = "\n".join(
            f"  {i}. {s.action} {s.target or ''}".strip()
            for i, s in enumerate(getattr(plan, "steps", []))
        ) or "  (no steps)"
        status = "SUCCESS" if response.success else f"FAILED ({response.task_result.value})"
        logger.info(
            "\n---- USER ------------\n%s\n"
            "---- CLASSIFICATION --\n%s\n"
            "---- PLAN ------------\n%s\n"
            "---- EXECUTOR --------\n%s",
            text.strip(), category, steps, status,
        )

    @staticmethod
    def _log_verification_outcome(verification: Any) -> None:
        logger.info(
            "\n---- VERIFICATION ----\npassed=%s\n%s",
            verification.passed, verification.message or "-",
        )

    @staticmethod
    def _log_final_result(text: str, reply: ModelResponse) -> None:
        logger.info(
            "\n---- FINAL RESULT ----\nsuccess=%s status=%s\n%s",
            reply.success, reply.task_result.value,
            reply.message or "-",
        )

    def _log_request_summary(
        self,
        user: str,
        intent: str,
        plan: Any,
        execution: str,
        verification: str,
        final: str,
        intent_confidence: float | None = None,
        reasoning_confidence: float | None = None,
    ) -> None:
        """Emit one consolidated, audit-friendly line per request.

        Includes the preserved speech confidence, the intent/reasoning
        confidence, the execution + verification outcomes and the total
        wall-clock time for the request.
        """
        steps = "\n".join(
            f"  {i}. {s.action} {s.target or ''}".strip()
            for i, s in enumerate(getattr(plan, "steps", []))
        ) or "  (no steps)"
        speech_conf = (
            f"{self._speech_confidence:.3f}"
            if self._speech_confidence is not None
            else "-"
        )
        intent_conf = (
            f"{intent_confidence:.3f}"
            if intent_confidence is not None
            else "-"
        )
        reasoning_conf = (
            f"{reasoning_confidence:.3f}"
            if reasoning_confidence is not None
            else "-"
        )
        total_ms = (
            (time.monotonic() - self._request_started_at) * 1000.0
            if self._request_started_at
            else -1.0
        )
        logger.info(
            "\n---- REQUEST ---------\n"
            "User: %s\n"
            "Intent: %s\n"
            "Speech Confidence: %s\n"
            "Intent Confidence: %s\n"
            "Reasoning Confidence: %s\n"
            "Plan:\n%s\n"
            "Execution: %s\n"
            "Verification: %s\n"
            "Final response: %s\n"
            "Total time: %.1f ms",
            user.strip(), intent, speech_conf, intent_conf, reasoning_conf,
            steps, execution, verification, final, total_ms,
        )

    def _chat_response(self, text: str, classification: ClassificationResult) -> ModelResponse:
        """Return the LLM response directly without invoking the executor."""
        reply = classification.response or "I'm here. How can I help you?"
        return ModelResponse(
            success=True,
            message=reply,
            data={
                "raw_text": text,
                "category": classification.category.value,
                "classification_source": classification.source,
            },
            task_result=TaskResult.SUCCESS,
        )

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

        if action == "open_new_profile":
            app_name = context.get("app_name") or context.get("display_name") or parsed.entities.get("app_name", "")
            return self._build_simple_plan(text, "open_app", {
                "app_name": app_name, "focus_if_running": False, "profile": True,
            }, parsed.confidence)

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

    # ------------------------------------------------------------------
    # Diagnostic helpers
    # ------------------------------------------------------------------

    def _try_parse(self, text: str) -> tuple[Any, DiagnosticReport | None]:
        try:
            return self._parser.parse(text), None
        except Exception as exc:
            diag = DiagnosticReport(component="Parser", exception=f"{type(exc).__name__}: {exc}",
                                    attempted_action=f"parse({text!r})")
            logger.error("Parser exception: %s", exc, exc_info=True)
            return None, diag

    def _try_recognize(self, parsed: Any) -> tuple[Any, DiagnosticReport | None]:
        try:
            return self._intent_recognizer.recognize(parsed), None
        except Exception as exc:
            diag = DiagnosticReport(component="IntentRecognizer", exception=f"{type(exc).__name__}: {exc}",
                                    attempted_action=f"recognize({parsed.intent})")
            logger.error("IntentRecognizer exception: %s", exc, exc_info=True)
            return None, diag

    def _try_capture_context(self, recognized: Any) -> tuple[Any, DiagnosticReport | None]:
        try:
            return self._capture_context(recognized), None
        except Exception as exc:
            diag = DiagnosticReport(component="ContextCapture", exception=f"{type(exc).__name__}: {exc}",
                                    attempted_action=f"capture_context({recognized.intent})")
            logger.error("Context capture exception: %s", exc, exc_info=True)
            return None, diag

    def _try_decide(self, recognized: Any, snapshot: Any) -> tuple[Any, DiagnosticReport | None]:
        try:
            decision = self._decision_engine.decide(
                recognized=recognized,
                snapshot=snapshot,
                context_manager=self._context_manager,
                clarification=getattr(self._context_manager, "clarification", None) if self._context_manager else None,
            )
            return decision, None
        except Exception as exc:
            diag = DiagnosticReport(component="DecisionEngine", exception=f"{type(exc).__name__}: {exc}",
                                    attempted_action=f"decide({recognized.intent})")
            logger.error("DecisionEngine exception: %s", exc, exc_info=True)
            return None, diag

    def _try_intelligent_plan(self, parsed: Any, recognized: Any, decision: Any, confirmed: bool) -> tuple[Any, DiagnosticReport | None]:
        """Plan via the Intelligent Planner, which consults world state
        and attaches a verification spec to every plan."""
        try:
            world_state = None
            if self._world_state is not None:
                try:
                    world_state = self._world_state.current()
                except Exception as exc:
                    logger.warning("World state capture failed: %s", exc)
            result = self._intelligent_planner.create_plan(
                parsed, confirmed=confirmed, world_state=world_state,
            )
            return result, None
        except Exception as exc:
            diag = DiagnosticReport(component="IntelligentPlanner", exception=f"{type(exc).__name__}: {exc}",
                                    attempted_action=f"create_plan({parsed.intent})")
            logger.error("IntelligentPlanner exception: %s", exc, exc_info=True)
            return None, diag

    def _try_build_plan(self, parsed: Any, recognized: Any, decision: Any, confirmed: bool) -> tuple[Any, DiagnosticReport | None]:
        try:
            return self._build_plan(parsed, recognized, decision, confirmed), None
        except Exception as exc:
            diag = DiagnosticReport(component="Planner", exception=f"{type(exc).__name__}: {exc}",
                                    attempted_action=f"build_plan({parsed.intent})")
            logger.error("Planner exception: %s", exc, exc_info=True)
            return None, diag

    def _try_execute(
        self,
        plan: Any,
        recognized: Any,
        cancel_event: Any = None,
    ) -> tuple[Any, DiagnosticReport | None]:
        try:
            response = self._executor.execute(plan, cancel_event=cancel_event)
            logger.info("Executor -> success=%s message=%s", response.success, response.message)
            status = getattr(response, "task_result", None)
            if status is None or status == TaskResult.SUCCESS:
                status = TaskResult.SUCCESS if response.success else TaskResult.FAILED
            data = dict(response.data)
            data["_execution"] = {
                "duration_ms": getattr(response, "duration_ms", None),
                "retry_count": getattr(response, "retry_count", 0),
                "verification": getattr(response, "verification", None),
            }
            mapped = ModelResponse(
                success=response.success,
                message=response.message,
                data=data,
                error=getattr(response, "error", None),
                needs_clarification=getattr(response, "needs_clarification", False),
                clarification_question=getattr(response, "clarification_question", ""),
                task_result=status,
                speech_confidence=self._speech_confidence,
            )
            return mapped, None
        except Exception as exc:
            diag = DiagnosticReport(component="Executor", exception=f"{type(exc).__name__}: {exc}",
                                    attempted_action=f"execute({plan.intent})")
            logger.error("Executor exception: %s", exc, exc_info=True)
            return ModelResponse(success=False, message="Executor failed while running the execution plan.",
                                 data={"raw_text": plan.raw_text, "intent": plan.intent},
                                 error=f"{type(exc).__name__}: {exc}",
                                 task_result=TaskResult.INTERNAL_ERROR), diag

    def _try_verify(self, response: Any, recognized: Any, plan: Any = None) -> tuple[Any, DiagnosticReport | None]:
        try:
            # The action already failed — do not run (or report) world-state
            # verification: the failure message must reach the user as-is
            # instead of being masked by a "couldn't verify" response.
            if not getattr(response, "success", False):
                return VerificationResult(
                    passed=True,
                    message="skipped — execution already failed",
                    details={"verified_response": response},
                ), None

            checks = self._plan_verification_checks(plan)
            if checks:
                passed, message = self._run_verification_checks(checks)
                logger.info("IntelligentPlanner VERIFICATION: passed=%s %s", passed, message)
                details = {"verified_response": response}
                if passed:
                    details["verification_passed"] = True
                return VerificationResult(
                    passed=passed,
                    message=message,
                    details=details,
                    needs_retry=not passed,
                    retry_response=None,
                ), None

            if not recognized.requires_verification:
                return VerificationResult(passed=True, message="Verification skipped for this intent."), None
            result = self._verification_engine.verify_execution(response, recognized.intent, recognized.entities)
            return result, None
        except Exception as exc:
            diag = DiagnosticReport(component="Verification", exception=f"{type(exc).__name__}: {exc}",
                                    attempted_action=f"verify({recognized.intent})")
            logger.error("Verification exception: %s", exc, exc_info=True)
            return VerificationResult(passed=False, message="Verification threw an exception."), diag

    @staticmethod
    def _plan_verification_checks(plan: Any) -> list[VerificationCheck]:
        """Extract the Intelligent Planner's verification spec from a plan."""
        if plan is None:
            return []
        metadata = getattr(plan, "metadata", None) or {}
        raw = metadata.get("verification") or []
        checks: list[VerificationCheck] = []
        for item in raw:
            if isinstance(item, VerificationCheck):
                checks.append(item)
            elif isinstance(item, dict):
                checks.append(VerificationCheck(**item))
        # A pure "none" spec is not a real verification — treat as absent
        # so the legacy requires_verification path still runs.
        if checks and all(c.kind == "none" for c in checks):
            return []
        return checks

    def _run_verification_checks(self, checks: list[VerificationCheck]) -> tuple[bool, str]:
        """Verify each check against the live world state.

        The world model is background-polled, so a check is retried until
        its ``timeout`` so it can observe the state after execution.
        """
        if self._world_state is None:
            return False, "world state unavailable — cannot verify"

        for check in checks:
            kind = check.kind
            if kind == "none":
                continue
            deadline = time.monotonic() + max(0.5, check.timeout)
            last_message = "no result yet"
            while True:
                try:
                    ws = self._world_state.current()
                except Exception as exc:
                    logger.warning("World state unavailable during verification: %s", exc)
                    ws = None
                if ws is None:
                    return False, "world state unavailable — cannot verify"
                passed, message = self._check_world(kind, check, ws)
                if passed or time.monotonic() >= deadline:
                    if not passed:
                        logger.info(
                            "IntelligentPlanner verification '%s' failed after %.0fs: %s",
                            kind, check.timeout, message,
                        )
                    return passed, message
                last_message = message
                time.sleep(0.4)
        return True, "all verification checks passed"

    @staticmethod
    def _check_world(kind: str, check: VerificationCheck, ws: Any) -> tuple[bool, str]:
        target = check.target
        if kind == "app_running":
            ok = ws.app_running(target)
            return ok, f"application '{target}' running" if ok else f"application '{target}' not running"
        if kind == "app_closed":
            ok = not ws.app_running(target)
            return ok, f"application '{target}' closed" if ok else f"application '{target}' still running"
        if kind == "url_loaded":
            urls = [b.active_url for b in ws.browsers.values() if b.active_url]
            ok = any(target and target.casefold() in (u or "").casefold() for u in urls)
            return ok, f"url '{target}' loaded" if ok else f"url '{target}' not found in active tabs"
        if kind == "tab_open":
            for b in ws.browsers.values():
                for win in b.windows:
                    for field in (win.active_tab_url, win.active_tab_title):
                        if target and target.casefold() in (field or "").casefold():
                            return True, f"tab matching '{target}' found"
            return False, f"no tab matching '{target}'"
        if kind == "media_playing":
            ok = bool(ws.video_playing)
            return ok, "media is playing" if ok else "no media playing detected"
        return True, f"unknown check '{kind}' skipped"

    @staticmethod
    def _fail(result: TaskResult, message: str, error: str, diag: DiagnosticReport | None, raw_text: str) -> ModelResponse:
        return ModelResponse(success=False, message=message, data={"raw_text": raw_text},
                            error=error, task_result=result, diagnostic=diag)

    @staticmethod
    def _patch_result(r: ModelResponse, task_result: TaskResult, diag: DiagnosticReport | None = None) -> ModelResponse:
        return ModelResponse(success=r.success, message=r.message, data=r.data, error=r.error,
                             needs_clarification=r.needs_clarification,
                             clarification_question=r.clarification_question,
                             alternatives=r.alternatives,
                             task_result=task_result, diagnostic=diag or r.diagnostic,
                             confidence=r.confidence, reasoning=r.reasoning)

