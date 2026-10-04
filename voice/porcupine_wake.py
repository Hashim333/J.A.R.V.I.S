"""
voice/porcupine_wake.py

Porcupine wake-word spotter (Picovoice) with a graceful off switch.

``pvporcupine`` (4.x) requires a Picovoice **access key** at construction
time plus a keyword — either a built-in keyword name (e.g. ``"jarvis"``) or
a path to a ``.ppn`` model file.  The key and keyword are read from the
environment / settings:

  * ``JARVIS_PICOVOICE_ACCESS_KEY``  — Picovoice access key (required)
    * ``JARVIS_PORCUPINE_KEYWORD``     — builtin keyword (default ``monday``)
  * ``JARVIS_PORCUPINE_KEYWORD_PATH``— ``.ppn`` model path (overrides keyword)

When no key is configured (or the module/model cannot be loaded) the
detector reports ``available == False`` and ``process_audio`` always returns
``False`` — the wake-word service then keeps using the existing local Vosk
wake detector, so the pipeline never depends on a cloud key.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _access_key() -> str:
    return os.getenv("JARVIS_PICOVOICE_ACCESS_KEY", "").strip()


class PorcupineWakeWord:
    """
    Streaming Porcupine wake-word spotter.

    Frame-based: audio is buffered into Porcupine's native frame size
    (512 samples @ 16 kHz) and fed to ``process``.  ``process_audio`` returns
    ``True`` the moment the keyword is detected.
    """

    def __init__(
        self,
        access_key: str | None = None,
        keyword_path: str | None = None,
        keyword: str = "monday",
        sensitivities: list[float] | None = None,
    ) -> None:
        self._available = False
        self._porcupine: Any = None
        self._frame_length = 512
        self._frame_buffer = bytearray()
        self._sensitivities = sensitivities

        key = (access_key or _access_key()).strip()
        keyword_path = (keyword_path or os.getenv("JARVIS_PORCUPINE_KEYWORD_PATH", "")).strip()
        keyword = (keyword or os.getenv("JARVIS_PORCUPINE_KEYWORD", "monday")).strip()

        if not key:
            logger.info(
                "Porcupine disabled: no Picovoice access key "
                "(set JARVIS_PICOVOICE_ACCESS_KEY); using local wake detector"
            )
            return
        try:
            import pvporcupine

            kwargs: dict[str, Any] = {"access_key": key}
            if keyword_path:
                kwargs["keyword_paths"] = [keyword_path]
            else:
                kwargs["keywords"] = [keyword or "monday"]
            if self._sensitivities:
                kwargs["sensitivities"] = self._sensitivities
            self._porcupine = pvporcupine.create(**kwargs)
            self._frame_length = int(getattr(self._porcupine, "frame_length", 512))
            self._available = True
            logger.info(
                "Porcupine wake word active (keyword=%s%s frame_length=%d)",
                keyword, f" path={keyword_path}" if keyword_path else "",
                self._frame_length,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Porcupine could not be initialised (%s) — using local wake detector",
                exc,
            )
            self._porcupine = None
            self._available = False

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._available

    @property
    def frame_length(self) -> int:
        return self._frame_length

    def reset(self) -> None:
        """Clear buffered audio after a detection."""
        self._frame_buffer = bytearray()

    def process_audio(self, chunk: bytes) -> bool:
        """Feed a 16-bit PCM chunk; returns True when the keyword is heard."""
        if self._porcupine is None:
            return False
        self._frame_buffer.extend(chunk)
        frame_bytes = self._frame_length * 2
        detected = False
        while len(self._frame_buffer) >= frame_bytes:
            frame = bytes(self._frame_buffer[:frame_bytes])
            del self._frame_buffer[:frame_bytes]
            try:
                if self._porcupine.process(frame) >= 0:
                    detected = True
            except Exception as exc:  # noqa: BLE001
                logger.error("Porcupine process failed: %s", exc, exc_info=True)
                detected = False
                break
        return detected

    def close(self) -> None:
        """Release the native resources (no-op when inactive)."""
        if self._porcupine is not None:
            try:
                self._porcupine.delete()
            except Exception:
                pass
            self._porcupine = None
        self._available = False
