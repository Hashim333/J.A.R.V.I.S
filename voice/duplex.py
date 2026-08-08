"""
voice/duplex.py

``DuplexVoiceSession`` — the full-duplex voice coordinator.

The microphone runs continuously; this session owns the *single* audio
consumer and routes every chunk through:

    raw mic  ->  echo canceller  ->  RNNoise stage (noise reduction)
                ->  { wake-word detector, capture VAD + Whisper STT,
                      barge-in VAD }

All three downstream taps consume the **echo-cancelled, noise-reduced**
signal, which is what makes the redesign work:

  * JARVIS's own TTS is cancelled against its playback reference, so it
    cannot trigger wake, barge-in, or phantom commands,
  * YouTube/Spotify/system audio is suppressed by the RNNoise stage (the
    adaptive FFT suppressor when native RNNoise is unavailable) and rarely
    passes the dynamic Silero VAD,
  * barge-in is *instant*: the moment real user speech is detected while
    TTS is playing, playback stops and the interrupted sentence is captured
    as the next command (no wake word needed again),
  * partial transcripts are produced live and the final text is
    only accepted above a confidence threshold; low-confidence results are
    returned with a rejection reason so the caller can ask the user to
    repeat instead of acting on (or giving up on) the audio,

The STT engine is Faster-Whisper (``WhisperRecognizer``) running on the
echo-cancelled, noise-reduced capture signal.

The public capture API is blocking (``capture_command``) and driven from
the backend loop, while ``process_chunk`` runs on the microphone capture
thread.  They communicate over a bounded event queue, so the design slots
into the existing run.py backend loop without a polling re-architecture.

Voice modules only capture audio.  This session NEVER changes conversation
state — the conversation owner (``services.conversation_owner``) is the
single owner of Wake/Listening/Thinking/Speaking/Sleep.
"""
from __future__ import annotations

import collections
import logging
import queue
import threading
import time
from typing import Callable, Optional

from voice.echo_canceller import EchoCanceller
from voice.rnnoise_stage import RNNoiseStage
from voice.silero_vad import SileroVAD
from voice.streaming_stt import FinalTranscript
from voice.synonym_engine import SynonymEngine
from voice.whisper_stt import WhisperRecognizer

logger = logging.getLogger(__name__)

# ~800 ms of noise-suppressed pre-roll so the first word after "Yes?" (or
# the first word of an interruption) is never lost.
_PREROLL_BYTES = 800 * 16000 * 2 // 1000

# Cap how long a single capture can run regardless of caller timeout.
_MAX_CAPTURE_SECONDS = 30.0


class CaptureResult:
    """Outcome of a streaming capture."""

    __slots__ = (
        "text", "confidence", "accepted", "reason", "duration_ms",
        "raw_text", "canonical_text", "pass_used", "recognition_ms",
        "speech_seconds",
    )

    def __init__(
        self,
        text: str,
        confidence: float,
        accepted: bool,
        reason: str = "",
        duration_ms: float = 0.0,
        raw_text: str = "",
        canonical_text: str = "",
        pass_used: str = "",
        recognition_ms: float = 0.0,
        speech_seconds: float = 0.0,
    ) -> None:
        self.text = text
        self.confidence = confidence
        self.accepted = accepted
        self.reason = reason
        self.duration_ms = duration_ms
        self.raw_text = raw_text
        self.canonical_text = canonical_text
        self.pass_used = pass_used
        self.recognition_ms = recognition_ms
        self.speech_seconds = speech_seconds

    @property
    def success(self) -> bool:
        return self.accepted and bool(self.text and self.text.strip())

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"CaptureResult(text={self.text!r}, confidence={self.confidence:.3f}, "
            f"accepted={self.accepted}, reason={self.reason!r})"
        )


