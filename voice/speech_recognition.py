"""
voice/speech_recognition.py

A stateless adapter for converting audio data to text using an underlying
speech recognition engine.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpeechRecognitionResult:
    """Result of converting captured audio into text."""

    success: bool
    text: str = ""
    error: str = ""


class SpeechRecognition:
    """
    A stateless utility that converts a single audio sample into text.
    It acts as an adapter, wrapping a speech recognition engine.
    """

    def __init__(
        self,
        *,
        recognizer_factory: Callable[[], Any] | None = None,
        language: str = "en-US",
    ) -> None:
        """
        Initializes the SpeechRecognition adapter.

        Args:
            recognizer_factory: A callable that returns a speech recognizer
                instance. This allows for dependency injection, making the
                class testable and adaptable to different engines. If None,
                it defaults to `speech_recognition.Recognizer`.
            language: The language code for speech recognition (e.g., "en-US").
        """
        self._recognizer_factory = recognizer_factory
        self._language = language

    def recognize(self, audio: Any) -> SpeechRecognitionResult:
        """Recognize text from audio without raising runtime errors."""
        if audio is None:
            logger.warning("recognize() called with None audio")
            return SpeechRecognitionResult(
                success=False,
                error="No audio was captured.",
            )

        try:
            recognizer, sr_exceptions = self._get_runtime_dependencies()
        except Exception as exc:
            logger.error("Speech recognition deps failed: %s", exc)
            return SpeechRecognitionResult(
                success=False,
                error="Speech recognition support is not available.",
            )

        logger.debug("Google STT starting")
        try:
            text = recognizer.recognize_google(audio, language=self._language)
            logger.debug("Google STT succeeded: '%s'", text)
        except getattr(sr_exceptions, "UnknownValueError", ValueError):
            logger.info("Google STT: no speech recognized")
            return SpeechRecognitionResult(
                success=False,
                error="No speech could be recognized.",
            )
        except getattr(sr_exceptions, "RequestError", RuntimeError) as exc:
            logger.warning("Google STT request error: %s", exc)
            return SpeechRecognitionResult(
                success=False,
                error="Speech recognition service is unavailable.",
            )
        except TimeoutError:
            logger.warning("Google STT timed out")
            return SpeechRecognitionResult(
                success=False,
                error="Speech recognition timed out.",
            )
        except Exception as exc:
            logger.error("Google STT failed: %s", exc)
            return SpeechRecognitionResult(
                success=False,
                error="Speech recognition failed.",
            )

        text = str(text).strip()
        if not text:
            logger.info("Google STT returned empty text")
            return SpeechRecognitionResult(
                success=False,
                error="No speech could be recognized.",
            )

        return SpeechRecognitionResult(success=True, text=text)

    def _get_runtime_dependencies(self) -> tuple[Any, Any]:
        if self._recognizer_factory is not None:
            return self._recognizer_factory(), _FallbackSpeechRecognition()

        import speech_recognition as sr

        return sr.Recognizer(), sr  # type: ignore[misc]


class _FallbackSpeechRecognition:
    UnknownValueError = ValueError
    RequestError = RuntimeError
