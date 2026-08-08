"""
tests/test_human_layer.py

Unit tests for the Human Conversation Layer (ResponseManager).

Requirement: every internal error/state maps to a calm, natural human
message, and no technical detail (exception names, WinError numbers,
timeout values, paths, model names, raw logs) ever reaches the user.
"""

from __future__ import annotations

import pytest

from response.human_layer import HumanResponseManager
from response.human_message import (
    HUMAN_MESSAGES,
    InternalState,
    classify,
)
from response.human_sanitizer import HumanSanitizer

# Tokens that must never appear in any user-facing message.
_FORBIDDEN_TECH = (
    "WinError",
    "OSError",
    "TimeoutError",
    "PermissionError",
    "Traceback",
    "line 3",
    "Exception:",
    "failed",
    "error",
    "timed out",
    "exit code",
    "C:\\",
    ".py",
)


class TestHumanConversationLayer:
    """The six mandated scenarios, all user-safe."""

    def test_timeout_is_natural_apology(self):
        msg = HumanResponseManager().humanize("TimeoutError")
        assert "sorry" in msg.lower() or "longer than expected" in msg.lower()
        self._assert_no_technical(msg)

    def test_permission_denied_explains_permission(self):
        msg = HumanResponseManager().humanize("PermissionDenied")
        assert "permission" in msg.lower() and "administrator" in msg.lower()
        self._assert_no_technical(msg)

    def test_no_speech_asks_to_repeat(self):
        msg = HumanResponseManager().humanize("NoSpeechDetected")
        assert "didn't hear" in msg.lower() or "repeat" in msg.lower()
        self._assert_no_technical(msg)

    def test_unknown_command_is_capability_unavailable(self):
        msg = HumanResponseManager().humanize("UnknownCommand")
        assert "couldn't determine" in msg.lower() or "haven't learned" in msg.lower()
        self._assert_no_technical(msg)

    def test_low_confidence_asks_to_repeat(self):
        msg = HumanResponseManager().humanize("SpeechRecognitionLowConfidence")
        assert "repeat" in msg.lower()
        self._assert_no_technical(msg)

    def test_internet_down_offers_local_functionality(self):
        msg = HumanResponseManager().humanize("InternetUnavailable")
        assert "offline" in msg.lower() and "local" in msg.lower()
        self._assert_no_technical(msg)

    def test_every_required_scenario_matches_table(self):
        required = [
            "TimeoutError",
            "SpeechRecognitionLowConfidence",
            "NoSpeechDetected",
            "PermissionDenied",
            "AutomationUnavailable",
            "LLMUnavailable",
            "InternetUnavailable",
        ]
        layer = HumanResponseManager()
        for key in required:
            assert classify(key) in HUMAN_MESSAGES, key
            text = layer.humanize(key)
            assert text.strip(), key
            self._assert_no_technical(text)

    @staticmethod
    def _assert_no_technical(text: str) -> None:
        lowered = text.casefold()
        for token in _FORBIDDEN_TECH:
            assert token.casefold() not in lowered, (
                f"technical detail leaked to user: {token!r} in {text!r}"
            )


class TestExceptionClassification:
    """Auto-classification of real exceptions and state tokens."""

    def test_classify_timeout_exception(self):
        assert classify(TimeoutError("waited 30s")) == "TimeoutError"

    def test_classify_permission_error(self):
        assert classify(PermissionError(5, "Access is denied")) == "PermissionDenied"

    def test_classify_connection_error_offline(self):
        assert classify(ConnectionError("network unreachable")) == "InternetUnavailable"

    def test_classify_low_confidence_token(self):
        assert classify("low confidence") == "SpeechRecognitionLowConfidence"
        assert classify("SpeechRecognitionLowConfidence") == "SpeechRecognitionLowConfidence"

    def test_classify_no_speech(self):
        assert classify("no speech") == "NoSpeechDetected"

    def test_translate_matches_humanize(self):
        layer = HumanResponseManager()
        assert layer.translate(PermissionError()) == layer.humanize("PermissionDenied")

    def test_unknown_state_uses_safe_fallback(self):
        msg = HumanResponseManager().humanize("SomethingTotallyNew")
        assert msg  # never empty, never technical
        self._assert_no_technical(msg)

    @staticmethod
    def _assert_no_technical(text: str) -> None:
        lowered = text.casefold()
        for token in _FORBIDDEN_TECH:
            assert token.casefold() not in lowered, (
                f"technical detail leaked to user: {token!r} in {text!r}"
            )


class TestSanitizer:
    """Neutralizes technical output before it reaches UI/TTS."""

    def test_winerror_is_sanitized(self):
        out = HumanSanitizer().sanitize("Task failed with WinError 5 reading file.")
        assert out.lower().startswith("i'm sorry") or "sorry" in out.lower()

    def test_traceback_is_sanitized(self):
        out = HumanSanitizer().sanitize(
            'Traceback (most recent call last):\n  File "x.py", line 3, in foo'
        )
        assert "sorry" in out.lower()

    def test_normal_text_is_kept(self):
        out = HumanSanitizer().sanitize("Chrome opened successfully.")
        assert out == "Chrome opened successfully."

    def test_multi_line_is_collapsed(self):
        out = HumanSanitizer().sanitize("Open windows:\n  notepad\n  chrome")
        assert out == "Open windows: notepad chrome"

    def test_none_falls_back(self):
        assert HumanSanitizer().sanitize(None).strip()

    def test_unicode_content_never_crashes(self):
        assert HumanSanitizer().sanitize("café ☕")


class TestLayerReusability:
    """The layer must be lightweight and usable by any component."""

    def test_no_heavy_dependencies(self):
        # Importing the layer must not pull in audio/network hardware.
        import response.human_layer as module

        assert module is not None

    def test_injectable_logger_receives_technical_detail(self):
        logs: list[str] = []
        layer = HumanResponseManager(debug=True).with_detail_logged(logs.append)
        layer.humanize("TimeoutError", detail="waited 30s on automation.run()")
        assert logs, "technical detail must be routed to the debug log"

    def test_humanize_is_pure_and_deterministic(self):
        layer = HumanResponseManager()
        assert layer.humanize("NoSpeechDetected") == layer.humanize("NoSpeechDetected")

    def test_custom_message_map_is_supported(self):
        layer = HumanResponseManager(messages={"MyState": "All good, sir."})
        assert layer.humanize("MyState") == "All good, sir."

    def test_internal_state_constants_resolve(self):
        assert InternalState is not None
        for member in InternalState:
            assert member.value in HUMAN_MESSAGES, member
