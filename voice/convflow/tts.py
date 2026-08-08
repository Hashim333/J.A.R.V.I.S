"""
voice/pipeline/tts.py

``TTSManager`` — interruptible speech output for Conversation Mode.

Every utterance is non-blocking and interruptible: the moment the user starts
speaking (or says "jarvis" / issues a new command), the manager stops the
current playback instantly and the pipeline re-enters Listening.  It also
feeds the exact PCM written to the speakers back to the echo canceller so
JARVIS can never wake or barge-in on its own voice.

Wraps the existing :class:`voice.engine.VoiceEngine` (itself built on
:class:`voice.manager.VoiceManager`) — the only new responsibilities here are
barge-in orchestration and the playback-reference feed for AEC.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


class TTSManager:
    """Non-blocking, interruptible TTS with playback->AEC reference.

    Args:
        engine: A ``VoiceEngine``-like object exposing ``speak``, ``interrupt``,
            ``cancel_all``, ``is_speaking``, ``is_busy`` and ``start_barge_in`` /
            ``stop_barge_in`` (injected in tests).
        on_playback_chunk: Optional ``(pcm, sample_rate) -> None`` forwarded to
            the echo canceller (called from the player thread).
        on_interrupt: Called when the user barges in while speaking.
    """

    def __init__(
        self,
        engine: Any = None,
        on_playback_chunk: Callable[[bytes, int], None] | None = None,
        on_interrupt: Callable[[], None] | None = None,
    ) -> None:
        self._engine = engine
        self._on_playback_chunk = on_playback_chunk
        self._on_interrupt = on_interrupt
        self._player: Any = None
        if engine is not None:
            self._wire_player(engine)

    def _wire_player(self, engine: Any) -> None:
        manager = getattr(engine, "_voice_manager", None)
        if manager is None:
            return
        try:
            self._player = manager.provider.player
        except AttributeError:
            self._player = None
        player = self._player
        if player is not None and hasattr(player, "on_chunk_written") and self._on_playback_chunk:
            player.on_chunk_written = self._on_playback_chunk

    # ------------------------------------------------------------------
    # Speaking
    # ------------------------------------------------------------------

    def speak(self, text: str, priority: bool = False) -> bool:
        """Enqueue text for speech (non-blocking). Returns True on success."""
        if not text or not text.strip():
            return False
        if self._engine is None:
            return False
        try:
            self._engine.speak(text.strip(), priority=priority)
            return True
        except Exception as exc:
            logger.error("TTS speak failed: %s", exc, exc_info=True)
            return False

    def stop(self, reason: str = "tts_manager.stop") -> None:
        """Interrupt current playback immediately (queued utterances remain)."""
        if self._engine is not None:
            try:
                self._engine.interrupt(reason=reason)
            except Exception as exc:
                logger.error("TTS interrupt failed: %s", exc, exc_info=True)

    def cancel_all(self, reason: str = "tts_manager.cancel_all") -> None:
        if self._engine is not None:
            try:
                self._engine.cancel_all()
            except Exception as exc:
                logger.error("TTS cancel_all failed: %s", exc, exc_info=True)

    @property
    def is_speaking(self) -> bool:
        return bool(self._engine is not None and self._engine.is_speaking)

    @property
    def is_busy(self) -> bool:
        return bool(self._engine is not None and self._engine.is_busy)

    @property
    def queue_size(self) -> int:
        return self._engine.queue_size if self._engine is not None else 0

    # ------------------------------------------------------------------
    # Barge-in
    # ------------------------------------------------------------------

    def arm_barge_in(self) -> None:
        if self._engine is not None:
            try:
                self._engine.start_barge_in()
            except Exception as exc:
                logger.error("TTS arm_barge_in failed: %s", exc, exc_info=True)

    def disarm_barge_in(self) -> None:
        if self._engine is not None:
            try:
                self._engine.stop_barge_in()
            except Exception as exc:
                logger.error("TTS disarm_barge_in failed: %s", exc, exc_info=True)

    def on_barge_in(self) -> None:
        """Called by the underlying engine when the user interrupts speech."""
        logger.info("TTSManager: user barge-in")
        if self._on_interrupt is not None:
            try:
                self._on_interrupt()
            except Exception as exc:
                logger.error("TTSManager on_interrupt failed: %s", exc, exc_info=True)

    def shutdown(self) -> None:
        try:
            self.disarm_barge_in()
            self.cancel_all("tts_manager.shutdown")
        except Exception as exc:
            logger.error("TTSManager shutdown error: %s", exc, exc_info=True)