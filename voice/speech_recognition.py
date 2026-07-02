"""
voice/speech_recognition.py

Speech-to-text adapter for push-to-talk input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class SpeechRecognitionResult:
    """Result of converting captured audio into text."""

    success: bool
    text: str = ""
    error: str = ""


class SpeechRecognition:
    """Convert one captured audio sample into text."""

    def __init__(
        self,
        *,
        recognizer_factory: Callable[[], Any] | None = None,
        language: str = "en-US",
    ) -> None:
        self._recognizer_factory = recognizer_factory
        self._language = language

    def recognize(self, audio: Any) -> SpeechRecognitionResult:
        """Recognize text from audio without raising runtime errors."""
        if audio is None:
            return SpeechRecognitionResult(
                success=False,
                error="No audio was captured.",
            )

        try:
            recognizer, sr = self._build_runtime()
        except Exception:
            return SpeechRecognitionResult(
                success=False,
                error="Speech recognition support is not available.",
            )

        try:
            text = recognizer.recognize_google(audio, language=self._language)
        except getattr(sr, "UnknownValueError", ValueError):
            return SpeechRecognitionResult(
                success=False,
                error="No speech could be recognized.",
            )
        except getattr(sr, "RequestError", RuntimeError):
            return SpeechRecognitionResult(
                success=False,
                error="Speech recognition service is unavailable.",
            )
        except TimeoutError:
            return SpeechRecognitionResult(
                success=False,
                error="Speech recognition timed out.",
            )
        except Exception:
            return SpeechRecognitionResult(
                success=False,
                error="Speech recognition failed.",
            )

        text = str(text).strip()
        if not text:
            return SpeechRecognitionResult(
                success=False,
                error="No speech could be recognized.",
            )

        return SpeechRecognitionResult(success=True, text=text)

    def _build_runtime(self) -> tuple[Any, Any]:
        if self._recognizer_factory is not None:
            return self._recognizer_factory(), _FallbackSpeechRecognition()

        import speech_recognition as sr

        return sr.Recognizer(), sr


class _FallbackSpeechRecognition:
    UnknownValueError = ValueError
    RequestError = RuntimeError
