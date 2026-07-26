"""
ui/run_ui.py

Entry point for the JARVIS desktop UI.
Creates the bridge, wires it to live backend services, and launches
the full-screen QML window.

Usage:
    python -m ui.run_ui
"""

from __future__ import annotations

import logging
import threading
import time

from ui.bridge import Bridge
from ui.main_window import launch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ui.run_ui")


def _demo_loop(bridge: Bridge) -> None:
    """Demonstration: cycles through modes and updates status.

    Replace this with real backend integration.
    """
    modes = ["idle", "listening", "thinking", "speaking"]
    idx = 0

    while True:
        time.sleep(6)
        bridge.set_mode(modes[idx % len(modes)])
        idx += 1

        if idx % 2 == 0:
            bridge.set_cpu_usage(12.0 + idx * 5.0)
            bridge.set_memory_usage(45.0 + idx * 3.0)
            bridge.show_subtitle(
                "I'm running on my local knowledge base. "
                "What would you like to know?"
            )
        else:
            bridge.set_cpu_usage(8.0)
            bridge.set_memory_usage(42.0)
            bridge.show_subtitle("")

        if idx % 4 == 1:
            bridge.wakeActive = True
            bridge.show_subtitle("")
        else:
            bridge.wakeActive = False


def main() -> None:
    bridge = Bridge()

    bridge.set_internet_status(True)
    bridge.set_mic_status(True)
    bridge.set_provider_status(True)
    bridge.set_llm_status(True)
    bridge.set_cpu_usage(8.0)
    bridge.set_memory_usage(42.0)

    threading.Thread(
        target=_demo_loop, args=(bridge,), daemon=True
    ).start()

    exit_code = launch(bridge)
    logger.info("UI exited with code %d", exit_code)


if __name__ == "__main__":
    main()
