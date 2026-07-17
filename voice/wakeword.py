"""
voice/wakeword.py

Wake-word detection using VAD for speech boundaries and Vosk for a local
offline wake-word check.

Every speech segment captured by VAD is transcribed locally via Vosk.
Only segments confirmed to contain the wake phrase ("jarvis") trigger the
``on_wake_word_detected`` callback, which passes the raw audio data for
subsequent cloud transcription. Non-wake speech is silently discarded —
no cloud calls, no data leaves the device.
"""

from __future__ import annotations

import logging

from voice.local_wake_word import LocalWakeWordDetector
from voice.vad import VAD

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """
    Detects the wake phrase in a continuous audio stream.

    Architecture: MicrophoneStream -> WakeWordDetector -> VAD -> Vosk
    """

    # Pre-roll: 640ms of 16-bit 16kHz PCM audio.
    # VAD needs up to ~570ms (19 frames @ 30ms) to trigger in the worst
    # case (first 9 frames classified as non-speech).  This value ensures
    # the first syllable of "Jarvis" is always in the rolling buffer.
    _ROLLING_BUFFER_BYTES = 20480

    # Minimum audio length to attempt recognition (~125ms)
    _MIN_AUDIO_BYTES = 4000

    # Maximum capture duration before force-processing (~4 seconds)
    _MAX_CAPTURE_BYTES = 128000

    def __init__(
        self,
        on_wake_word_detected: object,
        sample_rate: int = 16000,
        sample_width: int = 2,
    ) -> None:
        self._on_wake_word_detected = on_wake_word_detected
        self._sample_rate = sample_rate
        self._sample_width = sample_width
        self._is_capturing = False
        self._audio_buffer = bytearray()
        self._rolling_buffer = bytearray()
        self._done = False

        self._bytes_per_ms = self._sample_rate * self._sample_width / 1000

        logger.info(
            "WakeWordDetector: sample_rate=%d, sample_width=%d, "
            "bytes_per_ms=%.1f, "
            "_ROLLING_BUFFER_BYTES=%d (%.0f ms), "
            "_MIN_AUDIO_BYTES=%d (%.0f ms), "
            "_MAX_CAPTURE_BYTES=%d (%.0f ms)",
            self._sample_rate, self._sample_width,
            self._bytes_per_ms,
            self._ROLLING_BUFFER_BYTES,
            self._ROLLING_BUFFER_BYTES / self._bytes_per_ms,
            self._MIN_AUDIO_BYTES,
            self._MIN_AUDIO_BYTES / self._bytes_per_ms,
            self._MAX_CAPTURE_BYTES,
            self._MAX_CAPTURE_BYTES / self._bytes_per_ms,
        )

        # Local Vosk detector — entirely offline
        self._local_detector = LocalWakeWordDetector()

        self._vad = VAD(
            on_speech_started=self._on_speech_started,
            on_speech_ended=self._on_speech_ended,
        )

    def reset(self) -> None:
        """Reset detector state so it can be reused after a wake word is detected."""
        self._done = False
        self._is_capturing = False
        self._audio_buffer = bytearray()
        self._rolling_buffer = bytearray()
        self._vad.reset()
        logger.info("WakeWordDetector reset")

    def process_audio(self, audio_chunk: bytes) -> None:
        """Process an audio chunk: update rolling buffer, capture if speaking, feed VAD."""
        if self._done:
            return

        self._rolling_buffer.extend(audio_chunk)
        if len(self._rolling_buffer) > self._ROLLING_BUFFER_BYTES:
            self._rolling_buffer = self._rolling_buffer[-self._ROLLING_BUFFER_BYTES:]

        if self._is_capturing:
            self._audio_buffer.extend(audio_chunk)
            if len(self._audio_buffer) >= self._MAX_CAPTURE_BYTES:
                logger.debug("Max capture buffer reached, force-flushing")
                self._flush_and_keep_capturing()

        self._vad.process_audio(audio_chunk)

    def _flush_and_keep_capturing(self) -> None:
        """Force-check the current buffer without waiting for VAD speech_end."""
        if self._done:
            return
        snapshot = bytes(self._audio_buffer)
        if len(snapshot) < self._MIN_AUDIO_BYTES:
            return
        _log_segment(snapshot, self._bytes_per_ms, "force-flush")
        try:
            wake_found = self._local_detector.contains_wake_word(
                snapshot, self._sample_rate,
            )
        except Exception as exc:
            logger.error("contains_wake_word failed in force-flush: %s", exc, exc_info=True)
            self._audio_buffer = bytearray()
            return
        if wake_found:
            self._done = True
            logger.info("Wake word detected via force-flush (%d bytes, %.0f ms)",
                       len(snapshot),
                       len(snapshot) / self._bytes_per_ms)
            import speech_recognition as sr
            audio_data = sr.AudioData(
                snapshot, self._sample_rate, self._sample_width,
            )
            try:
                self._on_wake_word_detected(audio_data)
            except Exception as exc:
                logger.error("_on_wake_word_detected callback failed: %s", exc, exc_info=True)
        else:
            logger.debug("Force-flush: wake word not found (%d bytes)", len(snapshot))
            self._audio_buffer = bytearray()

    def _on_speech_started(self) -> None:
        """VAD callback: start capturing, prepend pre-trigger audio."""
        try:
            if self._done:
                return
            self._is_capturing = True
            self._audio_buffer = bytearray(self._rolling_buffer)
            logger.debug(
                "Speech started, rolling_buffer=%d bytes (%.0f ms)",
                len(self._rolling_buffer),
                len(self._rolling_buffer) / self._bytes_per_ms,
            )
            logger.info("Speech started")
        except Exception as exc:
            logger.error("_on_speech_started failed: %s", exc, exc_info=True)

    def _on_speech_ended(self) -> None:
        """VAD callback: stop capturing, check locally for wake phrase."""
        if self._done:
            return
        self._is_capturing = False
        if len(self._audio_buffer) < self._MIN_AUDIO_BYTES:
            logger.debug(
                "Speech ended but buffer too small: %d bytes (%.0f ms < %.0f ms min)",
                len(self._audio_buffer),
                len(self._audio_buffer) / self._bytes_per_ms,
                self._MIN_AUDIO_BYTES / self._bytes_per_ms,
            )
            self._audio_buffer = bytearray()
            return

        buf_bytes = bytes(self._audio_buffer)
        _log_segment(buf_bytes, self._bytes_per_ms, "VAD speech end")

        # Transcribe locally via Vosk — no cloud call.
        try:
            wake_found = self._local_detector.contains_wake_word(
                buf_bytes, self._sample_rate,
            )
        except Exception as exc:
            logger.error("contains_wake_word failed in speech end: %s", exc, exc_info=True)
            self._audio_buffer = bytearray()
            return

        if wake_found:
            self._done = True
            logger.info(
                "Wake word detected via VAD speech end (%d bytes, %.0f ms)",
                len(buf_bytes),
                len(buf_bytes) / self._bytes_per_ms,
            )

            import speech_recognition as sr

            audio_data = sr.AudioData(
                bytes(self._audio_buffer),
                self._sample_rate,
                self._sample_width,
            )
            try:
                self._on_wake_word_detected(audio_data)
            except Exception as exc:
                logger.error("_on_wake_word_detected callback failed: %s", exc, exc_info=True)
        else:
            logger.debug("VAD speech end: wake word not found (%d bytes)", len(self._audio_buffer))

        self._audio_buffer = bytearray()
        logger.info("Speech ended")


def _log_segment(audio_bytes: bytes, bytes_per_ms: float, tag: str) -> None:
    """Log detailed segment info for debugging clipped audio."""
    total_ms = len(audio_bytes) / bytes_per_ms

    first_500_preserved = len(audio_bytes) >= 500 * bytes_per_ms
    last_500_preserved = len(audio_bytes) >= 500 * bytes_per_ms
    # Offset to start of last 500ms in the buffer
    last_500_offset = max(0, len(audio_bytes) - int(500 * bytes_per_ms))

    logger.info(
        "[%s] total_bytes=%d, total_duration=%.0f ms, "
        "first_500ms_preserved=%s (offset=0), "
        "last_500ms_preserved=%s (offset=%d bytes = %.0f ms from end)",
        tag,
        len(audio_bytes),
        total_ms,
        first_500_preserved,
        last_500_preserved,
        last_500_offset,
        last_500_offset / bytes_per_ms,
    )
