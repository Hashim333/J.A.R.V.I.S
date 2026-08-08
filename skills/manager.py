"""
skills/manager.py

The Skill Manager - the awareness layer that makes JARVIS behave like an
intelligent assistant for requests it cannot execute.

Responsibilities:

  1. Answer capability meta-commands deterministically ("what can you do?",
     "what skills are missing?", "what can't you do yet?").
  2. Classify a request that the deterministic parser could not handle into
     the best-known capability (implemented or not).
  3. When the capability is acknowledged but not implemented: register the
     request in the persistent Skill Registry and reply with an explanation
     of what is missing plus the closest available capability.
  4. When the request is unintelligible: ask for a rephrase (never a bare
     "I don't know" / "Command not found" / "I can only open and close
     apps").

The manager is data-driven: it consults ``skills/capability.CATALOG``, so
new skills are added as plugin entries without changing this class.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from models.response import Response as ModelResponse
from models.task_result import TaskResult
from skills.capability import (
    Capability,
    keyword_weight,
    implemented_capabilities,
    unimplemented_capabilities,
)
from skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

_MIN_MISSING_SCORE = 2


# Meta-command phrases, normalised (lowercase, no punctuation).
_CAPABILITY_COMMANDS = (
    "what can you do", "what can you do for me",
    "what are your capabilities", "what are your abilities",
    "what are you capable of", "what do you do",
    "what can you help with", "how can you help",
    "list commands", "list capabilities", "list your commands",
    "list your capabilities", "show commands", "show capabilities",
    "show your capabilities", "what commands do you have",
    "capabilities", "commands", "help", "help me",
)

_MISSING_COMMANDS = (
    "what skills are missing", "skills are missing", "missing skills",
    "show requested features", "show me requested features",
    "requested features", "list requested features",
    "show unfinished skills", "show me unfinished skills",
    "unfinished skills", "list unfinished skills",
    "what skills have i requested", "what skills did i request",
    "my requested skills", "what is on the roadmap",
    "whats on the roadmap", "show roadmap", "roadmap",
)

_CANNOT_COMMANDS = (
    "what can't you do", "what cant you do", "what can you not do",
    "what can't you do yet", "what cant you do yet",
    "what can you not do yet", "what are you unable to do",
    "what do you struggle with", "what is missing",
    "what are you missing",
)


@dataclass(frozen=True)
class MissingSkillMatch:
    """A classified request that maps to an acknowledged-but-unimplemented skill."""

    capability: Capability
    score: int


class SkillManager:
    """Capability awareness, missing-skill registration and meta commands."""

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        capabilities: tuple[Capability, ...] | None = None,
    ) -> None:
        self._registry = registry or SkillRegistry()
        self._capabilities = tuple(capabilities) if capabilities is not None else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def registry(self) -> SkillRegistry:
        return self._registry

    def answer(self, text: str) -> ModelResponse | None:
        """Answer a capability meta-command, or ``None`` to continue.

        Never raises.  Detects "what can you do?", "what skills are
        missing?" and "what can't you do yet?" deterministically.
        """
        try:
            normalized = self._normalize(text)
        except Exception as exc:
            logger.warning("SkillManager.answer normalisation failed: %s", exc)
            return None
        if not normalized:
            return None

        if self._matches_any(normalized, _CANNOT_COMMANDS):
            return self._respond_cannot()
        if self._matches_any(normalized, _MISSING_COMMANDS):
            return self._respond_missing_list()
        if self._matches_any(normalized, _CAPABILITY_COMMANDS):
            return self._respond_capabilities()
        return None

    def classify_missing(self, text: str) -> MissingSkillMatch | None:
        """Classify an unparseable request into a missing capability.

        Returns a ``MissingSkillMatch`` only when the request clearly maps
        to an acknowledged-but-unimplemented skill (score >= threshold),
        otherwise ``None``.  Never raises.
        """
        try:
            normalized = self._normalize(text)
        except Exception as exc:
            logger.warning("SkillManager.classify_missing failed: %s", exc)
            return None
        if not normalized:
            return None

        best: Capability | None = None
        best_score = 0
        for cap in self._unimplemented:
            score = self._score(normalized, cap.keywords)
            if score > best_score:
                best_score = score
                best = cap
        if best is None or best_score < _MIN_MISSING_SCORE:
            return None
        return MissingSkillMatch(capability=best, score=best_score)

    def respond_missing(
        self,
        text: str,
        match: MissingSkillMatch,
        *,
        speech_confidence: float | None = None,
    ) -> ModelResponse:
        """Register the request and build a natural missing-capability reply."""
        cap = match.capability
        try:
            self._registry.request(
                cap.name,
                cap.label,
                category=cap.category,
                dependencies=cap.dependencies,
                closest_capability=cap.closest,
                last_request=text,
            )
        except Exception as exc:
            logger.warning("SkillRegistry.request failed: %s", exc)

        message = (
            f"I understand - you'd like to {cap.label}. "
            f"That skill isn't implemented yet; what's missing is {cap.missing}. "
            f"The closest thing I can do right now is {cap.closest}. "
            f"I've logged \"{cap.name}\" as a requested skill so it can be prioritised."
        )
        return self._response(
            message=message,
            text=text,
            category=cap.category,
            skill=cap.name,
            intent="unknown",
            speech_confidence=speech_confidence,
        )

    def respond_unintelligible(
        self,
        text: str,
        *,
        speech_confidence: float | None = None,
    ) -> ModelResponse:
        """Ask for a rephrase when nothing could be classified."""
        message = "I couldn't determine the requested action. Could you rephrase it?"
        return self._response(
            message=message,
            text=text,
            category="unclear",
            skill="",
            intent="unknown",
            speech_confidence=speech_confidence,
        )

    # ------------------------------------------------------------------
    # Meta-command responses
    # ------------------------------------------------------------------

    def _respond_capabilities(self) -> ModelResponse:
        labels = self._join_labels([c.label for c in self._implemented])
        message = (
            f"Here's what I can do: {labels}. "
            "I also understand requests I can't execute yet - ask me "
            "\"what skills are missing?\" to see the roadmap."
        )
        return self._response(message=message, text="", category="meta",
                              skill="", intent="help")

    def _respond_missing_list(self) -> ModelResponse:
        entries = self._registry.missing()
        if not entries:
            labels = self._join_labels([c.label for c in self._implemented])
            message = (
                "I don't have any unimplemented skills on file yet. "
                f"Right now I can {labels}. If you ask for something I "
                "can't do, I'll add it to my roadmap automatically."
            )
            return self._response(message=message, text="", category="meta",
                                  skill="", intent="help")

        lines = [
            f"Here's what's on my skill roadmap ({len(entries)} requested):",
        ]
        for e in entries:
            lines.append(
                f"- {e.get('skill')}: {e.get('description')} "
                f"(requested {e.get('date_requested')}, priority "
                f"{e.get('priority')}, status {e.get('status')})"
            )
        return self._response(
            message="\n".join(lines),
            text="",
            category="meta",
            skill="",
            intent="help",
            data={"roadmap": [dict(e) for e in entries]},
        )

    def _respond_cannot(self) -> ModelResponse:
        catalog_missing = self._join_labels([c.label for c in self._unimplemented])
        registered = self._registry.missing()
        lines = ["These are the skills I don't have yet:"]
        lines.append(f"- {catalog_missing}")
        if registered:
            lines.append("Requested ones already on my roadmap:")
            for e in registered:
                lines.append(
                    f"- {e.get('skill')} ({e.get('status')}, priority "
                    f"{e.get('priority')})"
                )
        labels = self._join_labels([c.label for c in self._implemented])
        lines.append(f"For anything else, I can {labels}.")
        return self._response(
            message=" ".join(lines),
            text="",
            category="meta",
            skill="",
            intent="help",
            data={"missing": [dict(e) for e in registered]},
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @property
    def _implemented(self) -> list[Capability]:
        if self._capabilities is not None:
            return sorted((c for c in self._capabilities if c.implemented),
                          key=lambda c: c.name)
        return implemented_capabilities()

    @property
    def _unimplemented(self) -> list[Capability]:
        if self._capabilities is not None:
            return sorted((c for c in self._capabilities if not c.implemented),
                          key=lambda c: c.name)
        return unimplemented_capabilities()

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(
            re.sub(r"[^\w\s']", " ", text or "").casefold().split()
        )

    @staticmethod
    def _matches_any(normalized: str, phrases: tuple[str, ...]) -> bool:
        for phrase in phrases:
            if " " not in phrase:
                if normalized == phrase:
                    return True
            elif normalized == phrase or normalized.startswith(phrase + " "):
                return True
        return False

    @staticmethod
    def _score(text: str, keywords: tuple[str, ...]) -> int:
        total = 0
        for kw in keywords:
            if kw in text:
                total += keyword_weight(kw)
        return total

    @staticmethod
    def _join_labels(labels: list[str]) -> str:
        if not labels:
            return "nothing"
        if len(labels) == 1:
            return labels[0]
        return ", ".join(labels[:-1]) + f", and {labels[-1]}"

    @staticmethod
    def _response(
        message: str,
        *,
        text: str,
        category: str,
        skill: str,
        intent: str,
        speech_confidence: float | None = None,
        data: dict[str, Any] | None = None,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "raw_text": text,
            "category": category,
            "intent": intent,
        }
        if skill:
            payload["skill"] = skill
            payload["status"] = "requested"
        if data:
            payload.update(data)
        return ModelResponse(
            success=True,
            message=message,
            data=payload,
            task_result=TaskResult.SUCCESS,
            confidence=1.0,
            speech_confidence=speech_confidence,
            reasoning="Deterministic Skill Manager response.",
        )
