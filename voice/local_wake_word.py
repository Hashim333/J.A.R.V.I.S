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
        input_duration_ms = (
            len(audio_bytes)
            / (source_rate * LocalWakeWordDetector._SAMPLE_WIDTH)
            * 1000
        )
        if source_rate == LocalWakeWordDetector._VOSK_SAMPLE_RATE:
            logger.info(
                "Vosk PCM input already normalized: sample_rate=%d Hz, "
                "channels=%d, sample_width=%d bytes, bytes=%d, "
                "expected_duration=%.0f ms, bytes_per_second=%d",
                source_rate,
                LocalWakeWordDetector._CHANNELS,
                LocalWakeWordDetector._SAMPLE_WIDTH,
                len(audio_bytes),
                input_duration_ms,
                source_rate * LocalWakeWordDetector._SAMPLE_WIDTH,
            )
            return audio_bytes

        logger.warning(
            "Resampling Vosk PCM from %d Hz to %d Hz: channels=%d, "
            "sample_width=%d bytes, input=%d bytes, expected_duration=%.0f ms",
            source_rate,
            LocalWakeWordDetector._VOSK_SAMPLE_RATE,
            LocalWakeWordDetector._CHANNELS,
            LocalWakeWordDetector._SAMPLE_WIDTH,
            len(audio_bytes),
            input_duration_ms,
        )
        result_bytes, _ = audioop.ratecv(
            audio_bytes,
            LocalWakeWordDetector._SAMPLE_WIDTH,
            LocalWakeWordDetector._CHANNELS,
            source_rate,
            LocalWakeWordDetector._VOSK_SAMPLE_RATE,
            None,
        )
        output_duration_ms = (
            len(result_bytes)
            / (
                LocalWakeWordDetector._VOSK_SAMPLE_RATE
                * LocalWakeWordDetector._SAMPLE_WIDTH
            )
            * 1000
        )
        logger.info(
            "Resampled Vosk PCM: %d bytes -> %d bytes, "
            "expected_duration %.0f ms -> %.0f ms",
            len(audio_bytes),
            len(result_bytes),
            input_duration_ms,
            output_duration_ms,
        )
        return result_bytes

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

            # Log first/last 500ms preservation before any resampling
            bytes_per_ms = sample_rate * self._SAMPLE_WIDTH / 1000
            first_500_bytes = min(len(audio_bytes), int(500 * bytes_per_ms))
            last_500_bytes_start = max(0, len(audio_bytes) - int(500 * bytes_per_ms))
            first_500_preserved = duration_ms >= 500.0
            last_500_preserved = duration_ms >= 500.0
            logger.info(
                "Segment detail: total=%d bytes (%.0f ms), "
                "first_500ms=%s (%d bytes offset=0), "
                "last_500ms=%s (%d bytes offset=%d)",
                len(audio_bytes), duration_ms,
                first_500_preserved, first_500_bytes,
                last_500_preserved, int(500 * bytes_per_ms), last_500_bytes_start,
            )

            pcm_bytes = self._ensure_16khz(audio_bytes, sample_rate)
            vosk_duration_ms = (
                len(pcm_bytes)
                / (self._VOSK_SAMPLE_RATE * self._SAMPLE_WIDTH)
                * 1000
            )

            logger.info(
                "Vosk recognizer PCM: sample_rate=%d Hz, channels=%d, "
                "sample_width=%d bytes, bytes=%d, bytes_per_second=%d, "
                "expected_duration=%.0f ms",
                self._VOSK_SAMPLE_RATE,
                self._CHANNELS,
                self._SAMPLE_WIDTH,
                len(pcm_bytes),
                self._VOSK_SAMPLE_RATE * self._SAMPLE_WIDTH * self._CHANNELS,
                vosk_duration_ms,
            )

            recognizer = vosk.KaldiRecognizer(self._model, self._VOSK_SAMPLE_RATE)
            accepted = recognizer.AcceptWaveform(pcm_bytes)
            partial_text = ""
            if accepted:
                result_source = "Result"
                result = json.loads(recognizer.Result())
            else:
                result_source = "FinalResult"
                partial = json.loads(recognizer.PartialResult())
                partial_text = partial.get("partial", "").casefold()
                result = json.loads(recognizer.FinalResult())
            text = result.get("text", "").casefold()
            if not text and partial_text:
                text = partial_text

            logger.info(
                "Vosk heard: %r (accepted=%s, result_source=%s, "
                "partial=%r, audio: %d bytes, %.0f ms at %d Hz)",
                text, accepted, result_source, partial_text,
                len(pcm_bytes), vosk_duration_ms, self._VOSK_SAMPLE_RATE,
            )

            return self._WAKE_PHRASE in text
        except Exception as exc:
            logger.error("Vosk recognition failed: %s", exc, exc_info=True)
            return False
