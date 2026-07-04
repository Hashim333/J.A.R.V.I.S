"""
services/wake_word_service.py

A long-running background service that will eventually listen for a
wake word ("Hey JARVIS").

For this milestone, it only implements the service lifecycle: a
background thread that can be started, stopped, and restarted
cleanly by ServiceManager. It does not yet perform any microphone
I/O or wake word detection.
"""

from __future__ import annotations

from services.base_service import BaseService
from voice.microphone_stream import MicrophoneStream


class WakeWordService(BaseService):
    """
    A wake word service that continuously captures audio from the microphone.
    """

    def __init__(self) -> None:
        super().__init__(name="wake_word")
        self._microphone_stream: MicrophoneStream | None = None

    def initialize(self) -> None:
        """
        One-time setup. Initialize microphone resources.
        """
        self._microphone_stream = MicrophoneStream()

    def start(self) -> None:
        """
        Start capturing audio from the microphone.
        """
        if self._microphone_stream:
            self._microphone_stream.start()

    def stop(self) -> None:
        """
        Signal the background thread to stop and wait for it to exit.
        """
        if self._microphone_stream:
            self._microphone_stream.stop()

    def shutdown(self) -> None:
        """
        Ensure the service is stopped cleanly on application exit.
        """
        if self._microphone_stream:
            self._microphone_stream.shutdown()