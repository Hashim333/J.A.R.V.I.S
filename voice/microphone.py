"""
voice/microphone.py

One-shot microphone capture for push-to-talk input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class MicrophoneCapture:
    """Result of a single microphone capture attempt."""

    success: bool
    audio: Any = None
    error: str = ""


class MicrophoneManager:
    """Open the microphone, capture one utterance, then close it."""

    def __init__(
        self,
        *,
        recognizer_factory: Callable[[], Any] | None = None,
        microphone_factory: Callable[[], Any] | None = None,
        timeout: float = 5.0,
        phrase_time_limit: float = 10.0,
    ) -> None:
        self._recognizer_factory = recognizer_factory
        self._microphone_factory = microphone_factory
        self._timeout = timeout
        self._phrase_time_limit = phrase_time_limit

    def capture_once(self) -> MicrophoneCapture:
        """Capture one voice command and always release the microphone."""
        try:
            recognizer, microphone_factory, sr = self._build_runtime()
        except Exception:
            return MicrophoneCapture(
                success=False,
                error="Microphone support is not available.",
            )

        try:
            with microphone_factory() as source:
                self._adjust_for_noise(recognizer, source)
                audio = recognizer.listen(
                    source,
                    timeout=self._timeout,
                    phrase_time_limit=self._phrase_time_limit,
                )
        except getattr(sr, "WaitTimeoutError", TimeoutError):
            return MicrophoneCapture(success=False, error="No speech was detected.")
        except OSError:
            return MicrophoneCapture(
                success=False,
                error="Microphone is unavailable.",
            )
        except Exception:
            return MicrophoneCapture(
                success=False,
                error="Microphone capture failed.",
            )

        return MicrophoneCapture(success=True, audio=audio)

    def _build_runtime(self) -> tuple[Any, Callable[[], Any], Any]:
        if self._recognizer_factory is not None and self._microphone_factory is not None:
            return self._recognizer_factory(), self._microphone_factory, _FallbackSpeechRecognition()

        import speech_recognition as sr

        recognizer_factory = self._recognizer_factory or sr.Recognizer
        microphone_factory = self._microphone_factory or sr.Microphone
        return recognizer_factory(), microphone_factory, sr

    @staticmethod
    def _adjust_for_noise(recognizer: Any, source: Any) -> None:
        adjust = getattr(recognizer, "adjust_for_ambient_noise", None)
        if callable(adjust):
            adjust(source, duration=0.2)


class _FallbackSpeechRecognition:
    WaitTimeoutError = TimeoutError
