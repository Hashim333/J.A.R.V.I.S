"""
voice/local_wake_word.py

Local "jarvis" detection using Vosk offline speech recognition.
No cloud calls — every speech segment is transcribed locally.
Only segments confirmed to contain the wake phrase are forwarded
for cloud transcription.
"""

from __future__ import annotations

import json
import logging
import time
import audioop

import vosk

logger = logging.getLogger(__name__)


class LocalWakeWordDetector:
    """
    Transcribes captured audio locally via Vosk and reports whether the
    wake phrase ("jarvis") is present.

    The Vosk model is loaded once and shared across all detection calls.
    """

    _WAKE_PHRASE = "jarvis"
    _VOSK_SAMPLE_RATE = 16000
    _SAMPLE_WIDTH = 2
    _CHANNELS = 1

    def __init__(self) -> None:
        self._model = vosk.Model(lang="en-us")

    @staticmethod
    def _ensure_16khz(audio_bytes: bytes, source_rate: int) -> bytes:
        if source_rate != LocalWakeWordDetector._VOSK_SAMPLE_RATE:
            result_bytes, _ = audioop.ratecv(
                audio_bytes,
                LocalWakeWordDetector._SAMPLE_WIDTH,
                LocalWakeWordDetector._CHANNELS,
                source_rate,
                LocalWakeWordDetector._VOSK_SAMPLE_RATE,
                None,
            )
            return result_bytes

        return audio_bytes

    def contains_wake_word(self, audio_bytes: bytes, sample_rate: int = 16000) -> bool:
        try:
            duration_ms = (
                len(audio_bytes) / (sample_rate * self._SAMPLE_WIDTH) * 1000
            )
            logger.debug(
                "contains_wake_word: audio_bytes=%d, sample_rate=%d, "
                "channels=%d, sample_width=%d bytes, bytes_per_second=%d, "
                "expected_duration=%.0f ms",
                len(audio_bytes), sample_rate, self._CHANNELS, self._SAMPLE_WIDTH,
                sample_rate * self._SAMPLE_WIDTH * self._CHANNELS, duration_ms,
            )

            if duration_ms < 200:
                logger.warning(
                    "Audio duration (%.0f ms) is very short — "
                    "Vosk may not produce meaningful results",
                    duration_ms,
                )

            bytes_per_ms = sample_rate * self._SAMPLE_WIDTH / 1000
            first_500_bytes = min(len(audio_bytes), int(500 * bytes_per_ms))
            last_500_bytes_start = max(0, len(audio_bytes) - int(500 * bytes_per_ms))
            first_500_preserved = duration_ms >= 500.0
            last_500_preserved = duration_ms >= 500.0
            pcm_bytes = self._ensure_16khz(audio_bytes, sample_rate)

            recognizer = vosk.KaldiRecognizer(self._model, self._VOSK_SAMPLE_RATE, '["jarvis"]')
            start_ns = time.perf_counter_ns()
            recognizer.AcceptWaveform(pcm_bytes)
            result = json.loads(recognizer.FinalResult())
            text = result.get("text", "").casefold()
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1e6

            logger.debug("Vosk heard: %r (%.1f ms for %d bytes)",
                         text, elapsed_ms, len(pcm_bytes))

            # Accept the wake phrase when it leads the utterance — this is
            # what lets a single "jarvis, open chrome" count as a full
            # command (wake + command) instead of needing a second wake.
            # Partial matches, "[unk]", and empty text are still rejected.
            tokens = text.split()
            if not tokens or "[unk]" in tokens:
                logger.debug(
                    "contains_wake_word REJECT: tokens=%r (empty or [unk])",
                    tokens,
                )
                return False
            matched = "jarvis" in tokens[:2]
            logger.debug(
                "contains_wake_word DECISION: matched=%s tokens=%r",
                matched, tokens,
            )
            return matched
        except Exception as exc:
            logger.error("Vosk recognition failed: %s", exc, exc_info=True)
            return False
