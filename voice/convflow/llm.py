"""
voice/pipeline/llm.py

``LLMRouter`` — the gate that decides *whether* a command reaches the LLM.

The redesign's core rule: the LLM is only invoked for valid speech — a
recognizer-accepted, non-empty, high-confidence transcript.  Rejected or
empty input is short-circuited here so no model call, no hallucination, and
no wasted resources happen on background noise or a whisper the ASR could
not reliably hear.

Routing is a pure gate: it never calls the model itself.  Execution (and
the ``llm_ms`` / ``execution_ms`` timings) is owned by
:class:`CommandDispatcher`, and the routed intent/action names are pulled
from the resulting response via ``extract`` for the structured request log.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Tuple

logger = logging.getLogger(__name__)


class LlmDecision:
    """Outcome of gating a transcript.

    ``invoked`` is True only when the input is valid enough to run the LLM.
    """

    __slots__ = ("invoked", "rejected_reason")

    def __init__(self, invoked: bool, rejected_reason: str = "") -> None:
        self.invoked = invoked
        self.rejected_reason = rejected_reason

    @property
    def needs_repeat(self) -> bool:
        return self.rejected_reason != ""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"LlmDecision(invoked={self.invoked}, rejected={self.rejected_reason!r})"


class LLMRouter:
    """Gate for LLM invocation and response intent/action extraction.

    Args:
        intent_extractor: Optional ``(response) -> str`` naming the intent.
        action_extractor: Optional ``(response) -> str`` naming the action.
    """

    def __init__(
        self,
        intent_extractor: Callable[[Any], str] | None = None,
        action_extractor: Callable[[Any], str] | None = None,
    ) -> None:
        self._intent_extractor = intent_extractor or (lambda r: "")
        self._action_extractor = action_extractor or (lambda r: "")

    def route(
        self,
        text: str,
        confidence: float = 0.0,
        accepted: bool = False,
        rejected_reason: str = "",
    ) -> LlmDecision:
        """Gate one transcript.  If ``accepted`` is False (rejected / invalid
        speech) the LLM must not be invoked — the caller asks the user to
        repeat instead."""
        text = (text or "").strip()
        if not accepted or not text:
            reason = rejected_reason or ("empty text" if not text else "not accepted")
            return LlmDecision(False, rejected_reason=reason)
        return LlmDecision(True)

    def extract(self, response: Any) -> tuple[str, str]:
        """Return ``(intent, action)`` from a response for the request log."""
        try:
            intent = self._intent_extractor(response) or ""
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("intent extractor failed: %s", exc)
            intent = ""
        try:
            action = self._action_extractor(response) or ""
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("action extractor failed: %s", exc)
            action = ""
        return intent, action