"""
voice/microphone.py

One-shot microphone capture for push-to-talk input.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from voice.audio_lock import audio_lock

logger = logging.getLogger(__name__)


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
        timeout: float = 10.0,
        phrase_time_limit: float = 30.0,
    ) -> None:
        self._recognizer_factory = recognizer_factory
        self._microphone_factory = microphone_factory
        self._timeout = timeout
        self._phrase_time_limit = phrase_time_limit

    def capture_once(self, timeout: float | None = None) -> MicrophoneCapture:
        """Capture one voice command and always release the microphone."""
        try:
            recognizer, microphone_factory, sr = self._build_runtime()
        except Exception as exc:
            logger.error("Microphone runtime build failed: %s", exc)
            return MicrophoneCapture(
                success=False,
                error="Microphone support is not available.",
            )

        effective_timeout = timeout if timeout is not None else self._timeout

        logger.debug(
            "Recognizer settings: energy_threshold=%s, dynamic_energy_threshold=%s, "
            "pause_threshold=%s, phrase_threshold=%s, non_speaking_duration=%s, "
            "timeout=%s, phrase_time_limit=%s",
            getattr(recognizer, "energy_threshold", "N/A"),
            getattr(recognizer, "dynamic_energy_threshold", "N/A"),
            getattr(recognizer, "pause_threshold", "N/A"),
            getattr(recognizer, "phrase_threshold", "N/A"),
            getattr(recognizer, "non_speaking_duration", "N/A"),
            effective_timeout,
            self._phrase_time_limit,
        )

        logger.debug("MicrophoneManager: acquiring lock (timeout=%.1f)", effective_timeout)
        if not audio_lock.acquire("microphone_manager", timeout=effective_timeout):
            logger.warning("MicrophoneManager: audio lock timeout")
            return MicrophoneCapture(
                success=False,
                error="Microphone is in use by another component.",
            )

        try:
            with microphone_factory() as source:
                self._adjust_for_noise(recognizer, source)
                logger.debug("MicrophoneManager: listening (timeout=%.1f, phrase_limit=%.1f)",
                            effective_timeout, self._phrase_time_limit)
                audio = recognizer.listen(
                    source,
                    timeout=effective_timeout,
                    phrase_time_limit=self._phrase_time_limit,
                )
            logger.debug("MicrophoneManager: audio captured (%d bytes)",
                        len(audio.frame_data) if hasattr(audio, 'frame_data') else 0)
        except getattr(sr, "WaitTimeoutError", TimeoutError):
            logger.info("MicrophoneManager: no speech detected (timeout)")
            return MicrophoneCapture(success=False, error="No speech was detected.")
        except OSError as exc:
            logger.error("MicrophoneManager: OSError: %s", exc)
            return MicrophoneCapture(
                success=False,
                error="Microphone is unavailable.",
            )
        except Exception as exc:
            logger.error("MicrophoneManager: capture failed: %s", exc)
            return MicrophoneCapture(
                success=False,
                error="Microphone capture failed.",
            )
        else:
            return MicrophoneCapture(success=True, audio=audio)
        finally:
            audio_lock.release("microphone_manager")

    def _build_runtime(self) -> tuple[Any, Callable[[], Any], Any]:
        if self._recognizer_factory is not None and self._microphone_factory is not None:
            recognizer = self._recognizer_factory()
            self._configure_recognizer(recognizer)
            return recognizer, self._microphone_factory, _FallbackSpeechRecognition()

        import speech_recognition as sr

        recognizer_factory = self._recognizer_factory or sr.Recognizer
        microphone_factory = self._microphone_factory or sr.Microphone
        recognizer = recognizer_factory()
        self._configure_recognizer(recognizer)
        return recognizer, microphone_factory, sr

    @staticmethod
    def _configure_recognizer(recognizer: Any) -> None:
        dynamic = getattr(recognizer, "dynamic_energy_threshold", None)
        if dynamic is not None:
            recognizer.dynamic_energy_threshold = True

        pause = getattr(recognizer, "pause_threshold", None)
        if pause is not None:
            recognizer.pause_threshold = 1.2
        phrase = getattr(recognizer, "phrase_threshold", None)
        if phrase is not None:
            recognizer.phrase_threshold = 0.3
        non_speaking = getattr(recognizer, "non_speaking_duration", None)
        if non_speaking is not None:
            recognizer.non_speaking_duration = 0.8

    @staticmethod
    def _adjust_for_noise(recognizer: Any, source: Any) -> None:
        adjust = getattr(recognizer, "adjust_for_ambient_noise", None)
        if callable(adjust):
            adjust(source, duration=0.5)


class _FallbackSpeechRecognition:
    WaitTimeoutError = TimeoutError
