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

import audioop
import collections
import logging
import queue
import threading
import time
from typing import Callable, Optional

from monitoring.turn_trace import mark as turn_mark, start_turn as turn_start
from voice.echo_canceller import EchoCanceller
from voice.rnnoise_stage import RNNoiseStage
from voice.silero_vad import SileroVAD
from voice.streaming_stt import FinalTranscript
from voice.synonym_engine import SynonymEngine
from voice.whisper_stt import WhisperRecognizer

logger = logging.getLogger(__name__)

# Keep a short noise-suppressed pre-roll so the onset detector does not clip
# the first phoneme. Longer pre-rolls can leak the previous utterance into
# the next command.
_PREROLL_BYTES = 1200 * 16000 * 2 // 1000
_CAPTURE_PREROLL_BYTES = 200 * 16000 * 2 // 1000

# Cap how long a single capture can run regardless of caller timeout.
# FIX-VOICE-003: reduced from 30s to 10s - any command longer than 10s is
# pathological and should be rejected.
_MAX_CAPTURE_SECONDS = 10.0

# PART 14: a capture callback (the inline ``on_partial`` on the microphone
# thread) must never stall mic capture.  If one invocation exceeds this
# ceiling we log it and stop invoking the callback inline — partials still
# reach the backend through the bounded event queue, so nothing is lost.
_MAX_PARTIAL_CALLBACK_SECONDS = 0.5

# PART 15: hard limit on the capture cleanup/exit path.  A Whisper decode in
# ``_finalize_capture`` must never wedge ``capture_command`` (and with it the
# conversation backend loop) — if the recognizer does not finish within this
# ceiling the capture exits with a timeout instead of blocking forever.
# VOICE-FIX: 12 s — matches the faster beam<=2 decode; a healthy short
# utterance finalizes in ~1 s, so 12 s is purely a wedge guard.
_MAX_FINALIZE_SECONDS = 12.0

# Pause-tolerant end-of-speech hangover. Brief mid-sentence pauses should not
# split one spoken command before Whisper receives the full utterance.
# VOICE-FIX: 900 ms — long enough to survive natural word gaps, short enough
# that a finished command finalizes promptly instead of idling.
_DEFAULT_SILENCE_HANGOVER_MS = 900.0

# FIX-VOICE-005: the shortest "utterance" we treat as speech.  A VAD onset
# shorter than this (e.g. a 0.03s click / rumble / pre-roll blip) is never
# sent to the recognizer — the capture is discarded and we keep listening.
_MIN_UTTERANCE_SECONDS = 0.25

# FIX 4: onset energy gate.  VAD frame-voting alone fires on loud clicks,
# clacks, and TTS-edge transients (observed: onsets at 93/312 ms idle_wait
# on room noise, followed by empty decodes).  An onset is only accepted
# when recent post-suppression audio carries real energy: peak RMS above
# an absolute floor OR clearly above the tracked background.  Both tests
# are energy-only and accent/language-independent — soft speech in a quiet
# room passes on the ratio clause, loud-room speech on the absolute clause;
# only flat low-level noise is rejected.
_ONSET_ENERGY_WINDOW = 12
_ONSET_MIN_RMS = 0.02
_ONSET_MIN_SNR = 4.0
_ONSET_MIN_CHUNKS = 4


