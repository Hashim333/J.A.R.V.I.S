"""
voice/system_provider.py

Offline Windows text-to-speech provider with non-blocking, interruptible
speech via a background PowerShell process.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time

from voice.provider import VoiceProvider

logger = logging.getLogger(__name__)


class SystemProvider(VoiceProvider):
    """Speak through Windows' built-in SAPI voice engine.

    Speech runs in a background thread so speak() returns immediately.
    stop() kills the PowerShell process to interrupt speech.
    """

    def __init__(self, voice_id: str | None = None) -> None:
        self._voice_id = voice_id
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._speak_thread: threading.Thread | None = None

    def speak(self, text: str) -> bool:
        if not isinstance(text, str) or not text.strip():
            return False

        script = self._build_script(text.strip())

        def _run() -> None:
            with self._lock:
                try:
                    self._process = subprocess.Popen(
                        ["powershell", "-NoProfile", "-Command", script],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except OSError:
                    self._process = None
                    logger.warning("SystemProvider: failed to launch PowerShell")
                    return

            if self._process is None:
                return

            try:
                self._process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                self._process.kill()
            except Exception:
                pass
            finally:
                with self._lock:
                    self._process = None

        # Cancel any previous speech
        self.stop()

        self._speak_thread = threading.Thread(target=_run, daemon=True)
        self._speak_thread.start()
        return True

    def stop(self) -> None:
        """Kill the current PowerShell speech process immediately."""
        with self._lock:
            proc = self._process
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
                self._process = None

    @property
    def is_playing(self) -> bool:
        """True when the PowerShell speech process is still running."""
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def _build_script(self, text: str) -> str:
        escaped_text = _escape_powershell_string(text)
        script = [
            "Add-Type -AssemblyName System.Speech",
            "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer",
        ]
        if self._voice_id:
            escaped_voice = _escape_powershell_string(self._voice_id)
            script.append(
                f"try {{ $speaker.SelectVoice('{escaped_voice}') }} catch {{ }}"
            )
        script.append(f"$speaker.Speak('{escaped_text}')")
        script.append("$speaker.Dispose()")
        return "; ".join(script)


def _escape_powershell_string(value: str) -> str:
    return value.replace("'", "''")
