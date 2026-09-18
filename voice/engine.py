"""
voice/engine.py

Central voice coordination engine providing:

- Queue-based, non-blocking TTS via VoiceManager
- Interruptible speech (barge-in: stop TTS when user starts speaking)
- Cancelable speech (cancel remaining queued utterances)
- Thread-safe operations
- VAD-based barge-in monitoring while speaking

Usage::

    engine = VoiceEngine(voice_manager, microphone_stream)
    engine.speak("Hello, I am JARVIS.")
    # ...
    engine.interrupt()          # stop current speech immediately
    engine.cancel_all()         # stop + clear queue
    engine.speak_and_wait("Please choose an option.")  # blocking

TTS only speaks — it never changes conversation state.  The conversation
owner (``services.conversation_owner``) is the single owner of
Wake/Listening/Thinking/Speaking/Sleep.
"""

from __future__ import annotations

import datetime
import logging
import threading
import time
import traceback
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from voice.manager import VoiceManager
    from voice.microphone_stream import MicrophoneStream

logger = logging.getLogger(__name__)

# Ignore any VAD onset for the first moments after a new utterance is
# enqueued (mic mute settling / echo). 500-700 ms per the milestone spec.
_BARGE_IN_GRACE_SECONDS = 0.6
# After the grace window, an onset only cancels playback if the user keeps
# speaking for at least 700 ms and the signal remains strong enough.
_BARGE_IN_CONFIRM_SECONDS = 0.7
_BARGE_IN_AUDIO_LEVEL_THRESHOLD = 0.16
_BARGE_IN_CONFIDENCE_THRESHOLD = 0.25
_BARGE_IN_PROGRESS_THRESHOLD = 0.7


