"""
voice/audio_lock.py

Global lock that ensures only one component opens the microphone at any time.

Usage:
    from voice.audio_lock import audio_lock

    if not audio_lock.acquire("microphone_stream", timeout=5.0):
        raise RuntimeError("Microphone is in use by another component")
    try:
        microphone.__enter__()
        ...
    finally:
        microphone.__exit__(...)
        audio_lock.release("microphone_stream")
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class AudioLock:
    """
    Exclusive microphone access lock.

    Components that open sr.Microphone (MicrophoneStream, MicrophoneManager)
    must acquire this lock before opening and release after closing.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: str | None = None
        self._released = threading.Event()
        self._released.set()

    def acquire(self, owner: str, timeout: float = 5.0) -> bool:
        """
        Acquire exclusive microphone access.

        Blocks until the lock is available or timeout expires.

        Args:
            owner: Identifier for the component acquiring the lock.
            timeout: Maximum seconds to wait.

        Returns:
            True if acquired, False if timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._owner is None:
                    self._owner = owner
                    self._released.clear()
                    logger.debug("audio_lock acquired by %r", owner)
                    return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning("audio_lock timed out for %r (current owner: %r)", owner, self._owner)
                return False
            self._released.wait(timeout=min(0.1, remaining))
        return False

    def release(self, owner: str) -> None:
        """
        Release exclusive microphone access.

        Idempotent — safe to call multiple times.
        Raises RuntimeError only if a mismatched owner calls release.

        Args:
            owner: Must match the current owner.
        """
        with self._lock:
            if self._owner is None:
                logger.debug("audio_lock released by %r (was already free)", owner)
                return
            if self._owner != owner:
                raise RuntimeError(
                    f"Cannot release AudioLock: owner is {self._owner!r}, "
                    f"but {owner!r} tried to release"
                )
            self._owner = None
            self._released.set()
            logger.debug("audio_lock released by %r", owner)

    @property
    def owner(self) -> str | None:
        with self._lock:
            return self._owner

    @property
    def is_acquired(self) -> bool:
        return self.owner is not None


# Global singleton — import this from any component that opens sr.Microphone.
audio_lock = AudioLock()
