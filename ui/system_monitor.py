"""
ui/system_monitor.py — Background system resource monitor.

Runs on a dedicated daemon thread (NOT the Qt MainThread).
Polls CPU, RAM, GPU, Disk, and Battery periodically.
Sends results to Bridge via cross-thread signal emission (auto-queued to UI thread).

The Qt MainThread must NEVER call:
  - win32com / wmi
  - psutil functions that may block
  - subprocess
  - network requests
  - time.sleep (blocking)
"""

from __future__ import annotations

import logging
import threading
import time

import psutil

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 2.0
_THROTTLE_DELTA = 0.5  # minimum change to emit an update


class SystemMonitor:
    """Polls system resources on a daemon background thread.

    Call ``start()`` after creating the Bridge to begin polling.
    Call ``stop()`` during shutdown.
    """

    def __init__(self, bridge) -> None:
        self._bridge = bridge
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="system-monitor", daemon=True,
        )
        # GPU monitoring state (lazy initialised on background thread)
        self._has_nvml = False
        self._nvml_handle = None
        self._has_wmi_gpu = False
        self._wmi_client = None
        self._wmi_initialised = False

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        logger.info("SystemMonitor: starting background poll thread")
        self._thread.start()

    def stop(self, join_timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            join_start = time.monotonic()
            self._thread.join(timeout=join_timeout)
            elapsed = (time.monotonic() - join_start) * 1000
            if self._thread.is_alive():
                logger.error(
                    "SystemMonitor: thread failed to stop within %.0fms — "
                    "continuing shutdown", elapsed,
                )
            else:
                logger.info(
                    "SystemMonitor: thread stopped in %.0fms", elapsed,
                )

    # ── Background loop ────────────────────────────────────────────────

    def _run(self) -> None:
        logger.info("SystemMonitor: thread '%s' started", threading.current_thread().name)
        self._init_gpu()
        self._sample()
        while not self._stop.is_set():
            if self._stop.wait(_POLL_INTERVAL):
                break
            self._sample()
        logger.info(
            "SystemMonitor: thread '%s' stopped",
            threading.current_thread().name,
        )

    def _init_gpu(self) -> None:
        """Initialise GPU monitoring (runs once on background thread)."""
        # --- NVML (NVIDIA) ---
        try:
            import pynvml  # type: ignore[import-untyped]
            pynvml.nvmlInit()
            self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._has_nvml = True
            logger.info("SystemMonitor: NVML GPU monitoring initialized")
        except Exception:
            self._nvml_handle = None

    def _ensure_wmi(self) -> None:
        """Lazy WMI initialisation (runs on background thread)."""
        if self._wmi_initialised:
            return
        self._wmi_initialised = True
        try:
            import pythoncom  # type: ignore[import-untyped]
            import wmi  # type: ignore[import-untyped]
            pythoncom.CoInitialize()
            self._wmi_client = wmi.WMI()
            test = self._wmi_client.Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine()
            if test:
                self._has_wmi_gpu = True
                logger.info("SystemMonitor: WMI GPU monitoring initialized")
        except Exception:
            self._wmi_client = None

    # ── Sampling ──────────────────────────────────────────────────────

    def _sample(self) -> None:
        """Poll all resources and send results to Bridge via Qt signals.

        All Bridge setter calls happen from this background thread.
        The Qt signal emissions (cpuUsageChanged, etc.) are automatically
        queued to the main thread by PySide6's cross-thread signal mechanism.
        Python's GIL guarantees atomic float assignment for the internal
        ``_cpu`` / ``_ram`` / ``_gpu`` attributes.
        """
        bridge = self._bridge

        cpu = self._read_cpu()
        if cpu is not None:
            bridge.set_cpu_usage(cpu)

        ram = self._read_ram()
        if ram is not None:
            bridge.set_ram_usage(ram)

        gpu = self._read_gpu()
        if gpu is not None:
            bridge.set_gpu_usage(gpu)

        disk = self._read_disk()
        if disk is not None:
            bridge.set_disk_usage(disk)

        battery = self._read_battery()
        if battery is not None:
            bridge.set_battery(battery)

    # ── Individual readers (all run on background thread) ─────────────

    @staticmethod
    def _read_cpu() -> float | None:
        try:
            return psutil.cpu_percent(interval=0)
        except Exception:
            return None

    @staticmethod
    def _read_ram() -> float | None:
        try:
            return psutil.virtual_memory().percent
        except Exception:
            return None

    def _read_gpu(self) -> float | None:
        if self._has_nvml:
            try:
                import pynvml  # type: ignore[import-untyped]
                return float(pynvml.nvmlDeviceGetUtilizationRates(self._nvml_handle).gpu)
            except Exception:
                pass

        self._ensure_wmi()
        if self._has_wmi_gpu and self._wmi_client is not None:
            try:
                total = 0
                for e in self._wmi_client.Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine():
                    if 'engtype_3D' in e.Name:
                        v = e.UtilizationPercentage
                        if v is not None:
                            total += int(v)
                return min(float(total), 100.0)
            except Exception:
                pass
        return None

    @staticmethod
    def _read_disk() -> float | None:
        try:
            return psutil.disk_usage('/').percent
        except Exception:
            return None

    @staticmethod
    def _read_battery() -> float | None:
        try:
            batt = psutil.sensors_battery()
            return float(batt.percent) if batt is not None else -1.0
        except Exception:
            return -1.0
