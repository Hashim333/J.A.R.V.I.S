"""
dev_tests/test_service_manager.py

Unit tests for services/service_manager.py and services/base_service.py.

Covers:
    - register()
    - duplicate registration
    - initialize_all()
    - start_all()
    - stop_all()
    - shutdown_all()
    - restart()
    - get_status()
    - list_services()
    - failure isolation

These tests use lightweight fake BaseService subclasses defined in
this file only -- no real background service (voice, vision, etc.)
exists yet, and this file does not import or depend on any of them.
"""

from __future__ import annotations

import unittest

from services.base_service import BaseService, ServiceStatus
from services.service_manager import ServiceManager


class FakeService(BaseService):
    """A BaseService that records calls and never fails."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.calls: list[str] = []

    def initialize(self) -> None:
        self.calls.append("initialize")

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> None:
        self.calls.append("stop")

    def shutdown(self) -> None:
        self.calls.append("shutdown")


class FailingService(BaseService):
    """A BaseService whose start() always raises."""

    def initialize(self) -> None:
        pass

    def start(self) -> None:
        raise RuntimeError("start failed")

    def stop(self) -> None:
        pass


class TestServiceManagerRegister(unittest.TestCase):
    """Tests for ServiceManager.register()."""

    def test_register_adds_service(self) -> None:
        manager = ServiceManager()
        service = FakeService("dummy")

        manager.register("dummy", service)

        self.assertIn("dummy", manager.list_services())

    def test_register_rejects_empty_name(self) -> None:
        manager = ServiceManager()
        service = FakeService("dummy")

        with self.assertRaises(ValueError):
            manager.register("", service)

    def test_register_rejects_non_base_service(self) -> None:
        manager = ServiceManager()

        with self.assertRaises(TypeError):
            manager.register("not_a_service", object())

    def test_duplicate_registration_replaces_existing(self) -> None:
        manager = ServiceManager()
        first = FakeService("dummy")
        second = FakeService("dummy")

        manager.register("dummy", first)
        manager.register("dummy", second)

        self.assertEqual(len(manager.list_services()), 1)
        manager.start_all()
        self.assertIn("start", second.calls)
        self.assertNotIn("start", first.calls)


class TestServiceManagerLifecycle(unittest.TestCase):
    """Tests for initialize_all(), start_all(), stop_all(), shutdown_all()."""

    def setUp(self) -> None:
        self.manager = ServiceManager()
        self.service = FakeService("dummy")
        self.manager.register("dummy", self.service)

    def test_initialize_all_calls_initialize(self) -> None:
        results = self.manager.initialize_all()

        self.assertEqual(results["dummy"], "ok")
        self.assertIn("initialize", self.service.calls)
        self.assertEqual(self.manager.get_status("dummy"), ServiceStatus.STOPPED)

    def test_start_all_calls_start_and_sets_running(self) -> None:
        self.manager.initialize_all()
        results = self.manager.start_all()

        self.assertEqual(results["dummy"], "ok")
        self.assertIn("start", self.service.calls)
        self.assertEqual(self.manager.get_status("dummy"), ServiceStatus.RUNNING)

    def test_stop_all_calls_stop_and_sets_stopped(self) -> None:
        self.manager.initialize_all()
        self.manager.start_all()
        results = self.manager.stop_all()

        self.assertEqual(results["dummy"], "ok")
        self.assertIn("stop", self.service.calls)
        self.assertEqual(self.manager.get_status("dummy"), ServiceStatus.STOPPED)

    def test_shutdown_all_calls_shutdown_and_sets_stopped(self) -> None:
        self.manager.initialize_all()
        self.manager.start_all()
        results = self.manager.shutdown_all()

        self.assertEqual(results["dummy"], "ok")
        self.assertIn("shutdown", self.service.calls)
        self.assertEqual(self.manager.get_status("dummy"), ServiceStatus.STOPPED)

    def test_lifecycle_calls_happen_in_order(self) -> None:
        self.manager.initialize_all()
        self.manager.start_all()
        self.manager.stop_all()
        self.manager.shutdown_all()

        self.assertEqual(
            self.service.calls,
            ["initialize", "start", "stop", "shutdown"],
        )


class TestServiceManagerRestart(unittest.TestCase):
    """Tests for ServiceManager.restart()."""

    def test_restart_calls_stop_then_start_and_sets_running(self) -> None:
        manager = ServiceManager()
        service = FakeService("dummy")
        manager.register("dummy", service)
        manager.initialize_all()
        manager.start_all()
        service.calls.clear()

        result = manager.restart("dummy")

        self.assertEqual(result, "ok")
        self.assertEqual(service.calls, ["stop", "start"])
        self.assertEqual(manager.get_status("dummy"), ServiceStatus.RUNNING)

    def test_restart_unknown_service_returns_error(self) -> None:
        manager = ServiceManager()

        result = manager.restart("missing")

        self.assertTrue(result.startswith("error:"))

    def test_restart_failure_sets_failed_status(self) -> None:
        manager = ServiceManager()
        manager.register("bad", FailingService("bad"))

        result = manager.restart("bad")

        self.assertTrue(result.startswith("error:"))
        self.assertEqual(manager.get_status("bad"), ServiceStatus.FAILED)


class TestServiceManagerStatusQueries(unittest.TestCase):
    """Tests for get_status() and list_services()."""

    def test_get_status_returns_none_for_unknown_service(self) -> None:
        manager = ServiceManager()

        self.assertIsNone(manager.get_status("missing"))

    def test_get_status_returns_current_status(self) -> None:
        manager = ServiceManager()
        manager.register("dummy", FakeService("dummy"))

        self.assertEqual(manager.get_status("dummy"), ServiceStatus.STOPPED)

    def test_list_services_returns_all_registered_services(self) -> None:
        manager = ServiceManager()
        manager.register("dummy_one", FakeService("dummy_one"))
        manager.register("dummy_two", FakeService("dummy_two"))

        services = manager.list_services()

        self.assertEqual(
            services,
            {
                "dummy_one": ServiceStatus.STOPPED,
                "dummy_two": ServiceStatus.STOPPED,
            },
        )

    def test_list_services_returns_empty_dict_when_none_registered(self) -> None:
        manager = ServiceManager()

        self.assertEqual(manager.list_services(), {})


class TestServiceManagerFailureIsolation(unittest.TestCase):
    """Tests that one service's failure does not affect the others."""

    def test_start_all_isolates_failure_to_one_service(self) -> None:
        manager = ServiceManager()
        good = FakeService("good")
        bad = FailingService("bad")
        manager.register("good", good)
        manager.register("bad", bad)

        results = manager.initialize_all()
        results.update(manager.start_all())

        self.assertEqual(results["good"], "ok")
        self.assertTrue(results["bad"].startswith("error:"))
        self.assertEqual(manager.get_status("good"), ServiceStatus.RUNNING)
        self.assertEqual(manager.get_status("bad"), ServiceStatus.FAILED)

    def test_stop_all_still_runs_for_remaining_services_after_failure(self) -> None:
        manager = ServiceManager()
        good = FakeService("good")
        bad = FailingService("bad")
        manager.register("good", good)
        manager.register("bad", bad)
        manager.initialize_all()
        manager.start_all()

        results = manager.stop_all()

        self.assertEqual(results["good"], "ok")
        self.assertEqual(results["bad"], "ok")
        self.assertEqual(manager.get_status("good"), ServiceStatus.STOPPED)


if __name__ == "__main__":
    unittest.main()