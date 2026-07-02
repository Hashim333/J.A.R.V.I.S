"""
voice/system_provider.py

Offline Windows text-to-speech provider.
"""

from __future__ import annotations

import subprocess

from voice.provider import VoiceProvider


class SystemProvider(VoiceProvider):
    """Speak through Windows' built-in SAPI voice engine."""

    def __init__(self, voice_id: str | None = None) -> None:
        self._voice_id = voice_id

    def speak(self, text: str) -> bool:
        if not isinstance(text, str) or not text.strip():
            return False

        script = self._build_script(text.strip())
        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    script,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False

        if completed.returncode != 0:
            return False

        return True

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
