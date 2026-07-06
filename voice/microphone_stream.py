"""
voice/microphone_stream.py

A non-blocking, continuous microphone stream.
"""
import threading
import time
from typing import Any, Callable

import speech_recognition as sr


class MicrophoneStream:
    """A non-blocking, continuous microphone stream."""

    def __init__(
        self,
        microphone_factory: Callable[[], Any] | None = None,
        chunk_size: int = 1024,
        sample_rate: int = 16000,
        on_audio_chunk: Callable[[bytes], None] | None = None,
    ) -> None:
        self._microphone_factory = microphone_factory or sr.Microphone
        self._chunk_size = chunk_size
        self._sample_rate = sample_rate
        self._on_audio_chunk = on_audio_chunk
        self._stream = None
        self._thread = None
        self._microphone = None
        self._is_running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start capturing audio from the microphone in a background thread."""
        with self._lock:
            if self._is_running:
                return

            try:
                self._microphone = self._microphone_factory(
                    sample_rate=self._sample_rate, chunk_size=self._chunk_size
                )
                self._stream = self._microphone.__enter__()
                self._is_running = True
                self._thread = threading.Thread(target=self._capture_loop)
                self._thread.daemon = True
                self._thread.start()
            except Exception:
                raise

    def stop(self) -> None:
        """Stop capturing audio."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False

        if self._thread:
            self._thread.join()
            self._thread = None

    def shutdown(self) -> None:
        """Release all microphone resources."""
        self.stop()
        with self._lock:
            if self._microphone:
                self._microphone.__exit__(None, None, None)
            self._stream = None
            self._microphone = None

    def _capture_loop(self) -> None:
        """Continuously read from the stream and process the data."""
        while self._is_running:
            try:
                audio_chunk = self._stream.read(self._chunk_size)
                if self._on_audio_chunk:
                    self._on_audio_chunk(audio_chunk)
            except IOError:
                # This can happen if the buffer is overflown.
                # We will just ignore it and continue.
                pass
            except Exception:
                # In case of other errors, we should probably stop.
                self._is_running = False
        time.sleep(0.1)
