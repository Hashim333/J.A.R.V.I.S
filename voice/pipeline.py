"""
voice/pipeline.py

Reliable voice conversation pipeline.

After wake word detection:
  1. Play confirmation sound (beep) + say "Yes?"
  2. Wait until the user starts speaking (VAD-based)
  3. Record until silence or max duration
  4. Send complete recording to Speech Recognition
  5. Retry on failure (up to 3 attempts)
  6. Detailed logs at every stage
"""

from __future__ import annotations

import logging
from typing import Any

from voice.microphone_stream import MicrophoneStream

logger = logging.getLogger(__name__)


class VoiceConversationPipeline:
    """
    Orchestrates wake-to-command voice capture with confirmation,
    VAD-based waiting, and retry logic.

    Does not import or depend on Brain, Planner, Executor, or any
    automation module.
    """

    def __init__(
        self,
        listener_service: Any,
        voice_manager: Any,
        microphone_stream: MicrophoneStream,
        max_retries: int = 3,
        capture_timeout: float = 10.0,
    ) -> None:
        """
        Args:
            listener_service: Service used to transcribe captured audio.
            voice_manager: VoiceManager instance for TTS prompts (
                may be None — only the beep will be used).
            microphone_stream: Shared continuous microphone stream.
            max_retries: Number of capture+STT attempts before giving up.
            capture_timeout: Max seconds to wait for the user to speak
                in each attempt.
        """
        self._listener_service = listener_service
        self._voice_manager = voice_manager
        self._microphone_stream = microphone_stream
        self._max_retries = max_retries
        self._capture_timeout = capture_timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def wait_for_command(self, wake_word_detected_event: Any) -> str | None:
        """
        Block until a wake word is detected, then capture and transcribe
        a spoken command.

        Returns the transcribed text, or None if all retries were
        exhausted and the user could not be understood.
        """
        # ── Step 1: Wait for wake word ──────────────────────────────
        wake_word_detected_event.wait()
        wake_word_detected_event.clear()
        logger.info("Wake detected")

        # ── Step 2: Play confirmation ───────────────────────────────
        self._play_confirmation()
        logger.info("Waiting for user")

        # ── Step 3: Capture + STT with retries ──────────────────────
        for attempt in range(1, self._max_retries + 1):
            logger.info(
                "Listening for command (attempt %d/%d, timeout=%.1f)",
                attempt, self._max_retries, self._capture_timeout,
            )

            audio = self._microphone_stream.capture_utterance(
                timeout=self._capture_timeout,
            )

            if audio is None:
                logger.warning(
                    "No audio captured (attempt %d/%d)",
                    attempt, self._max_retries,
                )
                if attempt < self._max_retries:
                    self._say("I didn't hear anything. Please try again.")
                else:
                    self._say("Sorry, I could not understand that.")
                continue

            # Log recording metadata
            recording_length = (
                len(audio.frame_data) if hasattr(audio, "frame_data") else 0
            )
            duration = (
                recording_length / (audio.sample_rate * audio.sample_width)
                if hasattr(audio, "sample_rate")
                   and hasattr(audio, "sample_width")
                   and audio.sample_width > 0
                else 0.0
            )
            logger.info(
                "User started speaking -> recording length: %d bytes "
                "(%.1f seconds)",
                recording_length, duration,
            )

            # ── Step 4: Speech-to-Text ──────────────────────────────
            result = self._listener_service.transcribe(audio)

            if result.success and result.text:
                logger.info("STT success: '%s'", result.text)
                logger.info("Recognized text: '%s'", result.text)
                return result.text

            logger.warning(
                "STT failure (attempt %d/%d): %s",
                attempt, self._max_retries, result.error,
            )

            # ── Step 5: Retry prompt ────────────────────────────────
            if attempt < self._max_retries:
                self._say("I didn't catch that. Please repeat.")
            else:
                self._say("Sorry, I could not understand that.")

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _play_confirmation(self) -> None:
        """Play a short confirmation beep and speak 'Yes?'."""
        self._beep()
        self._say("Yes?")

    @staticmethod
    def _beep() -> None:
        """Emit a short 800 Hz beep (Windows). No-op elsewhere."""
        try:
            import winsound
            winsound.Beep(800, 150)
        except Exception:
            pass

    def _say(self, text: str) -> None:
        """Speak text via the voice manager (best-effort, non-blocking)."""
        if self._voice_manager is not None:
            try:
                self._voice_manager.speak(text)
            except Exception as exc:
                logger.debug("Voice playback failed: %s", exc)
