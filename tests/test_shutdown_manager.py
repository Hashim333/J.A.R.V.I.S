from __future__ import annotations

import threading
from unittest import TestCase

from services.shutdown_manager import ShutdownManager


class TestShutdownManager(TestCase):
    def test_phases_defined(self) -> None:
        sm = ShutdownManager()
        self.assertGreater(len(sm.PHASES), 0)

    def test_shutdown_runs_all_hooks(self) -> None:
        sm = ShutdownManager()
        order: list[str] = []

        for name, _ in sm.PHASES:
            sm.on(name, lambda n=name: order.append(n))

        sm.shutdown()
        expected = [name for name, _ in sm.PHASES]
        self.assertEqual(order, expected)

    def test_hook_exception_does_not_crash(self) -> None:
        sm = ShutdownManager()
        sm.on("stop_listening", lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        sm.shutdown()

    def test_register_and_join_threads(self) -> None:
        sm = ShutdownManager()
        done = threading.Event()

        def worker():
            done.wait(timeout=5.0)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        sm.register_thread(t)
        done.set()
        sm._join_threads()
        self.assertFalse(t.is_alive())

    def test_shutdown_returns_total_time(self) -> None:
        sm = ShutdownManager()
        total = sm.shutdown()
        self.assertGreaterEqual(total, 0.0)

    def test_empty_shutdown_does_not_error(self) -> None:
        sm = ShutdownManager()
        total = sm.shutdown()
        self.assertIsInstance(total, float)
