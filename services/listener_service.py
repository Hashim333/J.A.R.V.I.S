"""
services/listener_service.py

A service responsible for capturing and transcribing a single spoken command.

It supports two capture back-ends:

1. **MicrophoneStream** (preferred) — uses the shared continuous microphone
   stream that is already open.  No lock contention, no device re-open.
2. **MicrophoneManager** (fallback) — legacy one-shot open/capture/close
   cycle, subject to ``audio_lock`` contention.

The back-end is selected automatically based on which dependency is
injected at construction time.
"""

from __future__ import annotations

import logging
from typing import Any

from services.base_service import BaseService
from voice.microphone import MicrophoneManager
from voice.microphone_stream import MicrophoneStream
from voice.speech_recognition import SpeechRecognition, SpeechRecognitionResult

logger = logging.getLogger(__name__)


class ListenerService(BaseService):
    """
    Orchestrates the process of listening for a single command and
    transcribing it to text.

    This service does not perform wake-word detection. It is designed to be
    activated on-demand to capture a command after a wake-word has already
    been detected by another service.
    """

    def __init__(
        self,
        microphone_manager: MicrophoneManager | None = None,
        speech_recognition: SpeechRecognition | None = None,
        max_retries: int = 2,
        microphone_stream: MicrophoneStream | None = None,
    ) -> None:
        """
        Initializes the ListenerService.

        Args:
            microphone_manager: Legacy one-shot microphone manager (used
                when *microphone_stream* is not provided).
            speech_recognition: Engine for audio-to-text transcription.
            max_retries: Number of times to retry listening on failure.
            microphone_stream: Shared continuous microphone stream.
                When provided, *microphone_manager* is ignored for
                :meth:`listen_for_command`.
        """
        super().__init__(name="listener")
        self._microphone_manager = microphone_manager or MicrophoneManager()
        self._speech_recognition = speech_recognition or SpeechRecognition()
        self._max_retries = max_retries
        self._microphone_stream = microphone_stream

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def listen_for_command(self, timeout: float | None = None) -> SpeechRecognitionResult:
        """
        Captures a single utterance from the microphone and returns the
        transcription result with retries.

        If a MicrophoneStream was injected, the shared stream is used
        (no device re-open).  Otherwise falls back to the legacy
        ``MicrophoneManager.capture_once()``.

        Args:
            timeout: Maximum seconds to wait for speech.

        Returns:
            A SpeechRecognitionResult object containing the outcome.
        """
        if self._microphone_stream is not None:
            return self._listen_via_stream(timeout or 10.0)
        return self._listen_via_manager(timeout)

    def transcribe(self, audio_data: Any) -> SpeechRecognitionResult:
        """
        Transcribe pre-captured audio without opening the microphone.

        This is the companion to :meth:`listen_for_command`: it performs
        the same transcription step without the microphone capture step.
        Used to transcribe audio captured during wake-word detection.

        Args:
            audio_data: An ``sr.AudioData`` instance (or anything the
                speech recognition engine accepts).

        Returns:
            A SpeechRecognitionResult.
        """
        return self._speech_recognition.recognize(audio_data)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """No-op. Resources are managed on-demand by collaborators."""
        pass

    def start(self) -> None:
        """No-op. This service is not a long-running process."""
        pass

    def stop(self) -> None:
        """No-op. This service does not have a running state to stop."""
        pass

    # ------------------------------------------------------------------
    # Back-end: MicrophoneStream (VAD-based one-shot)
    # ------------------------------------------------------------------

    def _listen_via_stream(self, timeout: float) -> SpeechRecognitionResult:
        """Capture via the shared MicrophoneStream using VAD end-of-speech detection."""
        attempts = 0
        max_attempts = self._max_retries + 1
        while attempts < max_attempts:
            attempts += 1
            logger.debug(
                "Listening via stream (attempt %d/%d, timeout=%.1f)",
                attempts, max_attempts, timeout,
            )
            audio = self._microphone_stream.capture_utterance(timeout=timeout)
            if audio is None:
                logger.warning(
                    "Stream capture returned None (attempt %d/%d)",
                    attempts, max_attempts,
                )
                if attempts < max_attempts:
                    continue
                return SpeechRecognitionResult(
                    success=False, error="No speech captured.",
                )

            result = self._speech_recognition.recognize(audio)
            if result.success and result.text:
                logger.info("Command recognized via stream: '%s'", result.text)
                print(f"\n[LISTENER] RAW TRANSCRIPT: {result.text!r}")
                return result

            logger.warning(
                "Recognition failed via stream (attempt %d/%d): %s",
                attempts, max_attempts, result.error,
            )
            if attempts < max_attempts:
                continue
            return result

        return SpeechRecognitionResult(
            success=False, error="Failed to capture command after retries.",
        )

    # ------------------------------------------------------------------
    # Back-end: MicrophoneManager (legacy one-shot open/capture/close)
    # ------------------------------------------------------------------

    def _listen_via_manager(self, timeout: float | None) -> SpeechRecognitionResult:
        """Fallback capture via the legacy one-shot MicrophoneManager."""
        attempts = 0
        max_attempts = self._max_retries + 1
        while attempts < max_attempts:
            attempts += 1
            logger.debug(
                "Listening via manager (attempt %d/%d)", attempts, max_attempts
            )
            capture = self._microphone_manager.capture_once(timeout=timeout)
            if not capture.success:
                logger.warning(
                    "Microphone capture failed (attempt %d/%d): %s",
                    attempts, max_attempts, capture.error
                )
                if attempts < max_attempts:
                    continue
                return SpeechRecognitionResult(success=False, error=capture.error)

            result = self._speech_recognition.recognize(capture.audio)
            if result.success and result.text:
                logger.info("Command recognized via manager: '%s'", result.text)
                print(f"\n[LISTENER] RAW TRANSCRIPT: {result.text!r}")
                return result

            logger.warning(
                "Speech recognition failed (attempt %d/%d): %s",
                attempts, max_attempts, result.error
            )
            if attempts < max_attempts:
                continue

            return result

        return SpeechRecognitionResult(
            success=False, error="Failed to capture command after retries."
        )