class CaptureResult:
    """Outcome of a streaming capture.

    (FIX-003) ``word_confidences`` / ``sentence_confidences`` /
    ``min_word_confidence`` carry the per-word / per-sentence recognition
    confidence for the Speech Intelligence Layer, and ``idle_wait_ms`` is
    the time spent waiting for speech onset (Phase A) so end-to-end latency
    can be attributed.
    """

    __slots__ = (
        "text", "confidence", "accepted", "reason", "duration_ms",
        "raw_text", "canonical_text", "pass_used", "recognition_ms",
        "speech_seconds", "word_confidences", "sentence_confidences",
        "min_word_confidence", "idle_wait_ms",
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
        word_confidences: tuple[tuple[str, float], ...] = (),
        sentence_confidences: tuple[tuple[str, float], ...] = (),
        min_word_confidence: float | None = None,
        idle_wait_ms: float = 0.0,
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
        self.word_confidences = word_confidences
        self.sentence_confidences = sentence_confidences
        self.min_word_confidence = min_word_confidence
        self.idle_wait_ms = idle_wait_ms

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
            (pause tolerance — increased to 1500ms so natural pauses between
            words don't end the utterance prematurely).
        max_capture_timeout: Hard cap on a single ``capture_command``.
        capture_vad: Override VAD instance (for testing).
        barge_in_vad: Override barge-in VAD instance (for testing).
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
        silence_hangover_ms: float = _DEFAULT_SILENCE_HANGOVER_MS,
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
        # VOICE-PIPELINE-006: build the default transcriber WITHOUT the
        # background partial decoder.  That worker re-decodes the entire
        # growing capture buffer every partial_interval_ms (1.2 s) while
        # holding ``_decode_lock``; the authoritative ``finalize()`` must then
        # queue behind it, so under real CPU contention (VAD + RNNoise + echo
        # canceller on the mic thread) a single utterance can blow the
        # 20 s ``_MAX_FINALIZE_SECONDS`` window and be lost as speech_timeout.
        # With partials disabled each utterance is decoded exactly once, the
        # moment the VAD says speech ended.
        self._transcriber = transcriber or WhisperRecognizer(
            sample_rate=sample_rate, enable_partials=False,
        )
        if confidence_threshold is not None:
            self._transcriber._confidence_threshold = float(confidence_threshold)
        self.on_partial = on_partial
        self.on_wake_word = on_wake_word
        self.on_barge_in = on_barge_in
        self._max_capture_timeout = float(max_capture_timeout)

        # PART 14: clamp the inline capture callback on the mic thread.  One
        # overrun disables inline invocation (queue delivery continues); the
        # counter is exposed for diagnostics.
        self._partial_callback_overruns = 0

        # Capture VAD (Silero, WebRTC fallback) — fast end-of-speech detection.
        # FIX-VOICE-003: reduced default silence hangover to 600ms for fast
        # command completion. Natural pauses between words are handled by
        # the VAD's onset buffer, not the hangover.
        self._capture_vad = capture_vad or SileroVAD(
            on_speech_started=self._on_capture_speech_started,
            on_speech_ended=self._on_capture_speech_ended,
            sample_rate=sample_rate,
            silence_hangover_ms=silence_hangover_ms,
            onset_frames=5,
        )
        # Barge-in VAD (echo-cancelled signal, so JARVIS cannot trigger it).
        # VOICE-FIX: 200 ms minimum + 5-frame onset so residual TTS echo /
        # clicks cannot interrupt; real user speech (300 ms+) still fires
        # instantly.
        self._barge_in_vad = barge_in_vad or SileroVAD(
            on_speech_started=self._on_barge_in_onset,
            on_speech_ended=lambda: None,
            sample_rate=sample_rate,
            silence_hangover_ms=300.0,
            min_speech_ms=200.0,
            onset_frames=5,
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

        # FIX-NO-WAKE-ECHO: after a conversation returns to idle the wake
        # detector is re-armed.  Any residual echo still ringing from JARVIS's
        # own last utterance must drain before the detector starts listening
        # again — otherwise the first mic chunk after re-arm can contain a
        # wake-phrase tail and re-trigger instantly.  During the cooldown the
        # mic keeps flowing (capture/barge-in still work) but the wake detector
        # is not fed.
        self._wake_rearm_until = 0.0

        # State shared between the mic thread and the backend thread.
        self._in_capture = False
        self._capture_started = False
        self._capture_deadline = 0.0
        self._events: queue.Queue = queue.Queue(maxsize=64)
        self._lock = threading.RLock()

        # Capture generation: bumped at the start of every capture_command
        # so that a stale event (a late VAD onset/end, or a cancel issued
        # for a previous turn by task cleanup / watchdog recovery) can
        # never abort or corrupt the current turn.  Every speech/cancel
        # event carries the generation it was emitted for; the capture
        # loop only honours events tagged with its own generation.
        # Legacy 2-tuple events (external/test injection) are honoured
        # fail-open so direct queue injection keeps working.
        self._capture_gen = 0
        self._cancel_gen: int | None = None

        # Pre-roll ring buffer of the most recent noise-suppressed audio.
        self._preroll = collections.deque()
        self._preroll_bytes = 0

        # Recent post-suppression chunk RMS history for the onset energy
        # gate (FIX 4).  None/empty means "no audio observed yet" and the
        # gate fails open so direct event injection (tests) still works.
        self._onset_rms: collections.deque = collections.deque(
            maxlen=_ONSET_ENERGY_WINDOW
        )

        # Playback reference resampling (TTS rate -> pipeline rate).
        self._ref_resampler = None
        self._last_ref_chunk = b""

        # PART 7: echo-reference diagnostics (for the JARVIS_DIAG runtime
        # verification) — the echo canceller only cancels JARVIS's voice once
        # the TTS playback reference is actually being fed.
        self._reference_active = False
        self._last_ref_diag_at = 0.0

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

        # Wake detection is suspended while a capture is running: the user has
        # already woken us, and running the VAD->Vosk wake check on the
        # microphone thread mid-command would starve the capture (a Vosk
        # decode per speech segment can clip the very audio being recorded).
        # Barge-in during speech is handled by the barge-in VAD, not the wake
        # detector, so nothing is lost by the suspension.
        if self._wake_armed and not self._in_capture and self._wake_detector is not None:
            try:
                # FIX-NO-WAKE-ECHO: the wake detector is not fed during the
                # re-arm cooldown so the residual tail of JARVIS's own speech
                # (or any wake-phrase echo) cannot re-trigger the moment the
                # detector is re-armed after returning to idle.
                if time.monotonic() >= self._wake_rearm_until:
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

    def _track_onset_energy(self, clean: bytes) -> None:
        """Record post-suppression RMS for the onset energy gate (FIX 4)."""
        try:
            if clean and len(clean) % 2 == 0:
                self._onset_rms.append(audioop.rms(clean, 2) / 32768.0)
        except Exception:
            pass

    def _onset_has_energy(self) -> bool:
        """True when recent audio carries speech-like energy (FIX 4).

        Accepts when the window peak clears an absolute floor (loud rooms,
        normal speech) or clearly exceeds the tracked background (quiet
        rooms, soft speech).  Fails open when no audio has been observed.
        """
        if len(self._onset_rms) < _ONSET_MIN_CHUNKS:
            return True
        peak = max(self._onset_rms)
        background = min(self._onset_rms)
        if peak >= _ONSET_MIN_RMS:
            return True
        if background > 0.0 and peak >= _ONSET_MIN_SNR * background:
            return True
        return False

    def _feed_capture(self, clean: bytes) -> None:
        self._track_onset_energy(clean)
        try:
            self._capture_vad.process_audio(clean)
        except Exception as exc:
            logger.error("Capture VAD failed: %s", exc, exc_info=True)
        try:
            # Do not decode the idle portion of a capture. It contains
            # ambient noise and the previous command's tail, and can become
            # a convincing but incorrect Whisper transcript. Once VAD has
            # triggered, include only a short onset pre-roll and then stream
            # the current utterance normally.
            if not getattr(self._capture_vad, "triggered", False):
                return
            if not self._capture_started:
                buffered = self._preroll_bytes_all()
                if len(buffered) > len(clean):
                    buffered = buffered[:-len(clean)]
                onset_preroll = buffered[-_CAPTURE_PREROLL_BYTES:]
                if onset_preroll:
                    self._transcriber.push(onset_preroll)
                self._capture_started = True
            partial = self._transcriber.push(clean)
            if partial:
                self._emit(("partial", partial))
                # PART 14: clamp the inline callback — a slow consumer must
                # never stall the mic thread.  Queue delivery above is the
                # reliable path; inline invocation is best-effort and is
                # switched off permanently after a single overrun.
                if self.on_partial and not self._partial_callback_overruns:
                    started = time.monotonic()
                    try:
                        self.on_partial(partial)
                    except Exception as exc:
                        logger.error("on_partial callback failed: %s", exc)
                    elapsed = time.monotonic() - started
                    if elapsed > _MAX_PARTIAL_CALLBACK_SECONDS:
                        self._partial_callback_overruns += 1
                        logger.warning(
                            "on_partial callback took %.2fs (> %.2fs) on the mic "
                            "thread — disabling inline invocation (PART 14)",
                            elapsed, _MAX_PARTIAL_CALLBACK_SECONDS,
                        )
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
        # PART 7: log the reference becoming active so a runtime trace can
        # prove the echo canceller is receiving JARVIS's own voice.
        if not self._reference_active:
            self._reference_active = True
            logger.info("ECHO_REFERENCE ACTIVE (TTS playback reference feeding echo canceller)")
        now = time.monotonic()
        if now - self._last_ref_diag_at >= 10.0:
            self._last_ref_diag_at = now
            ec = self._echo_canceller
            try:
                logger.info(
                    "ECHO_REFERENCE feeding (delay_locked=%s erle=%.1f dB ref_chunks=%s)",
                    getattr(ec, "delay_locked", None),
                    getattr(ec, "erle_db", 0.0),
                    len(getattr(ec, "_ref", ())) if hasattr(ec, "_ref") else "-",
                )
            except Exception:
                logger.info("ECHO_REFERENCE feeding")
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

    def start_wake_detection(self, rearm_cooldown_seconds: float = 0.0) -> None:
        """Begin listening for the wake phrase (when Idle).

        ``rearm_cooldown_seconds`` starts a short window during which the
        detector is NOT fed mic audio (used after returning to idle so a
        residual echo / wake-phrase tail can drain before we listen again).
        """
        self._ensure_wake_detector()
        self._wake_armed = True
        if rearm_cooldown_seconds > 0:
            self._wake_rearm_until = time.monotonic() + float(rearm_cooldown_seconds)

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
        """Arm instant barge-in detection while TTS is speaking.

        Idempotent: the VAD is only reset on the disarmed->armed transition.
        The conversation loop re-arms this every ~50 ms while JARVIS is
        speaking; a reset on every call would clear the onset accumulator
        before it can reach the majority threshold and instant barge-in would
        never fire.
        """
        if self._barge_in_armed:
            return
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

    def _current_gen(self) -> int:
        with self._lock:
            return self._capture_gen

    @staticmethod
    def _event_gen(event) -> int | None:
        """Generation tag of *event*, or None for legacy untagged events."""
        try:
            if len(event) >= 3 and isinstance(event[2], int):
                return event[2]
        except Exception:
            pass
        return None

    def _event_is_current(self, event, gen: int) -> bool:
        """True when *event* belongs to capture generation *gen*.

        Untagged (legacy / test-injected) events are honoured fail-open;
        tagged events from any other generation are stale and ignored so
        an old turn can never cancel or complete the current turn.
        """
        tag = self._event_gen(event)
        if tag is None:
            return True
        if tag != gen:
            logger.debug(
                "Ignoring stale capture event %r (gen=%d current=%d)",
                event[0] if event else "?", tag, gen,
            )
            return False
        return True

    def _on_capture_speech_started(self) -> None:
        # FIX 4: VAD frame votes alone fire on clicks/transients.  Without
        # speech-like energy behind the onset, reset and keep listening
        # instead of burning a capture + Whisper decode on room noise.
        if not self._onset_has_energy():
            logger.info(
                "SPEECH ONSET rejected (no post-gate energy) — resetting VAD, "
                "keep listening"
            )
            try:
                self._capture_vad.reset()
            except Exception as exc:
                logger.error("Capture VAD reset failed: %s", exc)
            return
        logger.info("SPEECH DETECTED (capture VAD onset)")
        gen = self._current_gen()
        turn_mark("SPEECH_START", gen=gen)
        self._emit(("speech_start", time.monotonic(), gen))

    def _on_capture_speech_ended(self) -> None:
        # FIX-VOICE-003: log speech end time for latency tracking
        end_time = time.monotonic()
        logger.info("SPEECH ENDED (capture VAD silence hangover / max utterance) at t=%.3fs", end_time)
        gen = self._current_gen()
        turn_mark("SPEECH_END", gen=gen)
        self._emit(("speech_end", end_time, gen))

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

        capture_started_at = time.monotonic()
        with self._lock:
            # VOICE-FIX: reset the VAD BEFORE arming the capture.  The mic
            # thread feeds the VAD without holding this lock, so the old
            # order (arm -> reset) let one chunk slip through the stale,
            # ambient-primed onset window and fire a bogus speech_start
            # ~60 ms after capture began.  Draining LAST drops anything
            # that predates the reset; anything emitted after the drain
            # comes from post-reset VAD state (120 ms+ of real speech).
            self._capture_vad.reset()
            self._onset_rms.clear()
            self._transcriber.begin()
            self._capture_started = False
            # Keep only a bounded onset cushion. Do not feed the pre-roll to
            # VAD, because stale audio must not create a speech-start event.
            preroll = self._preroll_bytes_all()[-_CAPTURE_PREROLL_BYTES:]
            if preroll:
                self._transcriber.push(preroll)
            self._drain_events()
            # New turn, new generation: any event tagged with an older
            # generation (late VAD onset/end, a cancel issued for the
            # previous turn) is stale and must not affect this capture.
            self._capture_gen += 1
            gen = self._capture_gen
            self._in_capture = True
        turn_start(gen)
        turn_mark("LISTENING_READY", gen=gen, timeout=timeout)
        logger.info("CAPTURE ACTIVE (gen=%d idle_wait_timeout=%.1fs)", gen, timeout)

        idle_wait_ms = 0.0
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
                    if not self._event_is_current(event, gen):
                        continue
                    speech_started_at = event[1]
                    idle_wait_ms = (time.monotonic() - capture_started_at) * 1000.0
                    logger.info(
                        "SPEECH DETECTED at t=%.3fs — beginning capture "
                        "(idle_wait=%.0f ms)",
                        speech_started_at, idle_wait_ms,
                    )
                    logger.info(
                        "LATENCY stage=capture_start->speech_start %.0f ms",
                        idle_wait_ms,
                    )
                elif kind == "cancelled":
                    if not self._event_is_current(event, gen):
                        continue
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
                    if not self._event_is_current(event, gen):
                        continue
                    logger.info("SPEECH ENDED at t=%.3fs — finalizing", event[1])
                    speech_ended_at = event[1]
                    voiced = max(
                        0.0, speech_ended_at - speech_started_at
                    ) if speech_started_at is not None else None
                    # FIX-VOICE-005: reject blips/shorter than a real word
                    # BEFORE STT — discard and keep listening instead of
                    # burning a Whisper decode on a 0.03s "utterance".
                    if voiced is not None and voiced < _MIN_UTTERANCE_SECONDS:
                        logger.info(
                            "CAPTURE TOO SHORT (%.0f ms) — discarding, "
                            "no STT (FIX-VOICE-005)", voiced * 1000.0,
                        )
                        self._safe_discard()
                        return CaptureResult(
                            "", 0.0, False, reason="too short", duration_ms=0.0,
                        )
                    final = self._finalize_capture(voiced_seconds=voiced)
                    # FIX-VOICE-003: if _finalize_capture returns None (timeout),
                    # we should still exit with a result rather than continuing
                    # to accumulate audio. Return a speech_timeout result.
                    if final is None:
                        logger.warning("Transcriber finalize timed out - exiting capture")
                        return CaptureResult("", 0.0, False, reason="speech_timeout", duration_ms=0.0)
                    return self._final_to_result(
                        final, speech_ended_at, speech_started_at,
                        idle_wait_ms=idle_wait_ms,
                    )
                elif kind == "cancelled":
                    if not self._event_is_current(event, gen):
                        continue
                    logger.info("Capture cancelled during speech")
                    return CaptureResult("", 0.0, False, reason="cancelled", duration_ms=0.0)

            # Deadline reached without a VAD boundary: finalize what we have.
            voiced = (
                max(0.0, time.monotonic() - speech_started_at)
                if speech_started_at is not None
                else None
            )
            final = self._finalize_capture(voiced_seconds=voiced)
            if final is not None:
                return self._final_to_result(
                    final, speech_ended_at, speech_started_at,
                    idle_wait_ms=idle_wait_ms,
                )
            return CaptureResult("", 0.0, False, reason="speech_timeout", duration_ms=0.0)
        finally:
            with self._lock:
                self._in_capture = False
                self._capture_started = False
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

    def _safe_discard(self) -> None:
        """Drop any buffered audio without running STT (FIX-VOICE-005)."""
        try:
            self._transcriber.discard()
        except Exception as exc:
            logger.warning("Transcriber discard failed: %s", exc)

    def _finalize_capture(self, voiced_seconds: float | None = None) -> FinalTranscript | None:
        """Finalize the capture with a hard time bound (PART 15).

        The Whisper decode runs on a short-lived daemon worker so a stuck
        recognizer can never wedge ``capture_command`` past
        ``_MAX_FINALIZE_SECONDS``; on overrun we return ``None`` and the
        caller exits with a ``speech_timeout`` result instead of blocking.
        """
        container: list[FinalTranscript | None] = [None]
        gen = self._current_gen()
        turn_mark("CAPTURE_COMPLETE", gen=gen, voiced_seconds=voiced_seconds)
        turn_mark("STT_START", gen=gen)

        def _run() -> None:
            try:
                container[0] = self._transcriber.finalize(voiced_seconds=voiced_seconds)
            except Exception as exc:
                logger.error("Transcriber finalize failed: %s", exc, exc_info=True)
                container[0] = None

        worker = threading.Thread(target=_run, name="capture-finalize", daemon=True)
        worker.start()
        worker.join(timeout=_MAX_FINALIZE_SECONDS)
        if worker.is_alive():
            logger.warning(
                "Transcriber finalize exceeded %.0fs — aborting capture "
                "(PART 15 hard limit)",
                _MAX_FINALIZE_SECONDS,
            )
            return None
        final = container[0]
        if final is not None:
            turn_mark(
                "STT_RESULT",
                gen=gen,
                accepted=final.accepted,
                text_len=len(final.text or ""),
                reason=final.rejected_reason,
            )
            turn_mark(
                "STT_CONFIDENCE",
                gen=gen,
                confidence=round(float(final.confidence), 3),
            )
        return final

    def _final_to_result(
        self,
        final: FinalTranscript,
        speech_ended_at: float | None = None,
        speech_started_at: float | None = None,
        idle_wait_ms: float = 0.0,
    ) -> CaptureResult:
        """Log the recognition outcome, then wrap it as a CaptureResult.

        The synonym engine canonicalises the accepted text (e.g. "start music"
        -> "play music") so the intent parser always sees one canonical form;
        the raw text is preserved for internal comparison.  ``recognition_ms``
        measures Speech End -> Recognition Finished (latency stage 2); the
        per-word / per-sentence confidence and the idle wait (Phase A) are
        carried so the Speech Intelligence Layer and latency report can use
        them.
        FIX-VOICE-003: add comprehensive timing logs.
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
            word_confidences=final.word_confidences,
            sentence_confidences=final.sentence_confidences,
            min_word_confidence=final.min_word_confidence,
            idle_wait_ms=idle_wait_ms,
        )
        # FIX-VOICE-003: comprehensive timing logs
        logger.info("CAPTURE_START audio=%.2fs", idle_wait_ms / 1000.0)
        if speech_started_at is not None:
            logger.info("SPEECH_START audio=%.2fs", speech_started_at - capture_started_at if 'capture_started_at' in locals() else 0.0)
        if speech_ended_at is not None:
            logger.info("SPEECH_END audio=%.2fs", speech_seconds)
        logger.info("AUDIO_DURATION=%.2fs", speech_seconds)
        logger.info("STT_START")
        logger.info("STT_END text=%r confidence=%.3f", final.text, final.confidence)
        logger.info("STT_CONFIDENCE=%.3f", final.confidence)
        if not final.accepted:
            logger.info("REASON REJECTED: %s (text=%r confidence=%.3f)",
                final.rejected_reason, final.text, final.confidence)
        return result

    # ------------------------------------------------------------------
    # Capture cancellation (called by the conversation owner)
    # ------------------------------------------------------------------

    def cancel_capture(self) -> None:
        """Abort an in-progress capture (e.g. shutdown / new command).

        The cancel is tagged with the generation it was issued for: a
        cancel that lands after its turn already finished (late task
        cleanup, watchdog recovery) is stale and must never abort the
        next turn's capture.
        """
        with self._lock:
            self._cancel_gen = self._capture_gen
            self._in_capture = False
            gen = self._capture_gen
        self._transcriber.discard()
        self._emit(("cancelled", time.monotonic(), gen))

    @property
    def is_capture_active(self) -> bool:
        """True while a capture_command turn is armed on this session.

        Used by the conversation owner to verify LISTENING is real
        (capture armed) rather than just a published UI state.
        """
        with self._lock:
            return self._in_capture

    @property
    def capture_generation(self) -> int:
        """Current capture generation (diagnostics / tests)."""
        with self._lock:
            return self._capture_gen

    def reset_capture_state(self) -> None:
        """Drop all in-flight capture state without emitting events.

        Used by watchdog recovery to return to a known-good listening
        baseline: VAD reset, transcriber discarded, stale events drained,
        capture disarmed.  The next capture_command starts a fresh
        generation, so nothing reset here can leak into the next turn.
        """
        with self._lock:
            self._in_capture = False
            self._capture_started = False
            try:
                self._capture_vad.reset()
            except Exception as exc:
                logger.error("Capture VAD reset failed: %s", exc)
            try:
                self._barge_in_vad.reset()
            except Exception as exc:
                logger.error("Barge-in VAD reset failed: %s", exc)
            self._onset_rms.clear()
            try:
                self._transcriber.discard()
            except Exception as exc:
                logger.warning("Transcriber discard failed: %s", exc)
            self._drain_events()
        logger.info("Capture state reset (gen=%d) — ready to re-arm", self._current_gen())

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