class DuplexVoiceSession:
    """
    Full-duplex voice coordinator.

    This session ONLY captures audio.  It never decides conversation state.

    Args:
        sample_rate: Pipeline sample rate (16 kHz mono 16-bit).
        echo_canceller: An ``EchoCanceller`` (default: auto-created).
        noise_reducer: A noise-reduction stage placed before STT (default:
            ``RNNoiseStage`` — native RNNoise when available, otherwise the
            adaptive FFT suppressor).
        noise_suppressor: Backward-compatible alias for ``noise_reducer``
            (kept so existing callers/injected DSPs keep working).
        transcriber: A transcriber exposing ``begin`` / ``push`` /
            ``partial_text`` / ``finalize`` / ``discard`` / ``reset``
            (default: ``WhisperRecognizer`` — Faster-Whisper).
        on_partial: Called (from the mic thread) with each partial transcript.
        on_wake_word: Called with the raw wake audio when "jarvis" is heard
            while Idle.
        on_barge_in: Called when real user speech interrupts JARVIS while
            speaking.
        confidence_threshold: Overrides the transcriber's acceptance gate.
        silence_hangover_ms: End-of-speech hangover for the capture VAD
            (pause tolerance — kept above one second so a natural pause is
            never mistaken for the end of the utterance).
        max_capture_timeout: Hard cap on a single ``capture_command``.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        echo_canceller: EchoCanceller | None = None,
        noise_reducer: object | None = None,
        noise_suppressor: object | None = None,
        transcriber: object | None = None,
        on_partial: Callable[[str], None] | None = None,
        on_wake_word: Callable[[object], None] | None = None,
        on_barge_in: Callable[[], None] | None = None,
        confidence_threshold: float | None = None,
        silence_hangover_ms: float = 2000.0,
        max_capture_timeout: float = _MAX_CAPTURE_SECONDS,
        capture_vad: object | None = None,
        barge_in_vad: object | None = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._echo_canceller = echo_canceller or EchoCanceller(sample_rate=sample_rate)
        # RNNoise stage (FFT fallback) owns the pre-STT noise reduction.
        self._noise_suppressor = (
            noise_reducer or noise_suppressor or RNNoiseStage(sample_rate=sample_rate)
        )
        self._transcriber = transcriber or WhisperRecognizer(sample_rate=sample_rate)
        if confidence_threshold is not None:
            self._transcriber._confidence_threshold = float(confidence_threshold)
        self.on_partial = on_partial
        self.on_wake_word = on_wake_word
        self.on_barge_in = on_barge_in
        self._max_capture_timeout = float(max_capture_timeout)

        # Capture VAD (Silero, WebRTC fallback) — pause-tolerant end-of-speech.
        self._capture_vad = capture_vad or SileroVAD(
            on_speech_started=self._on_capture_speech_started,
            on_speech_ended=self._on_capture_speech_ended,
            sample_rate=sample_rate,
            silence_hangover_ms=silence_hangover_ms,
            onset_frames=3,
        )
        # Barge-in VAD (echo-cancelled signal, so JARVIS cannot trigger it)
        self._barge_in_vad = barge_in_vad or SileroVAD(
            on_speech_started=self._on_barge_in_onset,
            on_speech_ended=lambda: None,
            sample_rate=sample_rate,
            silence_hangover_ms=300.0,
            min_speech_ms=120.0,
            onset_frames=3,
        )
        self._barge_in_armed = False

        # Last noise floor applied to the VADs (throttled adaptation) so a
        # steady background (fan / AC / TV) cannot trigger speech onset.
        self._last_noise_floor_applied = 0.0
        self._last_noise_floor_at = 0.0

        # Wake word detector is created lazily so this module imports even
        # when the local Vosk model is unavailable.
        self._wake_detector = None
        self._wake_armed = False

        # State shared between the mic thread and the backend thread.
        self._in_capture = False
        self._capture_deadline = 0.0
        self._events: queue.Queue = queue.Queue(maxsize=64)
        self._lock = threading.RLock()

        # Pre-roll ring buffer of the most recent noise-suppressed audio.
        self._preroll = collections.deque()
        self._preroll_bytes = 0

        # Playback reference resampling (TTS rate -> pipeline rate).
        self._ref_resampler = None
        self._last_ref_chunk = b""

    # ------------------------------------------------------------------
    # Microphone feed (runs on the capture thread)
    # ------------------------------------------------------------------

    def process_chunk(self, mic_chunk: bytes) -> None:
        """Consume a raw 16-bit PCM mic chunk.  Called by MicrophoneStream."""
        if not mic_chunk:
            return
        logger.debug(
            "process_chunk ENTRY: chunk_bytes=%d wake_armed=%s "
            "in_capture=%s barge_in_armed=%s",
            len(mic_chunk), self._wake_armed, self._in_capture,
            self._barge_in_armed,
        )
        try:
            cancelled = self._echo_canceller.process(mic_chunk)
            clean = self._noise_suppressor.process(cancelled)
        except Exception as exc:
            logger.error("Duplex processing failed: %s", exc, exc_info=True)
            return

        self._append_preroll(clean)

        self._adapt_vad_noise_floor()

        if self._wake_armed and self._wake_detector is not None:
            try:
                self._wake_detector.process_audio(clean)
            except Exception as exc:
                logger.error("Wake detector failed: %s", exc, exc_info=True)

        if self._in_capture:
            self._feed_capture(clean)

        if self._barge_in_armed:
            try:
                self._barge_in_vad.process_audio(clean)
            except Exception as exc:
                logger.error("Barge-in VAD failed: %s", exc, exc_info=True)

    def _append_preroll(self, clean: bytes) -> None:
        with self._lock:
            self._preroll.append(clean)
            self._preroll_bytes += len(clean)
            while self._preroll_bytes > _PREROLL_BYTES and self._preroll:
                dropped = self._preroll.popleft()
                self._preroll_bytes -= len(dropped)

    def _adapt_vad_noise_floor(self) -> None:
        """Tune the capture/barge-in VADs to the live ambient noise floor.

        Steady background noise (fan, AC, TV, system audio) raises the VAD
        aggressiveness and onset requirement, so it cannot be mistaken for
        the user starting to speak; a quiet room stays maximally sensitive.
        The re-tune is throttled so we never thrash the WebRTC VAD mid-capture.
        """
        suppressor = self._noise_suppressor
        if suppressor is None:
            return
        if not getattr(suppressor, "initialized", False):
            return
        try:
            nf = suppressor.noise_floor
        except Exception:
            return
        now = time.monotonic()
        if now - self._last_noise_floor_at < 2.0:
            return
        if abs(nf - self._last_noise_floor_applied) < 0.05 * max(nf, 1e-6):
            return
        self._last_noise_floor_at = now
        self._last_noise_floor_applied = nf
        try:
            self._capture_vad.set_noise_floor(nf)
            self._barge_in_vad.set_noise_floor(nf)
        except Exception as exc:
            logger.error("VAD noise floor adaptation failed: %s", exc)

    def _feed_capture(self, clean: bytes) -> None:
        try:
            self._capture_vad.process_audio(clean)
        except Exception as exc:
            logger.error("Capture VAD failed: %s", exc, exc_info=True)
        try:
            partial = self._transcriber.push(clean)
            if partial:
                self._emit(("partial", partial))
                if self.on_partial:
                    try:
                        self.on_partial(partial)
                    except Exception as exc:
                        logger.error("on_partial callback failed: %s", exc)
        except Exception as exc:
            logger.error("Streaming STT push failed: %s", exc, exc_info=True)

    def _emit(self, event) -> None:
        try:
            self._events.put_nowait(event)
        except queue.Full:
            # Backend is slow; drop the oldest event and keep the newest.
            try:
                self._events.get_nowait()
            except queue.Empty:
                pass
            try:
                self._events.put_nowait(event)
            except queue.Full:
                pass

    # ------------------------------------------------------------------
    # Playback reference (called from the TTS player thread)
    # ------------------------------------------------------------------

    def feed_playback_reference(self, pcm_chunk: bytes, sample_rate: int = 22050) -> None:
        """Feed the exact PCM the player wrote to the speakers."""
        if not pcm_chunk or len(pcm_chunk) % 2 != 0:
            return
        rate = int(sample_rate) if sample_rate else 22050
        if rate != self._sample_rate:
            import audioop

            try:
                pcm_chunk, self._ref_resampler = audioop.ratecv(
                    pcm_chunk, 2, 1, rate, self._sample_rate, self._ref_resampler,
                )
            except Exception:
                return
        self._echo_canceller.set_reference(pcm_chunk)

    # ------------------------------------------------------------------
    # Wake-word control
    # ------------------------------------------------------------------

    def _ensure_wake_detector(self) -> None:
        if self._wake_detector is not None:
            return
        from voice.wakeword import WakeWordDetector

        self._wake_detector = WakeWordDetector(
            on_wake_word_detected=self._on_wake_word_detected,
            sample_rate=self._sample_rate,
        )

    def start_wake_detection(self) -> None:
        """Begin listening for the wake phrase (when Idle)."""
        self._ensure_wake_detector()
        self._wake_armed = True

    def stop_wake_detection(self) -> None:
        self._wake_armed = False

    def reset_wake(self) -> None:
        self._ensure_wake_detector()
        self._wake_detector.reset()

    def _on_wake_word_detected(self, audio_data: object) -> None:
        """Wake phrase heard.  If barge-in is armed, treat it as barge-in."""
        if self._barge_in_armed:
            logger.info("Wake word heard while speaking -> barge-in")
            self._trigger_barge_in()
            return
        if self.on_wake_word:
            logger.debug(
                "Wake word confirmed -> forwarding to on_wake_word",
            )
            try:
                self.on_wake_word(audio_data)
            except Exception as exc:
                logger.error("on_wake_word callback failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Barge-in control
    # ------------------------------------------------------------------

    def arm_barge_in(self) -> None:
        """Arm instant barge-in detection while TTS is speaking."""
        self._barge_in_armed = True
        self._barge_in_vad.reset()

    def disarm_barge_in(self) -> None:
        self._barge_in_armed = False
        self._barge_in_vad.reset()

    def _on_barge_in_onset(self) -> None:
        """Real (echo-cancelled) user speech while JARVIS is speaking."""
        if not self._barge_in_armed:
            return
        self._trigger_barge_in()

    def _trigger_barge_in(self) -> None:
        if not self._barge_in_armed:
            return
        self._barge_in_armed = False
        self._barge_in_vad.reset()
        if self.on_barge_in:
            try:
                self.on_barge_in()
            except Exception as exc:
                logger.error("on_barge_in callback failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Capture (blocking, backend-loop thread)
    # ------------------------------------------------------------------

    def _on_capture_speech_started(self) -> None:
        logger.info("SPEECH DETECTED (capture VAD onset)")
        self._emit(("speech_start", time.monotonic()))

    def _on_capture_speech_ended(self) -> None:
        logger.info("SPEECH ENDED (capture VAD silence hangover / max utterance)")
        self._emit(("speech_end", time.monotonic()))

    def _preroll_bytes_all(self) -> bytes:
        return b"".join(self._preroll) if self._preroll else b""

    def capture_command(
        self,
        timeout: float = _MAX_CAPTURE_SECONDS,
        on_partial: Callable[[str], None] | None = None,
    ) -> CaptureResult:
        """
        Two-phase streaming capture of one command.

        Phase A (idle wait): never assume the user is silent — wait until the
        capture VAD actually detects speech onset.  The idle timeout bounds
        only this phase (default 30 s), so a long pause after the wake prompt
        never cuts the user off; the timer starts on speech, not on wake.

        Phase B (speech): once speech starts, keep recording until the VAD
        reports the utterance really ended (pause-tolerant hangover) or the
        hard per-utterance cap is reached.  The user is never cut off mid-word.

        The result carries a machine-readable ``reason``:
          ""                        accepted command
          "no_speech"               nothing heard within the idle timeout
          "low confidence" / "too short" / "no speech recognized"
                                    audio was recognised but rejected by the
                                    confidence gate (do NOT execute — ask to
                                    repeat instead of showing NO_COMMAND)
          "cancelled"               capture aborted via cancel_capture()
        """
        timeout = max(0.0, min(float(timeout), self._max_capture_timeout))
        logger.info(
            "Recording started (capture_command, idle_timeout=%.1fs, "
            "max_capture=%.1fs)",
            timeout, self._max_capture_timeout,
        )

        with self._lock:
            # Drop stale events from any previous capture (events are only
            # produced while ``_in_capture`` is True, so this is race-free).
            self._drain_events()
            self._in_capture = True
            self._capture_vad.reset()
            self._transcriber.begin()
            # Seed with the pre-roll so the first word is never lost.
            preroll = self._preroll_bytes_all()
            if preroll:
                try:
                    self._capture_vad.process_audio(preroll)
                    self._transcriber.push(preroll)
                except Exception as exc:
                    logger.error("Pre-roll seeding failed: %s", exc)

        try:
            # ---- Phase A: wait for real speech onset ----
            idle_deadline = time.monotonic() + timeout
            speech_started_at: float | None = None
            while speech_started_at is None:
                remaining = idle_deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    event = self._events.get(timeout=min(remaining, 0.2))
                except queue.Empty:
                    partial = self._safe_partial()
                    if partial and on_partial:
                        try:
                            on_partial(partial)
                        except Exception:
                            pass
                    continue
                kind = event[0]
                if kind == "partial":
                    text = event[1]
                    if on_partial:
                        try:
                            on_partial(text)
                        except Exception:
                            pass
                elif kind == "speech_start":
                    speech_started_at = event[1]
                    logger.info(
                        "SPEECH DETECTED at t=%.3fs — beginning capture",
                        speech_started_at,
                    )
                elif kind == "cancelled":
                    logger.info("Capture cancelled while waiting for speech")
                    return CaptureResult("", 0.0, False, reason="cancelled", duration_ms=0.0)
                # speech_end without an onset (e.g. seeded pre-roll) — ignore.

            if speech_started_at is None:
                logger.info(
                    "CAPTURE IDLE TIMEOUT after %.1fs — no speech detected",
                    timeout,
                )
                return CaptureResult("", 0.0, False, reason="no_speech", duration_ms=0.0)

            # ---- Phase B: record until the utterance really ends ----
            speech_deadline = speech_started_at + self._max_capture_timeout
            speech_ended_at: float | None = None
            while True:
                remaining = speech_deadline - time.monotonic()
                if remaining <= 0:
                    logger.info(
                        "CAPTURE MAX UTTERANCE reached after %.1fs — finalizing",
                        self._max_capture_timeout,
                    )
                    break
                try:
                    event = self._events.get(timeout=min(remaining, 0.2))
                except queue.Empty:
                    partial = self._safe_partial()
                    if partial and on_partial:
                        try:
                            on_partial(partial)
                        except Exception:
                            pass
                    continue
                kind = event[0]
                if kind == "partial":
                    text = event[1]
                    if on_partial:
                        try:
                            on_partial(text)
                        except Exception:
                            pass
                elif kind in ("speech_end", "speech_max"):
                    logger.info("SPEECH ENDED at t=%.3fs — finalizing", event[1])
                    speech_ended_at = event[1]
                    final = self._finalize_capture()
                    if final is None:
                        continue
                    return self._final_to_result(final, speech_ended_at, speech_started_at)
                elif kind == "cancelled":
                    logger.info("Capture cancelled during speech")
                    return CaptureResult("", 0.0, False, reason="cancelled", duration_ms=0.0)

            # Deadline reached without a VAD boundary: finalize what we have.
            final = self._finalize_capture()
            if final is not None:
                return self._final_to_result(final, speech_ended_at, speech_started_at)
            return CaptureResult("", 0.0, False, reason="speech_timeout", duration_ms=0.0)
        finally:
            with self._lock:
                self._in_capture = False
            logger.info("Recording stopped (capture_command)")

    def _drain_events(self) -> None:
        """Remove every event currently queued (called at capture start)."""
        try:
            while True:
                self._events.get_nowait()
        except queue.Empty:
            pass

    def _safe_partial(self) -> str:
        try:
            return self._transcriber.partial_text()
        except Exception:
            return ""

    def _finalize_capture(self) -> FinalTranscript | None:
        try:
            return self._transcriber.finalize()
        except Exception as exc:
            logger.error("Transcriber finalize failed: %s", exc, exc_info=True)
            return None

    def _final_to_result(self, final: FinalTranscript, speech_ended_at: float | None = None, speech_started_at: float | None = None) -> CaptureResult:
        """Log the recognition outcome, then wrap it as a CaptureResult.

        The synonym engine canonicalises the accepted text (e.g. "start music"
        -> "play music") so the intent parser always sees one canonical form;
        the raw text is preserved for internal comparison.  ``recognition_ms``
        measures Speech End -> Recognition Finished (latency stage 2).
        """
        raw_text = final.text
        pass_used = final.pass_used
        canonical_text = ""
        text = raw_text

        if final.accepted and raw_text:
            canonical = SynonymEngine.canonicalize(raw_text)
            if canonical.changed:
                text = canonical.text
                canonical_text = canonical.text
                logger.info(
                    "SYNONYM — raw=%r canonical=%r changes=%r",
                    raw_text, canonical.text, canonical.changes,
                )

        recognition_ms = 0.0
        speech_seconds = 0.0
        if speech_ended_at is not None:
            recognition_ms = (time.monotonic() - speech_ended_at) * 1000.0
        if speech_ended_at is not None and speech_started_at is not None:
            speech_seconds = max(0.0, speech_ended_at - speech_started_at)

        result = CaptureResult(
            text,
            final.confidence,
            final.accepted,
            reason="" if final.accepted else final.rejected_reason,
            duration_ms=final.duration_ms,
            raw_text=raw_text,
            canonical_text=canonical_text,
            pass_used=pass_used,
            recognition_ms=recognition_ms,
            speech_seconds=speech_seconds,
        )
        logger.info(
            "RECOGNITION FINAL — text=%r confidence=%.3f accepted=%s reason=%r "
            "pass=%s",
            final.text, final.confidence, final.accepted, final.rejected_reason or "",
            final.pass_used,
        )
        if speech_ended_at is not None:
            logger.info(
                "LATENCY stage=speech_end->recognition %.0f ms (text=%r pass=%s)",
                recognition_ms, raw_text, final.pass_used,
            )
        if not final.accepted:
            logger.info(
                "REASON REJECTED: %s (text=%r confidence=%.3f)",
                final.rejected_reason, final.text, final.confidence,
            )
        return result

    # ------------------------------------------------------------------
    # Capture cancellation (called by the conversation owner)
    # ------------------------------------------------------------------

    def cancel_capture(self) -> None:
        """Abort an in-progress capture (e.g. shutdown / new command)."""
        with self._lock:
            self._in_capture = False
        self._transcriber.discard()
        self._emit(("cancelled", time.monotonic()))

    # ------------------------------------------------------------------
    # State access
    # ------------------------------------------------------------------

    @property
    def echo_canceller(self) -> EchoCanceller:
        return self._echo_canceller

    @property
    def noise_suppressor(self) -> RNNoiseStage:
        """The pre-STT noise-reduction stage (RNNoise or FFT fallback)."""
        return self._noise_suppressor