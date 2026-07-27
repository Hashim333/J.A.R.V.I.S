from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from models.response import Response

if TYPE_CHECKING:
    from thinking.context_snapshot import ContextSnapshot
    from thinking.intent_recognizer import RecognizedIntent
    from context_manager.context_manager import ContextManager
    from context_manager.clarification_engine import ClarificationEngine
    from thinking.task_supervisor import TaskSupervisor


class DecisionType(Enum):
    PROCEED = auto()
    ASK_CLARIFICATION = auto()
    ABORT = auto()


@dataclass(frozen=True)
class Decision:
    type: DecisionType
    reasoning: str = ""
    response: Response | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DecisionEngine:
    def __init__(self) -> None:
        self._decision_history: list[dict[str, Any]] = []

    def decide(
        self,
        recognized: RecognizedIntent,
        snapshot: ContextSnapshot,
        context_manager: ContextManager | None,
        clarification: ClarificationEngine | None,
    ) -> Decision:
        intent = recognized.intent
        entities = recognized.entities
        raw_text = recognized.raw_text

        if intent == "open_website":
            protected_decision = self._check_protected(recognized, snapshot)
            if protected_decision:
                return protected_decision

        if recognized.requires_context and context_manager is not None:
            context_response = context_manager.check_before_execution(intent, entities, raw_text)
            if context_response is not None and getattr(context_response, "needs_clarification", False):
                self._decision_history.append({
                    "type": "clarification",
                    "reason": context_response.clarification_question,
                    "intent": intent,
                })
                return Decision(
                    type=DecisionType.ASK_CLARIFICATION,
                    reasoning=f"Context manager requested clarification: {context_response.clarification_question}",
                    response=context_response,
                    metadata={"clarification_type": "context"},
                )

        if recognized.is_destructive:
            self._decision_history.append({
                "type": "proceed_with_caution",
                "reason": f"Destructive intent '{intent}'",
                "intent": intent,
            })
            return Decision(
                type=DecisionType.PROCEED,
                reasoning=f"Proceeding with destructive intent '{intent}' — requires confirmation in plan.",
                metadata={"requires_confirmation": True, "confirmation_reason": f"Action '{intent}' may be destructive."},
            )

        self._decision_history.append({
            "type": "proceed",
            "reason": f"No clarification needed for '{intent}'",
            "intent": intent,
        })
        return Decision(
            type=DecisionType.PROCEED,
            reasoning=f"Proceeding with intent '{intent}' — no context issues detected.",
            metadata={"requires_confirmation": False},
        )

    def decide_follow_up(
        self,
        answer: str,
        recognized: RecognizedIntent,
        context_manager: ContextManager | None,
        task_supervisor: TaskSupervisor | None,
    ) -> Decision:
        resolved: Response | None = None

        if task_supervisor is not None and task_supervisor.has_pending:
            resolved = task_supervisor.resolve(answer)
        elif context_manager is not None:
            resolved = context_manager.handle_follow_up(answer)

        if resolved is None:
            return Decision(
                type=DecisionType.ASK_CLARIFICATION,
                reasoning="No handler could resolve the answer.",
                response=Response(success=False, message="I didn't understand that. Could you rephrase?"),
                metadata={"clarification_type": "reask"},
            )

        if not resolved.success:
            needs_clar = getattr(resolved, "needs_clarification", False)
            if needs_clar:
                return Decision(
                    type=DecisionType.ASK_CLARIFICATION,
                    reasoning=f"Follow-up needs more clarification: {resolved.clarification_question}",
                    response=resolved,
                    metadata={"clarification_type": "follow_up"},
                )
            return Decision(
                type=DecisionType.ABORT,
                reasoning=f"Follow-up resolution failed: {resolved.message}",
                response=resolved,
                metadata={},
            )

        return Decision(
            type=DecisionType.PROCEED,
            reasoning="Follow-up resolved successfully.",
            response=resolved,
            metadata={"requires_confirmation": False},
        )

    @staticmethod
    def _check_protected(recognized: RecognizedIntent, snapshot: ContextSnapshot) -> Decision | None:
        website = recognized.entities.get("website", "")
        if not website:
            return None
        site_lower = website.casefold()
        protected_sites = {"chatgpt", "gmail", "mail.google", "docs.google", "github", "bank"}
        if any(p in site_lower for p in protected_sites):
            return Decision(
                type=DecisionType.PROCEED,
                reasoning=f"Protected site '{website}' requested — will handle safely.",
                metadata={"is_protected_site": True, "requires_confirmation": False},
            )
        if snapshot.protected_tabs:
            return Decision(
                type=DecisionType.PROCEED,
                reasoning="Protected tabs detected — will open in new tab to avoid disturbance.",
                metadata={"protected_tabs_present": True, "open_in_new_tab": True},
            )
        return None
