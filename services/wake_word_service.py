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

import threading
import time

from services.base_service import BaseService


class WakeWordService(BaseService):
    """
    A placeholder wake word service that runs a loop in a background
    thread.
    """

    def __init__(self) -> None:
        super().__init__(name="wake_word")
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def initialize(self) -> None:
        """
        One-time setup. For now, this is a no-op. Future versions
        would load models here.
        """
        pass

    def start(self) -> None:
        """
        Start the background thread if it is not already running.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return  # Already running

            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """
        Signal the background thread to stop and wait for it to exit.
        """
        with self._lock:
            if self._thread is None:
                return  # Already stopped

            self._stop_event.set()
            thread = self._thread

        thread.join(timeout=5.0)
        with self._lock:
            self._thread = None

    def shutdown(self) -> None:
        """
        Ensure the service is stopped cleanly on application exit.
        """
        self.stop()

    def _run(self) -> None:
        """
        The main loop for the background thread.
        """
        while not self._stop_event.is_set():
            time.sleep(0.1)