from __future__ import annotations

from typing import Any

from models.response import Response

_LOW_CONFIDENCE_THRESHOLD = 0.5
_LOW_CONFIDENCE_PREFIX = "I'm not fully sure, but "


_GENERIC_MESSAGES = (
    "done.",
    "done",
    "ok.",
    "ok",
    "okay.",
    "okay",
    "completed.",
    "completed",
    "action completed.",
    "all 1 step(s) executed successfully.",
    "all 2 step(s) executed successfully.",
    "all 3 step(s) executed successfully.",
    "unknown command.",
    "unknown command",
)

# FIX-VOICE-003: short response templates for deterministic commands
_SHORT_RESPONSES = {
    "open_app": "Opening.",
    "close_app": "Closing.",
    "focus_app": "Switching.",
    "open_website": "Opening.",
    "search": "Searching.",
    "play_music": "Playing.",
    "play_video": "Playing.",
    "media_pause": "Paused.",
    "media_resume": "Resumed.",
    "media_next": "Next.",
    "media_previous": "Previous.",
    "increase_volume": "Volume up.",
    "decrease_volume": "Volume down.",
    "mute_volume": "Muted.",
    "unmute_volume": "Unmuted.",
    "set_volume": "Volume adjusted.",
    "screenshot": "Screenshot taken.",
    "lock": "Locking.",
    "shutdown_windows": "Shutting down.",
    "restart": "Restarting.",
    "sleep": "Going to sleep.",
    "noop": "Got it.",
    "report_time": "Check.",
}

# FIX-VOICE-003: deterministic conversational responses for common phrases
# These bypass the LLM entirely and return immediately
_DETERMINISTIC_CONVERSATIONAL_RESPONSES = {
    "can you hear me": "Yes.",
    "can you hear me?": "Yes.",
    "are you there": "Yes.",
    "are you listening": "Yes.",
    "jarvis can you hear me": "Yes.",
    "jarvis are you there": "Yes.",
    "jarvis are you listening": "Yes.",
}


class ResponseGenerator:
    def generate(
        self,
        executor_response: Response | None,
        intent: str,
        raw_text: str,
        verification_message: str = "",
        pipeline_reasoning: str = "",
        confidence: float | None = None,
    ) -> Response:
        if executor_response is None:
            return Response(
                success=False,
                message="I couldn't complete that.",
                data={"raw_text": raw_text},
                confidence=confidence,
            )

        if executor_response.needs_clarification:
            return executor_response

        if not executor_response.success:
            message = self._format_failure_message(executor_response)
            data = dict(executor_response.data)
            data["raw_text"] = raw_text
            data["intent"] = intent
            return Response(
                success=False,
                message=self._hedge(message, confidence),
                data=data,
                error=executor_response.error,
                confidence=confidence,
                reasoning=pipeline_reasoning,
            )

        message = executor_response.message
        if not message or self._is_generic(message):
            message = self._generate_success_message(intent, executor_response.data, raw_text)

        data = dict(executor_response.data)
        data["raw_text"] = raw_text
        data["intent"] = intent
        if pipeline_reasoning:
            data["reasoning"] = pipeline_reasoning

        return Response(
            success=True,
            message=self._hedge(message, confidence),
            data=data,
            confidence=confidence,
            reasoning=pipeline_reasoning,
        )

    @staticmethod
    def _hedge(message: str, confidence: float | None) -> str:
        """Honestly flag low-confidence reasoning without blocking the action."""
        if confidence is None or confidence >= _LOW_CONFIDENCE_THRESHOLD:
            return message
        lower = message.strip().casefold()
        if lower.startswith(_LOW_CONFIDENCE_PREFIX.strip()):
            return message
        return f"{_LOW_CONFIDENCE_PREFIX}{message[0].casefold() if message else ''}{message[1:] if message else ''}".strip()

    @staticmethod
    def _is_generic(message: str) -> bool:
        lower = (message or "").strip().casefold()
        if lower in _GENERIC_MESSAGES:
            return True
        if lower.startswith("step ") and lower.endswith(" completed."):
            return True
        if lower.startswith("all ") and "step(s) executed successfully" in lower:
            return True
        return False

    @staticmethod
    def _format_failure_message(executor_response: Response) -> str:
        reason = ""
        recovery = ""
        data = executor_response.data or {}
        if data.get("reason"):
            reason = str(data.get("reason"))
        if data.get("recovery"):
            recovery = str(data.get("recovery"))
        if not reason and executor_response.error:
            reason = str(executor_response.error)

        if reason and recovery:
            return f"{reason}. {recovery}"
        if reason:
            return reason
        return executor_response.message or "I couldn't complete that."

    @staticmethod
    def _generate_success_message(intent: str, data: dict[str, Any], raw_text: str = "") -> str:
        # FIX-VOICE-003: check for deterministic conversational responses
        # Normalize the raw text to handle case, punctuation, and extra spaces
        normalized = raw_text.strip().casefold().rstrip(".?")
        if normalized in _DETERMINISTIC_CONVERSATIONAL_RESPONSES:
            return _DETERMINISTIC_CONVERSATIONAL_RESPONSES[normalized]
        
        if intent == "open_app":
            app = data.get("app_name") or data.get("display_name", "")
            if app:
                return f"{app} is now open."
            return "Opening."
        if intent == "close_app":
            app = data.get("app_name") or data.get("display_name", "")
            if app:
                return f"{app} has been closed."
            return "Closing."
        if intent == "focus_app":
            app = data.get("app_name") or data.get("display_name", "")
            if app:
                return f"Switching to {app}."
            return "Switching."
        if intent == "open_website":
            site = data.get("website", "") or data.get("url", "")
            return f"Opened {site}." if site else "Opening."
        if intent == "search":
            query = data.get("query", "")
            provider = data.get("provider", "")
            if query and provider:
                return f"Searching for '{query}' on {provider.capitalize()}."
            if query:
                return f"Searching for '{query}'."
            return "Searching."
        if intent == "play_music":
            query = data.get("query", "")
            return f"Playing '{query}'." if query else "Playing music."
        if intent == "increase_volume":
            return "Volume up."
        if intent == "decrease_volume":
            return "Volume down."
        if intent == "mute_volume":
            return "Muted."
        if intent == "unmute_volume":
            return "Unmuted."
        if intent == "set_volume":
            level = data.get("level", "")
            return f"Volume set to {level}." if level else "Volume adjusted."
        if intent == "screenshot":
            return "Screenshot taken."
        if intent == "lock":
            return "Locking."
        if intent == "shutdown_windows":
            return "Shutting down."
        if intent == "restart":
            return "Restarting."
        if intent == "sleep":
            return "Going to sleep."
        if intent == "noop":
            return "Got it."
        # FIX-VOICE-003: terse fallback for intents without entity data
        # (media pause/next/etc.).  Contextual branches above take priority
        # so e.g. "search" still names the query and provider.
        if intent in _SHORT_RESPONSES:
            return _SHORT_RESPONSES[intent]
        # Fallback: use raw_text to construct a minimal contextual reply.
        # Never claim a generic "Done." / "Completed." — reflect the request.
        if raw_text:
            short = raw_text.strip().rstrip(".")
            if len(short) < 60 and short:
                return f"{short[0].upper()}{short[1:]}."
        return "Understood."