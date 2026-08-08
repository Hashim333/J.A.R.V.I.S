"""
ui/monitor.py — UI Freeze Detection & Instrumentation.

DOES NOT FIX ANYTHING. Only detects, measures, and reports.

Strategy:
  - 200ms heartbeat timer on the Qt event loop to detect stalls
  - If heartbeat gap > 500ms, the UI thread was blocked
  - If heartbeat gap > 5s, freeze detected → auto-collect dump
  - Global exception hook captures crashes on any thread
  - Freeze dump includes: all thread stacks, bridge state, blocking calls

Bridge Signal/Slot instrumentation is NOT done here because wrapping
Qt Signal objects breaks their internal machinery.

Usage:
    from ui.monitor import UIMonitor
    monitor = UIMonitor(app, bridge)
    monitor.install()
"""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
import time
import traceback

logger = logging.getLogger(__name__)

_FREEZE_DUMP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ui_freeze_dump.log",
)

_HEARTBEAT_INTERVAL_S = 0.2  # 200ms heartbeat
_STALL_WARN_MS = 500  # warn if gap > 500ms (UI thread was blocked)
_FREEZE_THRESHOLD_S = 5.0  # freeze if gap > 5s


class UIMonitor:
    """Instruments the Qt UI thread to detect freezes and collect dumps."""

    def __init__(self, app, bridge) -> None:
        self._app = app
        self._bridge = bridge
        self._main_thread = threading.current_thread()
        self._main_thread_id = threading.get_ident()
        self._last_heartbeat = time.monotonic()
        self._heartbeat_count = 0
        self._stalled = False
        self._stall_warnings: list[dict] = []
        self._installed = False
        self._hb_timer = None
        # Stack sampler: background thread captures main thread stacks periodically
        self._sampler_stacks: list[dict] = []
        self._sampler_lock = threading.Lock()
        self._sampler_stop = threading.Event()

    def install(self) -> None:
        if self._installed:
            return
        self._installed = True

        # Enable faulthandler to dump tracebacks on crash
        faulthandler.enable()

        # Start heartbeat monitor (runs on UI thread via QTimer)
        self._start_heartbeat()

        # Start background stack sampler
        self._start_stack_sampler()

        # Install global exception hook
        sys.excepthook = self._crash_handler

        logger.info(
            "[UI MONITOR] Installed | thread=%s id=%d heartbeat=%.1fs",
            self._main_thread.name, self._main_thread_id,
            _HEARTBEAT_INTERVAL_S,
        )

    def _start_stack_sampler(self) -> None:
        """Start a background thread that captures the main thread stack every 500ms."""
        def _sampler():
            while not self._sampler_stop.is_set():
                frame = sys._current_frames().get(self._main_thread_id)
                if frame is not None:
                    stack = traceback.extract_stack(frame)
                    frames = [
                        {"file": f.filename, "line": f.lineno, "name": f.name, "code": f.line}
                        for f in stack[-5:]  # last 5 frames to save memory
                    ]
                    with self._sampler_lock:
                        self._sampler_stacks.append({
                            "time": time.monotonic(),
                            "frames": frames,
                        })
                        if len(self._sampler_stacks) > 30:
                            self._sampler_stacks.pop(0)
                self._sampler_stop.wait(0.5)  # 500ms sample interval
        t = threading.Thread(target=_sampler, name="ui-stack-sampler", daemon=True)
        t.start()

    # ── Heartbeat monitor ─────────────────────────────────────────────

    def stop(self) -> None:
        """Stop the heartbeat timer and the stack sampler."""
        if self._hb_timer is not None:
            self._hb_timer.stop()
            self._hb_timer = None
        self._sampler_stop.set()
        logger.debug("[UI MONITOR] Stopped")

    def _start_heartbeat(self) -> None:
        """Start a QTimer-based heartbeat on the UI thread."""
        from PySide6.QtCore import QTimer, Qt

        self._hb_timer = QTimer()
        self._hb_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._hb_timer.timeout.connect(self._heartbeat_tick)
        self._hb_timer.start(int(_HEARTBEAT_INTERVAL_S * 1000))

    def _heartbeat_tick(self) -> None:
        """Called every 100ms on the UI thread. Detects stalls."""
        now = time.monotonic()
        gap = now - self._last_heartbeat
        self._heartbeat_count += 1
        self._last_heartbeat = now

        gap_ms = gap * 1000

        if gap_ms > _FREEZE_THRESHOLD_S * 1000:
            # ── FREEZE DETECTED (>5s gap) ──
            self._stalled = True
            logger.critical(
                "[UI FREEZE] Heartbeat gap=%.0fms (%.1fs) — collecting dump",
                gap_ms, gap,
            )
            self._dump_freeze()
            return

        if gap_ms > _STALL_WARN_MS:
            # ── UI thread was blocked temporarily ──
            blocked_ms = gap_ms - (_HEARTBEAT_INTERVAL_S * 1000)
            record = {
                "gap_ms": round(gap_ms, 1),
                "blocked_ms": round(blocked_ms, 1),
                "heartbeat": self._heartbeat_count,
                "timestamp": time.time(),
            }
            self._stall_warnings.append(record)
            if len(self._stall_warnings) > 100:
                self._stall_warnings.pop(0)

            logger.warning(
                "[UI BLOCKED] Gap=%.0fms (blocked for ~%.0fms) heartbeat#=%d",
                gap_ms, blocked_ms, self._heartbeat_count,
            )

        # Health check every 50 heartbeats (10s at 200ms interval)
        if self._heartbeat_count % 50 == 0:
            self._log_health()

    # ── Freeze dump ───────────────────────────────────────────────────

    def _dump_freeze(self) -> None:
        """Collect comprehensive freeze dump to ui_freeze_dump.log."""
        lines = []
        lines.append("=" * 70)
        lines.append(f"UI FREEZE DUMP — {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"  Heartbeat count: {self._heartbeat_count}")
        lines.append(f"  Main thread: {self._main_thread.name} (id={self._main_thread_id})")
        lines.append("=" * 70)
        lines.append("")

        # ── Python stack traces for ALL threads ──
        lines.append("─── ALL THREAD STACK TRACES ───")
        for thread_id, stack in sys._current_frames().items():
            thread_name = ""
            for t in threading.enumerate():
                if t.ident == thread_id:
                    thread_name = t.name
                    break
            lines.append(f"\nThread ID={thread_id} Name={thread_name}:")
            for filename, lineno, name, line in traceback.extract_stack(stack):
                lines.append(f"  File: {filename}:{lineno} in {name}")
                if line:
                    lines.append(f"    {line.strip()}")

        # ── Stack sampler history (last 20 samples before freeze) ──
        lines.append("\n─── STACK SAMPLER HISTORY (last 20 samples, 200ms intervals) ───")
        with self._sampler_lock:
            samples = list(self._sampler_stacks)
        now = time.monotonic()
        for i, sample in enumerate(samples[-20:]):
            age_s = now - sample["time"]
            lines.append(f"\n  Sample {i}: {age_s*1000:.0f}ms ago (heartbeat# ~{self._heartbeat_count - len(samples) + i})")
            for frame in sample["frames"]:
                code = frame["code"] or ""
                lines.append(f"    File: {frame['file']}:{frame['line']} in {frame['name']} | {code}")

        # ── Thread states ──
        lines.append("\n─── THREAD STATES ───")
        for t in threading.enumerate():
            lines.append(f"  {t.name} (id={t.ident}) alive={t.is_alive()} daemon={t.daemon}")

        # ─── Active locks (from thread objects) ──
        lines.append("\n─── ACTIVE LOCKS ───")
        for t in threading.enumerate():
            if hasattr(t, "_lock") and t._lock is not None:
                lines.append(f"  {t.name}: lock={t._lock}")

        # ── Bridge state snapshot ──
        lines.append("\n─── APPLICATION STATE ───")
        try:
            b = self._bridge
            lines.append(f"  Bridge._core_state: {getattr(b, '_core_state', 'N/A')}")
            lines.append(f"  Bridge._window_mode: {getattr(b, '_window_mode', 'N/A')}")
            lines.append(f"  Bridge._wake_active: {getattr(b, '_wake_active', 'N/A')}")
            lines.append(f"  Bridge._conversation_history len: {len(getattr(b, '_conversation_history', []))}")
            lines.append(f"  Bridge._cpu: {getattr(b, '_cpu', 'N/A')}")
            lines.append(f"  Bridge._ram: {getattr(b, '_ram', 'N/A')}")
            lines.append(f"  Bridge._gpu: {getattr(b, '_gpu', 'N/A')}")
            lines.append(f"  Bridge._task: {getattr(b, '_task', 'N/A')}")
            lines.append(f"  Bridge._provider: {getattr(b, '_provider', 'N/A')}")
            lines.append(f"  Bridge._model: {getattr(b, '_model', 'N/A')}")
            lines.append(f"  Bridge._internet_ok: {getattr(b, '_internet_ok', 'N/A')}")
            lines.append(f"  Bridge._mic_ok: {getattr(b, '_mic_ok', 'N/A')}")
            lines.append(f"  Bridge._speaker_ok: {getattr(b, '_speaker_ok', 'N/A')}")
        except Exception as exc:
            lines.append(f"  Error reading bridge state: {exc}")

        # ── Recent stall warnings (last 20) ──
        lines.append("\n─── RECENT STALL WARNINGS (last 20) ───")
        for rec in self._stall_warnings[-20:]:
            lines.append(
                f"  Gap={rec['gap_ms']}ms Blocked={rec['blocked_ms']}ms "
                f"heartbeat#={rec['heartbeat']}"
            )

        # ── QApplication info ──
        lines.append("\n─── QAPPLICATION STATE ───")
        try:
            lines.append(f"  Application: {self._app.applicationName()}")
            lines.append(f"  QuitOnLastWindowClosed: {self._app.quitOnLastWindowClosed()}")
        except Exception as exc:
            lines.append(f"  Error: {exc}")

        lines.append("\n" + "=" * 70)
        lines.append("END FREEZE DUMP")
        lines.append("=" * 70)

        dump_text = "\n".join(lines)

        # Write to file
        try:
            with open(_FREEZE_DUMP_PATH, "w", encoding="utf-8") as f:
                f.write(dump_text)
            logger.info("[UI MONITOR] Freeze dump written to %s", _FREEZE_DUMP_PATH)
        except Exception as exc:
            logger.error("[UI MONITOR] Failed to write freeze dump: %s", exc)

    # ── Exception handler ─────────────────────────────────────────────

    def _crash_handler(
        self, exc_type: type, exc_value: Exception, exc_tb: object,
    ) -> None:
        """Global exception hook — captures crashes on any thread."""
        thread = threading.current_thread()
        logger.critical(
            "[UI CRASH] Unhandled %s on thread=%s: %s",
            exc_type.__name__, thread.name, exc_value,
        )
        if exc_tb:
            for line in traceback.format_tb(exc_tb):
                logger.critical("[UI CRASH]   %s", line.rstrip())
        self._dump_freeze()
        # Call original exception hook
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    # ── Health logging ────────────────────────────────────────────────

    def _log_health(self) -> None:
        """Periodic health check — emitted every 10s."""
        uptime = self._heartbeat_count * _HEARTBEAT_INTERVAL_S
        logger.debug(
            "[UI HEALTH] heartbeat#=%d uptime=%.0fs stalls=%d warnings=%d",
            self._heartbeat_count, uptime,
            self._stalled, len(self._stall_warnings),
        )

    # ── Query ─────────────────────────────────────────────────────────

    @property
    def is_main_thread(self) -> bool:
        return threading.current_thread() is self._main_thread

    @property
    def stall_detected(self) -> bool:
        return self._stalled

    def get_stall_warnings(self) -> list[dict]:
        return list(self._stall_warnings)
