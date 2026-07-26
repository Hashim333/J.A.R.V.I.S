from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)


class ClarificationState(Enum):
    NONE = auto()
    AWAITING_ANSWER = auto()


class ClarificationType(Enum):
    APP_ALREADY_RUNNING = auto()
    TAB_ALREADY_OPEN = auto()
    SWITCH_OR_NEW = auto()
    CURRENT_OR_NEW_TAB = auto()


@dataclass
class PendingClarification:
    question: str
    clarification_type: ClarificationType
    context: dict[str, Any] = field(default_factory=dict)
    follow_up_intent: str = ""


class ClarificationEngine:
    def __init__(self) -> None:
        self._pending: PendingClarification | None = None
        self._last_command: str = ""

    @property
    def has_pending(self) -> bool:
        return self._pending is not None

    @property
    def pending_question(self) -> str:
        return self._pending.question if self._pending else ""

    @property
    def pending_context(self) -> dict[str, Any]:
        return self._pending.context if self._pending else {}

    def store_last_command(self, command: str) -> None:
        self._last_command = command

    def get_last_command(self) -> str:
        return self._last_command

    def set_pending(
        self,
        question: str,
        ctype: ClarificationType,
        context: dict[str, Any] | None = None,
        follow_up_intent: str = "",
    ) -> None:
        self._pending = PendingClarification(
            question=question,
            clarification_type=ctype,
            context=context or {},
            follow_up_intent=follow_up_intent,
        )
        logger.info("Clarification pending: %s", question)

    def resolve_answer(self, answer: str) -> dict[str, Any]:
        if not self._pending:
            return {"action": "none", "intent": ""}

        pending = self._pending
        answer_lower = answer.strip().casefold()

        result: dict[str, Any] = {
            "clarification_type": pending.clarification_type,
            "context": pending.context,
            "original_question": pending.question,
            "raw_answer": answer,
        }

        if pending.clarification_type == ClarificationType.APP_ALREADY_RUNNING:
            if answer_lower in ("yes", "switch", "switch to it", "existing", "that one"):
                result["action"] = "switch_to_existing"
                result["intent"] = "focus_app"
            elif answer_lower in ("no", "new", "another", "open another", "new window", "open new"):
                result["action"] = "open_new_window"
                result["intent"] = "open_app"
            else:
                result["action"] = "unknown"

        elif pending.clarification_type == ClarificationType.TAB_ALREADY_OPEN:
            if answer_lower in ("yes", "switch", "switch to it", "existing", "that one", "current"):
                result["action"] = "switch_to_tab"
                result["intent"] = "focus_tab"
            elif answer_lower in ("no", "new", "another", "new tab", "open another", "open new"):
                result["action"] = "open_new_tab"
                result["intent"] = "open_website"
            else:
                result["action"] = "unknown"

        elif pending.clarification_type == ClarificationType.SWITCH_OR_NEW:
            if answer_lower in ("switch", "existing", "current", "this one", "yes"):
                result["action"] = "switch_to_existing"
                result["intent"] = "focus_app"
            elif answer_lower in ("new", "no", "another", "new window", "open another"):
                result["action"] = "open_new_window"
                result["intent"] = "open_app"
            else:
                result["action"] = "unknown"

        elif pending.clarification_type == ClarificationType.CURRENT_OR_NEW_TAB:
            if answer_lower in ("current", "this tab", "current tab", "here", "yes"):
                result["action"] = "use_current_tab"
                result["intent"] = "search"
            elif answer_lower in ("new", "new tab", "new window", "no", "another"):
                result["action"] = "open_new_tab"
                result["intent"] = "search"
            else:
                result["action"] = "unknown"

        else:
            result["action"] = "unknown"

        self.clear_pending()
        logger.info("Clarification resolved: action=%s intent=%s", result.get("action"), result.get("intent"))
        return result

    def clear_pending(self) -> None:
        self._pending = None
