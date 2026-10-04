"""Cross-process instance ownership with an informational PID file."""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class InstanceGuard:
    """Hold a named Windows mutex for the lifetime of the backend process."""

    def __init__(self, project_dir: Path, mutex_name: str) -> None:
        self._project_dir = project_dir
        self._mutex_name = mutex_name
        self._pid_file = project_dir / ".jarvis_backend.pid"
        self._handle = None
        self._kernel32 = None
        self._posix_lock = None

    def acquire(self) -> bool:
        if os.name == "nt":
            import ctypes

            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create_mutex = self._kernel32.CreateMutexW
            create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
            create_mutex.restype = ctypes.c_void_p
            ctypes.set_last_error(0)
            handle = create_mutex(None, True, self._mutex_name)
            error = ctypes.get_last_error()
            if not handle:
                raise ctypes.WinError(error)
            if error == 183:
                self._kernel32.CloseHandle(handle)
                return False
            self._handle = handle
        else:
            import fcntl

            lock_path = self._project_dir / ".jarvis_backend.lock"
            self._posix_lock = lock_path.open("a+")
            try:
                fcntl.flock(self._posix_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self._posix_lock.close()
                self._posix_lock = None
                return False

        try:
            self._pid_file.write_text(str(os.getpid()), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write diagnostic PID file: %s", exc)
        return True

    @staticmethod
    def notify_primary(server_name: str, timeout_ms: int = 30000) -> bool:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtNetwork import QLocalSocket

        app = QCoreApplication.instance() or QCoreApplication([])
        socket = QLocalSocket()
        socket.connectToServer(server_name)
        if not socket.waitForConnected(timeout_ms):
            return False
        if socket.write(b"SHOW\n") != 5:
            return False
        socket.flush()
        if not socket.waitForReadyRead(timeout_ms):
            return False
        acknowledged = bytes(socket.readAll()).strip().upper() == b"OK"
        socket.disconnectFromServer()
        del app
        return acknowledged

    def release(self) -> None:
        try:
            if self._pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
                self._pid_file.unlink()
        except OSError:
            pass

        if self._handle is not None:
            self._kernel32.ReleaseMutex(self._handle)
            self._kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._posix_lock is not None:
            self._posix_lock.close()
            self._posix_lock = None
