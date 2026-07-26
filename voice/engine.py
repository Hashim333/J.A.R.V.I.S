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
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from voice.manager import VoiceManager
    from voice.microphone_stream import MicrophoneStream

logger = logging.getLogger(__name__)


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

        # Barge-in VAD
        self._barge_in_active = False
        self._barge_in_vad: object | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def speak(self, text: str, priority: bool = False) -> None:
        """Enqueue text for speech. Returns immediately."""
        if not text or not text.strip():
            return
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

    def interrupt(self) -> None:
        """Stop current speech immediately. Queued utterances remain."""
        if self._voice_manager is not None:
            self._voice_manager.stop()
        logger.info("VoiceEngine: speech interrupted")

    def cancel_all(self) -> None:
        """Stop current speech and clear the speech queue."""
        if self._voice_manager is not None:
            self._voice_manager.cancel_all()
        logger.info("VoiceEngine: all speech cancelled")

    @property
    def is_speaking(self) -> bool:
        """True when audio is currently playing."""
        return self._voice_manager is not None and self._voice_manager.is_playing

    @property
    def queue_size(self) -> int:
        return self._voice_manager.queue_size if self._voice_manager else 0

    # ------------------------------------------------------------------
    # Barge-in detection
    # ------------------------------------------------------------------

    def start_barge_in(self) -> None:
        """Begin monitoring for barge-in while speech is active."""
        if self._barge_in_active:
            return
        if self._microphone_stream is None:
            return
        self._barge_in_active = True

        from voice.vad import VAD

        self._barge_in_vad = VAD(
            on_speech_started=self._on_speech_detected,
            on_speech_ended=None,
            sample_rate=16000,
        )

        self._microphone_stream.set_consumer(self._barge_in_vad.process_audio)
        logger.info("VoiceEngine: barge-in monitoring started")

    def stop_barge_in(self) -> None:
        """Stop barge-in monitoring and restore audio consumer."""
        if not self._barge_in_active:
            return
        self._barge_in_active = False
        if self._microphone_stream is not None:
            self._microphone_stream.set_consumer(None)
        self._barge_in_vad = None
        logger.info("VoiceEngine: barge-in monitoring stopped")

    def _on_speech_detected(self) -> None:
        """Called by VAD when user starts speaking while TTS is active."""
        logger.info("VoiceEngine: BARGE-IN DETECTED — user started speaking")
        self.interrupt()
        self.stop_barge_in()
        if self._on_barge_in:
            try:
                self._on_barge_in()
            except Exception as exc:
                logger.error("VoiceEngine: barge-in callback failed: %s", exc)
        logger.info("VoiceEngine: barge-in event — speech cancelled, listening ready")
