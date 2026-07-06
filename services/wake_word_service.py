"""
services/wake_word_service.py

The Wake Word Service is responsible for listening for a specific wake word
(e.g., "Jarvis") in the user's speech and detecting voice activity.

It uses a MicrophoneStream to capture audio and a VAD (Voice Activity
Detection) instance to determine when speech starts and stops. This service
is a concrete implementation of BaseService and is managed by the
ServiceManager.
"""

from __future__ import annotations
import threading
from services.base_service import BaseService
from voice.microphone_stream import MicrophoneStream
from voice.vad import VAD


class WakeWordService(BaseService):
    """
    A service that listens for a wake word in the background.

    This service manages a microphone stream and a VAD instance to detect
    voice activity. It exposes events for speech start and end but does not
    yet implement the full wake word detection logic.
    """

    def __init__(self) -> None:
        super().__init__(name="wake_word")
        self._vad: VAD | None = None  # Initialized in initialize()
        self._microphone_stream: MicrophoneStream | None = None  # Initialized in initialize()
        self.is_speech_detected = threading.Event()

    def initialize(self) -> None:
        """
        Initializes the VAD and MicrophoneStream.

        This method creates instances of the VAD and the microphone stream.
        If the microphone stream fails to initialize (e.g., no microphone
        is found), it will not raise an exception, but the service will
        subsequently fail to start.
        """
        try:
            self._vad = VAD(
                on_speech_started=self._on_speech_started,
                on_speech_ended=self._on_speech_ended,
            )
            self._microphone_stream = MicrophoneStream(
                on_audio_chunk=self._vad.process_audio
            )
        except Exception as e:
            # Per test_microphone_service, initialization should not fail if the
            # microphone is not found. The failure is deferred to start().
            # However, for other exceptions, we must re-raise so the
            # ServiceManager can mark the service as FAILED.
            if "Microphone not found" not in str(e):
                raise

    def _on_speech_started(self) -> None:
        """Callback for when speech is detected."""
        self.is_speech_detected.set()

    def _on_speech_ended(self) -> None:
        """Callback for when speech ends."""
        self.is_speech_detected.clear()

    def start(self) -> None:
        """
        Starts the microphone stream to listen for the wake word.
        """
        if self._microphone_stream is None:
            raise RuntimeError("Microphone stream not initialized. Cannot start.")
        self._microphone_stream.start()

    def stop(self) -> None:
        """
        Stops the microphone stream.
        """
        if self._microphone_stream is not None:
            self._microphone_stream.stop()

    def shutdown(self) -> None:
        """
        Shuts down the microphone stream, releasing resources.
        """
        if self._microphone_stream is not None:
            self._microphone_stream.shutdown()