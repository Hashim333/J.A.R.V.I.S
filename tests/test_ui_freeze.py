"""
test_ui_freeze.py — UI Freeze Root Cause Investigation.

Instruments the Qt UI thread and runs for 30 minutes idle,
collecting freeze dumps automatically if the UI stalls.

Usage:
    python tests/test_ui_freeze.py [--duration 1800]

Do NOT fix anything. Only detect and report.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ui_freeze_test")

# ── Required imports ─────────────────────────────────────────────────
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ui.bridge import Bridge
from ui.monitor import UIMonitor
from ui.system_monitor import SystemMonitor


def _simulate_wake_word_event(bridge: Bridge) -> None:
    """Simulate a wake-word detection event on a background thread."""
    def _do():
        try:
            bridge.set_core_state("listening")
            time.sleep(0.3)
            bridge.wakeActive = True
            time.sleep(0.1)
            bridge.wakeActive = False
            bridge.set_core_state("thinking")
            time.sleep(0.5)
            bridge.show_subtitle("Processing voice command: open chrome")
            bridge.set_current_task("open chrome")
            time.sleep(1.0)
            bridge.set_current_task("")
            bridge.set_core_state("speaking")
            bridge.show_subtitle("Opening Chrome")
            time.sleep(1.0)
            bridge.set_core_state("idle")
            bridge.show_subtitle("Say 'JARVIS' or type a command.")
        except Exception as exc:
            logger.error("Simulation error: %s", exc)
    return _do


def _simulate_conversation_event(bridge: Bridge) -> None:
    """Simulate a conversation interaction on a background thread."""
    def _do():
        try:
            bridge.set_core_state("listening")
            time.sleep(0.5)
            bridge.set_core_state("thinking")
            bridge.set_current_task("search for weather")
            time.sleep(2.0)
            bridge.set_current_task("")
            bridge.set_core_state("speaking")
            bridge.show_subtitle("Searching for weather...")
            time.sleep(0.5)
            bridge.set_core_state("idle")
        except Exception as exc:
            logger.error("Conversation simulation error: %s", exc)
    return _do


def _simulate_stats_update(bridge: Bridge) -> None:
    """Simulate periodic status updates on a background thread."""
    import random
    def _do():
        try:
            bridge.set_cpu_usage(random.uniform(0, 100))
            bridge.set_ram_usage(random.uniform(0, 100))
            bridge.set_gpu_usage(random.uniform(0, 100))
            bridge.set_battery(random.uniform(0, 100))
            bridge.set_internet_status(random.choice([True, True, True, False]))
            bridge.set_mic_status(random.choice([True, True, False]))
            bridge.set_speaker_status(random.choice([True, True, False]))
        except Exception as exc:
            logger.error("Stats simulation error: %s", exc)
    return _do


def _background_simulator(bridge: Bridge, shutdown_event: threading.Event) -> None:
    """Simulate backend activity to stress the UI."""
    import random
    logger.info("Background simulator started")
    while not shutdown_event.is_set():
        event_type = random.choices(
            ["wake_word", "conversation", "stats", "none"],
            weights=[2, 1, 10, 5],
        )[0]

        if event_type == "wake_word":
            _simulate_wake_word_event(bridge)()
        elif event_type == "conversation":
            _simulate_conversation_event(bridge)()
        elif event_type == "stats":
            _simulate_stats_update(bridge)()

        time.sleep(random.uniform(0.5, 3.0))


def main() -> None:
    parser = argparse.ArgumentParser(description="UI Freeze Investigation Test")
    parser.add_argument(
        "--duration", type=int, default=1800,
        help="Test duration in seconds (default: 1800 = 30 min)",
    )
    parser.add_argument(
        "--simulate", action="store_true",
        help="Simulate backend events during idle test",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("UI FREEZE INVESTIGATION")
    logger.info("  Duration:  %d seconds (%.1f min)", args.duration, args.duration / 60)
    logger.info("  Simulate:  %s", args.simulate)
    logger.info("=" * 60)

    # ── Create Qt Application ──
    app = QApplication(sys.argv)
    app.setApplicationName("JARVIS Freeze Test")

    # ── Create Bridge ──
    bridge = Bridge()

    # ── Start background SystemMonitor (replaces old bridge-internal stats timer) ──
    sysmon = SystemMonitor(bridge)
    sysmon.start()

    # ── Install UI Monitor ──
    monitor = UIMonitor(app, bridge)
    monitor.install()

    # ── Shutdown coordination ──
    shutdown_event = threading.Event()

    # ── Background simulator (stress) ──
    sim_thread = None
    if args.simulate:
        sim_thread = threading.Thread(
            target=_background_simulator,
            args=(bridge, shutdown_event),
            daemon=True,
        )
        sim_thread.start()

    # ── Duration timer ──
    def _timeout():
        logger.info("Test duration reached — shutting down")
        shutdown_event.set()
        app.quit()

    QTimer.singleShot(args.duration * 1000, _timeout)

    # ── Periodic health check ──
    def _check_health():
        if monitor.stall_detected:
            logger.critical("UI FREEZE DETECTED during health check!")
            app.quit()
            return
        if not shutdown_event.is_set():
            QTimer.singleShot(10000, _check_health)

    QTimer.singleShot(10000, _check_health)

    # ── Run event loop ──
    logger.info("Starting UI event loop for %d seconds...", args.duration)
    exit_code = app.exec()

    # ── Report results ──
    logger.info("=" * 60)
    logger.info("UI FREEZE INVESTIGATION RESULTS")
    logger.info("=" * 60)
    logger.info("Exit code:     %d", exit_code)

    if monitor.stall_detected:
        logger.critical("RESULT: UI FREEZE DETECTED")
        logger.critical("Dump file: ui_freeze_dump.log")
        # Print the dump (re-encode to avoid cp1252 crash on box-drawing chars)
        dump_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui_freeze_dump.log")
        if os.path.exists(dump_path):
            with open(dump_path, "r", encoding="utf-8") as f:
                raw = f.read()
            try:
                print(raw)
            except UnicodeEncodeError:
                print(raw.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8"))
    else:
        logger.info("RESULT: NO UI FREEZE — UI was responsive for entire test")

    # Print stall warning summary
    stall_warnings = monitor.get_stall_warnings()
    logger.info("")
    logger.info("Stall warnings (>%dms): %d", 300, len(stall_warnings))
    for rec in stall_warnings:
        logger.info("  Gap=%.0fms Blocked=%.0fms heartbeat#=%d", rec["gap_ms"], rec["blocked_ms"], rec["heartbeat"])

    if monitor.stall_detected:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
