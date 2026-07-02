"""
voice/push_to_talk.py

Push-to-talk orchestration for one explicit voice command.
"""

from __future__ import annotations

from config.settings import settings
from voice.microphone import MicrophoneManager
from voice.speech_recognition import SpeechRecognition


class PushToTalk:
    """Capture and recognize one command when explicitly requested."""

    def __init__(
        self,
        microphone: MicrophoneManager | None = None,
        speech_recognition: SpeechRecognition | None = None,
        *,
        enabled: bool | None = None,
        key: str | None = None,
    ) -> None:
        self._microphone = microphone or MicrophoneManager()
        self._speech_recognition = speech_recognition or SpeechRecognition()
        self.enabled = settings.push_to_talk_enabled if enabled is None else enabled
        self.key = settings.push_to_talk_key if key is None else key
        self.last_error = ""

    def listen_once(self) -> str:
        """Capture one utterance and return the recognized command text."""
        self.last_error = ""

        if not self.enabled:
            self.last_error = "Push-to-talk is disabled."
            return ""

        capture = self._microphone.capture_once()
        if not capture.success:
            self.last_error = capture.error
            return ""

        recognized = self._speech_recognition.recognize(capture.audio)
        if not recognized.success:
            self.last_error = recognized.error
            return ""

        return recognized.text
