"""
voice/pipeline/audio.py

``AudioCapture`` — owns the live microphone and the DSP chain for the new
conversational pipeline.

Every chunk read from the microphone passes through:

    raw mic  ->  echo canceller (NLMS, reference-based)
             ->  adaptive noise suppressor (spectral min-tracking)
             ->  AGC / noise gate (MicrophoneProcessor)

so the wake detector, VAD, and ASR all consume a signal where JARVIS's own
TTS, YouTube/Spotify/system audio are suppressed — only genuine user speech
survives.  The ``FeedSession`` below routes that clean signal to whichever
consumers are armed for the current state (wake vs capture).

This is a standalone module: it composes the existing building blocks
(:class:`MicrophoneStream`, :class:`EchoCanceller`, :class:`NoiseSuppressor`,
:class:`MicrophoneProcessor`) and does not depend on the old
``DuplexVoiceSession``.
"""
from __future__ import annotations

import logging
from typing import Callable

from voice.microphone_stream import MicrophoneStream
from voice.echo_canceller import EchoCanceller
from voice.noise_suppressor import NoiseSuppressor

logger = logging.getLogger(__name__)


class AudioCapture:
    """Owns the mic stream and routes the cleaned signal to consumers.

    Args:
        sample_rate: Pipeline sample rate (16 kHz mono 16-bit).
        microphone_stream: The continuous stream (injected in tests).
        echo_canceller: NLMS canceller (default: auto-created).
        noise_suppressor: Spectral suppressor (default: auto-created).
        processor: AGC / noise-gate processor attached to the stream.
        on_clean_chunk: Called (on the mic thread) with each *cleaned* chunk
            before state routing, for live level meters / debugging.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        microphone_stream: MicrophoneStream | None = None,
        echo_canceller: EchoCanceller | None = None,
        noise_suppressor: NoiseSuppressor | None = None,
        processor=None,
        on_clean_chunk: Callable[[bytes], None] | None = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._stream = microphone_stream or MicrophoneStream(
            chunk_size=1024, sample_rate=sample_rate
        )
        self._echo_canceller = echo_canceller or EchoCanceller(sample_rate=sample_rate)
        self._noise_suppressor = noise_suppressor or NoiseSuppressor(sample_rate=sample_rate)
        self._processor = processor
        self._on_clean_chunk = on_clean_chunk
        self._session: "FeedSession | None" = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_session(self, session: "FeedSession | None") -> None:
        """Route the cleaned signal to *session* (a FeedSession)."""
        self._session = session

    def start(self) -> None:
        if self._processor is not None:
            self._stream.set_processor(self._processor)
        self._stream.set_consumer(self._process)
        self._stream.start()

    def shutdown(self) -> None:
        self._stream.set_consumer(None)
        self._stream.shutdown()

    def mute(self) -> None:
        self._stream.mute()

    def unmute(self) -> None:
        self._stream.unmute()

    @property
    def stream(self) -> MicrophoneStream:
        return self._stream

    @property
    def echo_canceller(self) -> EchoCanceller:
        return self._echo_canceller

    # ------------------------------------------------------------------
    # Mic-thread feed
    # ------------------------------------------------------------------

    def feed_mic_chunk(self, mic_chunk: bytes) -> None:
        """Public entry point for a raw mic chunk (used by the facade)."""
        self._process(mic_chunk)

    def _process(self, mic_chunk: bytes) -> None:
        if not mic_chunk:
            return
        try:
            cancelled = self._echo_canceller.process(mic_chunk)
            clean = self._noise_suppressor.process(cancelled)
        except Exception as exc:
            logger.error("AudioCapture DSP failed: %s", exc, exc_info=True)
            return
        if self._on_clean_chunk is not None:
            try:
                self._on_clean_chunk(clean)
            except Exception as exc:
                logger.error("AudioCapture on_clean_chunk failed: %s", exc, exc_info=True)
        session = self._session
        if session is not None:
            session.feed(clean)

    # ------------------------------------------------------------------
    # Echo reference from TTS playback
    # ------------------------------------------------------------------

    def feed_playback_reference(self, pcm_chunk: bytes, sample_rate: int = 22050) -> None:
        """Feed the exact PCM the TTS player wrote to the speakers.

        Called from the player thread so JARVIS's own voice is cancelled from
        the mic instead of being muted (which would block instant barge-in).
        """
        if not pcm_chunk or len(pcm_chunk) % 2 != 0:
            return
        if sample_rate and sample_rate != self._sample_rate:
            import audioop

            try:
                pcm_chunk, self._ref_resampler = audioop.ratecv(
                    pcm_chunk, 2, 1, sample_rate, self._sample_rate, getattr(
                        self, "_ref_resampler", None
                    ),
                )
            except Exception:
                return
        try:
            self._echo_canceller.set_reference(pcm_chunk)
        except Exception as exc:
            logger.error("AudioCapture set_reference failed: %s", exc, exc_info=True)


class FeedSession:
    """Receives the cleaned mic signal (see :class:`AudioCapture`).

    A session decides per-state where the audio goes — e.g. forward to the
    wake detector while sleeping, or to the capture VAD/ASR while listening.
    """

    def feed(self, clean_chunk: bytes) -> None:
        raise NotImplementedError  # pragma: no cover - abstract