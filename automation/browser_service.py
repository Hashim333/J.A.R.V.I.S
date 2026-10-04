"""
automation/browser_service.py — managed Chrome lifecycle for CDP automation.

A normal Chrome window does not expose a DevTools port, so JARVIS drives a
dedicated Chrome instance started with ``--remote-debugging-port`` and its
own user-data-dir.  The instance is created lazily on first use and every
tab inside it is reused (never duplicated).

If the user already has a browser exposing a DevTools port (for example
Chrome started with ``--remote-debugging-port``), that browser is attached
to instead of launching a second one.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import psutil

from automation.cdp import CdpBrowser, CdpError

logger = logging.getLogger(__name__)

_DEFAULT_PORTS = tuple(range(9222, 9231))


class BrowserServiceError(Exception):
    """Raised when the managed browser cannot be started or reached."""


class BrowserService:
    """Lazily launched, reusable Chrome instance for CDP automation."""

    DEFAULT_PORT = 9222

    def __init__(
        self,
        port: int | None = None,
        profile_dir: str | os.PathLike | None = None,
    ) -> None:
        self._port = port if port is not None else self.DEFAULT_PORT
        self._profile_dir = Path(profile_dir) if profile_dir else self._default_profile_dir()
        self._client: CdpBrowser | None = None
        self._launch_pid: int | None = None
        self._attached_to_existing = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def port(self) -> int:
        return self._port

    @property
    def profile_dir(self) -> Path:
        return self._profile_dir

    @property
    def client(self) -> CdpBrowser:
        """Return the CDP client, ensuring the managed browser is running."""
        return self.ensure_running()

    def ensure_running(self) -> CdpBrowser:
        if self._client is not None and self._client.is_reachable():
            return self._client

        existing = self._find_existing_port()
        if existing is not None:
            self._port = existing
            self._attached_to_existing = True
            self._client = CdpBrowser(existing)
            logger.info("BrowserService: attached to existing DevTools port %d", existing)
            return self._client

        self._launch()
        client = CdpBrowser(self._port)
        if not self._wait_until_reachable():
            raise BrowserServiceError(
                f"Managed Chrome did not open a DevTools port on {self._port} in time."
            )
        self._client = client
        logger.info("BrowserService: managed Chrome ready on port %d (profile %s)",
                    self._port, self._profile_dir)
        return self._client

    def stop(self) -> bool:
        """Terminate the managed Chrome instance (does not touch other browsers).
        
        Note: By default, we do NOT kill the Chrome process on stop,
        allowing it to persist after JARVIS exits. Call stop(force=True)
        to actually terminate the browser process.
        """
        if self._attached_to_existing or self._client is None:
            self._client = None
            self._launch_pid = None
            return True
        # By default, do NOT kill the Chrome process - let it persist
        # The user can call stop(force=True) if they really want to kill it
        self._client = None
        self._launch_pid = None
        return True

    # ------------------------------------------------------------------
    # Launch helpers
    # ------------------------------------------------------------------

    def _launch(self) -> None:
        executable = self._chrome_executable()
        args = [
            f"--remote-debugging-port={self._port}",
            f"--user-data-dir={self._profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-default-apps",
            "--disable-sync",
            "--noerrdialogs",
            "--disable-extensions",
            # Don't close when JARVIS exits - use a separate process group
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-default-apps",
            "--disable-sync",
            "--noerrdialogs",
            "--disable-extensions",
            "about:blank",
        ]
        try:
            self._profile_dir.mkdir(parents=True, exist_ok=True)
            # Use DETACHED_PROCESS so Chrome survives JARVIS exit
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            DETACHED_PROCESS = 0x00000008
            proc = subprocess.Popen(
                [executable, *args],
                shell=False,
                creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
            )
        except OSError as exc:
            raise BrowserServiceError(f"Could not launch managed Chrome: {exc}") from exc
        self._launch_pid = proc.pid
        logger.info("BrowserService: launching %s with args=%s", executable, args)

    def _chrome_executable(self) -> str:
        try:
            from automation.apps import _resolve_launch_candidates
            candidates = _resolve_launch_candidates("chrome")
        except Exception as exc:
            raise BrowserServiceError(f"Chrome executable could not be resolved: {exc}") from exc
        if not candidates:
            raise BrowserServiceError("Chrome executable not found.")
        return candidates[0]

    def _find_existing_port(self) -> int | None:
        """Probe common DevTools ports and return the first reachable one."""
        for port in _DEFAULT_PORTS:
            if CdpBrowser(port).is_reachable():
                return port
        return None

    def _wait_until_reachable(self, timeout: float = 12.0) -> bool:
        deadline = time.monotonic() + timeout
        client = CdpBrowser(self._port)
        while time.monotonic() < deadline:
            if client.is_reachable():
                return True
            time.sleep(0.25)
        return False

    @staticmethod
    def _default_profile_dir() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "JARVIS" / "BrowserProfile"

    @staticmethod
    def _terminate_process_tree(pid: int) -> None:
        try:
            parent = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return
        try:
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            parent.terminate()
            gone, alive = psutil.wait_procs([parent] + children, timeout=3.0)
            for proc in alive:
                try:
                    proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_service: BrowserService | None = None
_lock = threading.Lock()


def get_browser_service() -> BrowserService:
    """Return the process-wide ``BrowserService``, creating it on first use."""
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = BrowserService()
    return _service


def stop_browser_service(force: bool = False) -> bool:
    """Stop the process-wide managed browser (safe to call repeatedly).
    
    By default, does NOT kill the Chrome process - it just disconnects.
    Pass force=True to actually terminate the browser process.
    """
    global _service
    with _lock:
        if _service is None:
            return True
        try:
            _service.stop(force=force)
        except Exception as exc:
            logger.warning("BrowserService.stop failed: %s", exc)
        finally:
            _service = None
        return True