class VoiceEngine:
    """Non-blocking, interruptible speech coordination with barge-in.

    Delegates speech synthesis and queuing to VoiceManager.
    Owns barge-in detection (VAD-based monitoring while speaking).
    """

    def __init__(
        self,
        voice_manager: VoiceManager | None = None,
        microphone_stream: MicrophoneStream | None = None,
        on_barge_in: Callable[[], None] | None = None,
    ) -> None:
        self._voice_manager = voice_manager
        self._microphone_stream = microphone_stream
        self._on_barge_in = on_barge_in
        # Full-duplex session (owned by run.py).  When present it owns the
        # microphone consumer and performs instant echo-cancelled barge-in;
        # the legacy VAD-based barge-in below is only used without a session.
        self._duplex_session = None

        # Barge-in VAD
        self._barge_in_active = False
        self._barge_in_vad: object | None = None
        # Once barge-in fires, monitoring stays disarmed until the next
        # speak() so we never re-arm mid-utterance (re-arm flapping) while
        # the user is still talking.
        self._barge_in_fired = False
        # Ignore speech onset in the first moments after a new utterance is
        # enqueued — protects against JARVIS interrupting its own speech at
        # the very start of playback (mic mute settling / echo).
        self._barge_in_grace_until: float = 0.0
        # A VAD onset was seen past the grace window but the user has not
        # spoken long enough to confirm a genuine interruption yet.
        self._barge_in_pending = False
        self._barge_in_timer: threading.Timer | None = None
        self._barge_in_started_at: float | None = None
        self._latest_audio_level = 0.0
        self._latest_confidence = 0.0

    def set_duplex_session(self, session) -> None:
        """Attach the full-duplex session for instant echo-cancelled barge-in.

        When attached, the session owns barge-in detection (its VAD runs on
        echo-cancelled audio, so JARVIS's own TTS can never interrupt itself)
        and the engine's legacy mic-consumer barge-in is disabled.
        """
        self._duplex_session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def speak(self, text: str, priority: bool = False) -> None:
        """Enqueue text for speech. Returns immediately."""
        if not text or not text.strip():
            return
        # A new utterance arms barge-in monitoring again.
        self._barge_in_fired = False
        self._barge_in_pending = False
        self._barge_in_started_at = None
        self._latest_audio_level = 0.0
        self._latest_confidence = 0.0
        # Grace window: ignore any VAD onset right after enqueueing so the
        # new utterance is never cut off by its own first frames.
        self._barge_in_grace_until = time.monotonic() + _BARGE_IN_GRACE_SECONDS
        if self._voice_manager is not None:
            self._voice_manager.speak(text.strip(), priority=priority)
        else:
            logger.warning("VoiceEngine: no VoiceManager configured, cannot speak")

    def speak_and_wait(self, text: str, timeout: float | None = None) -> bool:
        """Speak text and block until speech completes or *timeout*.

        Returns True if speech completed, False if interrupted/timed out.
        """
        if self._voice_manager is None:
            return False

        done = threading.Event()
        original = self._on_barge_in
        self._on_barge_in = lambda: done.set()

        self.speak(text)

        deadline = None
        if timeout is not None:
            deadline = time.monotonic() + timeout

        while not done.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                self.interrupt()
                self._on_barge_in = original
                return False
            if not self.is_speaking and (
                self._voice_manager is None or self._voice_manager.queue_size == 0
            ):
                done.set()
                break
            time.sleep(0.05)

        self._on_barge_in = original
        return True

    def interrupt(self, reason: str = "voice_engine.interrupt") -> None:
        """Stop current speech immediately. Queued utterances remain."""
        self._log_stop_request(reason)
        if self._voice_manager is not None:
            self._voice_manager.stop(reason=reason, caller="voice_engine.interrupt")
        # Speech is stopping — no longer need barge-in monitoring.
        self.stop_barge_in()
        logger.info("VoiceEngine: speech interrupted (%s)", reason)

    def cancel_all(self) -> None:
        """Stop current speech and clear the speech queue."""
        self._log_stop_request("voice_engine.cancel_all")
        if self._voice_manager is not None:
            self._voice_manager.cancel_all()
        logger.info("VoiceEngine: all speech cancelled")

    def shutdown(self) -> None:
        """Stop speech and release the voice manager's worker thread."""
        self.stop_barge_in()
        if self._voice_manager is not None:
            self._voice_manager.shutdown()
        logger.info("VoiceEngine: shut down")

    @property
    def is_speaking(self) -> bool:
        """True when audio is currently playing."""
        return self._voice_manager is not None and self._voice_manager.is_playing

    @property
    def is_busy(self) -> bool:
        """True while speech is queued, being generated, or playing.

        Used by the conversation loop to decide when it is safe to start
        listening again — otherwise it would start capturing while TTS was
        still being generated (dequeued, not yet playing).
        """
        if self._voice_manager is None:
            return False
        try:
            return self._voice_manager.is_busy
        except Exception:
            return self.is_speaking or self.queue_size > 0

    @property
    def queue_size(self) -> int:
        return self._voice_manager.queue_size if self._voice_manager else 0

    # ------------------------------------------------------------------
    # Barge-in detection
    # ------------------------------------------------------------------

    def start_barge_in(self) -> None:
        """Begin monitoring for barge-in while speech is active.

        With a full-duplex session attached, detection is delegated to the
        session (echo-cancelled signal -> instant onset cancellation).
        Otherwise the legacy VAD/mic-consumer path is used.
        """
        if self._duplex_session is not None:
            self._duplex_session.arm_barge_in()
            logger.info("VoiceEngine: barge-in monitoring started (full-duplex session)")
            return
        if self._barge_in_active:
            return
        if self._barge_in_fired:
            logger.debug("VoiceEngine: barge-in already fired — not re-arming")
            return
        if self._microphone_stream is None:
            return
        if not self.is_speaking:
            logger.debug("VoiceEngine: not speaking — skipping barge-in arm")
            return
        self._barge_in_active = True

        from voice.vad import VAD

        self._barge_in_vad = VAD(
            on_speech_started=self._on_speech_detected,
            on_speech_ended=self._on_speech_ended,
            sample_rate=16000,
        )

        # FIX 3: never steal a consumer owned by someone else (e.g. the
        # full-duplex session).  If the feed is owned, barge-in cannot
        # attach here — refuse loudly instead of hijacking STT or, worse,
        # leaving the mic disconnected on stop().
        current = self._microphone_stream._consumer
        if current is not None and getattr(current, "__self__", None) is not self._barge_in_vad:
            owner = type(getattr(current, "__self__", current)).__name__
            if owner != "VoiceEngine":
                logger.warning(
                    "VoiceEngine: barge-in refused — mic consumer owned by %s",
                    owner,
                )
                self._barge_in_active = False
                self._barge_in_vad = None
                return
        self._microphone_stream.set_consumer(self._barge_in_vad.process_audio)
        self._microphone_stream.set_on_audio_level(self._on_audio_level)
        logger.info("VoiceEngine: barge-in monitoring started")

    def stop_barge_in(self) -> None:
        """Stop barge-in monitoring and restore audio consumer."""
        if self._duplex_session is not None:
            self._duplex_session.disarm_barge_in()
            logger.info("VoiceEngine: barge-in monitoring stopped (full-duplex session)")
            return
        if not self._barge_in_active:
            return
        self._barge_in_active = False
        if self._barge_in_timer is not None:
            self._barge_in_timer.cancel()
            self._barge_in_timer = None
        self._barge_in_pending = False
        if self._microphone_stream is not None:
            # FIX 3: only release the consumer if it is still ours — never
            # disconnect a feed owned by someone else (e.g. duplex STT).
            current = self._microphone_stream._consumer
            if current is None or (
                getattr(current, "__self__", None) is self._barge_in_vad
            ):
                self._microphone_stream.set_consumer(None)
                self._microphone_stream.set_on_audio_level(None)
            else:
                logger.warning(
                    "VoiceEngine: barge-in stopped but mic consumer owned by "
                    "%s — left attached",
                    type(getattr(current, "__self__", current)).__name__,
                )
        self._barge_in_vad = None
        logger.info("VoiceEngine: barge-in monitoring stopped")

    def _on_speech_detected(self) -> None:
        """Called by VAD when the user starts speaking while TTS is active.

        A single onset does not interrupt playback immediately. The speech
        must survive the grace window AND the confirm window (continuous
        speech) before the utterance is cancelled — accidental barge-in
        from a cough or a brief utterance is ignored.
        """
        if time.monotonic() < self._barge_in_grace_until:
            logger.debug("VoiceEngine: barge-in onset ignored (grace period)")
            return
        if self._barge_in_fired or self._barge_in_pending:
            logger.debug("VoiceEngine: barge-in already pending/fired — ignoring onset")
            return
        logger.info("VoiceEngine: barge-in onset — confirming continuous speech")
        self._barge_in_pending = True
        self._barge_in_started_at = time.monotonic()
        self._barge_in_timer = threading.Timer(
            _BARGE_IN_CONFIRM_SECONDS, self._confirm_barge_in,
        )
        self._barge_in_timer.daemon = True
        self._barge_in_timer.start()

    def _on_speech_ended(self) -> None:
        """Called by VAD when the user stops speaking.

        If speech ends before the confirm window elapses, the onset was
        accidental — cancel the pending barge-in and let TTS continue.
        """
        if self._barge_in_pending:
            logger.debug("VoiceEngine: speech ended before confirm — barge-in cancelled")
            self._barge_in_pending = False
            if self._barge_in_timer is not None:
                self._barge_in_timer.cancel()
                self._barge_in_timer = None

    def _confirm_barge_in(self) -> None:
        """Timer callback: the user kept speaking — fire the interruption."""
        if not self._barge_in_pending:
            return
        if self._barge_in_started_at is None:
            self._barge_in_pending = False
            self._barge_in_timer = None
            return

        duration = time.monotonic() - self._barge_in_started_at
        audio_level = self._latest_audio_level
        confidence = max(audio_level, self._latest_confidence)
        progress = self._speech_progress()

        logger.info(
            "VoiceEngine: barge-in check duration=%.3fs level=%.3f confidence=%.3f progress=%.3f",
            duration,
            audio_level,
            confidence,
            progress,
        )

        if duration < _BARGE_IN_CONFIRM_SECONDS:
            logger.debug("VoiceEngine: barge-in ignored — speech below 700ms window")
            return
        if audio_level < _BARGE_IN_AUDIO_LEVEL_THRESHOLD:
            logger.debug("VoiceEngine: barge-in ignored — energy below threshold")
            return
        if confidence < _BARGE_IN_CONFIDENCE_THRESHOLD:
            logger.debug("VoiceEngine: barge-in ignored — confidence below threshold")
            return
        if progress < _BARGE_IN_PROGRESS_THRESHOLD:
            logger.debug("VoiceEngine: barge-in ignored — TTS not yet 70%% complete")
            return

        self._barge_in_pending = False
        self._barge_in_timer = None
        logger.info("VoiceEngine: BARGE-IN CONFIRMED — continuous speech detected")
        self._barge_in_fired = True
        self.interrupt(reason="barge_in_confirmed")
        self.stop_barge_in()
        if self._on_barge_in:
            try:
                self._on_barge_in()
            except Exception as exc:
                logger.error("VoiceEngine: barge-in callback failed: %s", exc)
        logger.info("VoiceEngine: barge-in event — speech cancelled, listening ready")

    def _speech_progress(self) -> float:
        if self._voice_manager is None:
            return 1.0
        try:
            progress = self._voice_manager.get_speech_progress()
        except AttributeError:
            progress = 1.0
        except Exception:
            progress = 1.0
        try:
            return float(progress)
        except (TypeError, ValueError):
            return 0.0

    def _on_audio_level(self, level: float) -> None:
        self._latest_audio_level = max(0.0, min(1.0, float(level)))
        self._latest_confidence = self._latest_audio_level

    def _log_stop_request(self, reason: str) -> None:
        frame = traceback.extract_stack(limit=7)[-2]
        caller = f"{frame.filename}:{frame.lineno} {frame.name}"
        logger.info(
            "STOP_REQUEST caller=%s thread=%s reason=%s timestamp=%s stack=%s",
            caller,
            threading.current_thread().name,
            reason,
            datetime.datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "".join(traceback.format_stack(limit=8)).rstrip(),
        )