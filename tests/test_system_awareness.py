"""
tests/test_system_awareness.py — Unit tests for the System Awareness Service.

Organised per-layer:
  1. Data model (immutability, convenience queries)
  2. Instant answers (deterministic question → answer mapping)
  3. Collectors (structure validation, in isolation)
  4. Service orchestrator (lifecycle, fragment merging, thread safety)
  5. Pipeline integration (awareness gate answers instantly; actions pass through)
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

from system_awareness import (
    SystemAwarenessService,
    SystemAwarenessSnapshot,
    answer,
    describe,
)
from system_awareness.model import (
    BatteryInfo,
    MediaSessionInfo,
    NetworkInfo,
    ProcessInfo,
    StorageInfo,
    WindowInfo,
)
from world_model.collectors import BaseCollector


def _snapshot(**overrides) -> SystemAwarenessSnapshot:
    """Build a realistic snapshot with a couple of default facts."""
    defaults = dict(
        timestamp=time.time(),
        processes=[
            ProcessInfo(pid=1, name="chrome.exe", cpu_percent=55.0, memory_mb=800.0,
                        memory_percent=20.0, create_time=time.time(), started_today=True,
                        exe="C:\\chrome.exe"),
            ProcessInfo(pid=2, name="notepad.exe", cpu_percent=5.0, memory_mb=120.0,
                        memory_percent=3.0, create_time=time.time() - 4000,
                        started_today=False, exe="C:\\notepad.exe"),
        ],
        top_cpu_processes=[
            ProcessInfo(pid=1, name="chrome.exe", cpu_percent=55.0, memory_mb=800.0,
                        memory_percent=20.0, create_time=time.time(), started_today=True,
                        exe=""),
        ],
        top_ram_processes=[
            ProcessInfo(pid=1, name="chrome.exe", cpu_percent=55.0, memory_mb=800.0,
                        memory_percent=20.0, create_time=time.time(), started_today=True,
                        exe=""),
        ],
        processes_started_today=[
            ProcessInfo(pid=1, name="chrome.exe", cpu_percent=55.0, memory_mb=800.0,
                        memory_percent=20.0, create_time=time.time(), started_today=True,
                        exe=""),
        ],
        windows=[
            WindowInfo(hwnd=1, pid=1, title="Chrome - Example", is_active=True, is_visible=True),
            WindowInfo(hwnd=2, pid=1, title="Chrome - Docs", is_active=False, is_visible=True),
            WindowInfo(hwnd=3, pid=3, title="Notepad", is_active=False, is_visible=True),
        ],
        focused_window="Chrome - Example",
        network=NetworkInfo(connected=True, wifi_ssid="HomeWiFi", wifi_signal_percent=80.0,
                            download_bytes_per_sec=2_500_000, upload_bytes_per_sec=500_000,
                            ipv4=["192.168.1.10"]),
        battery=BatteryInfo(percent=82.0, charging=True, time_remaining_seconds=7200,
                            health_percent=95.0, present=True),
        storage=[StorageInfo(drive="C", total_gb=512.0, used_gb=400.0,
                             free_gb=112.0, percent=78.0)],
        media_sessions=[MediaSessionInfo(app_name="Spotify", title="Song",
                                         artist="Artist", is_playing=True)],
    )
    defaults.update(overrides)
    return SystemAwarenessSnapshot(**defaults)


# ═════════════════════════════════════════════════════════════════════
# 1. Data Model Tests
# ═════════════════════════════════════════════════════════════════════


class TestSystemAwarenessModel(unittest.TestCase):
    def test_snapshot_is_frozen(self) -> None:
        snap = SystemAwarenessSnapshot.empty()
        with self.assertRaises(AttributeError):
            snap.timestamp = 0.0  # type: ignore[misc]

    def test_empty_snapshot_defaults(self) -> None:
        snap = SystemAwarenessSnapshot.empty()
        self.assertEqual(snap.processes, [])
        self.assertEqual(snap.windows, [])
        self.assertIsNone(snap.network)
        self.assertIsNone(snap.battery)
        self.assertEqual(snap.storage, [])

    def test_process_info_frozen(self) -> None:
        p = ProcessInfo(pid=1, name="a.exe", cpu_percent=0.0, memory_mb=0.0,
                        memory_percent=0.0, create_time=0.0, started_today=False)
        with self.assertRaises(AttributeError):
            p.name = "mutated.exe"  # type: ignore[misc]

    def test_top_ram_process_query(self) -> None:
        snap = _snapshot()
        top = snap.top_ram_process()
        self.assertIsNotNone(top)
        self.assertEqual(top.name, "chrome.exe")

    def test_top_cpu_process_query(self) -> None:
        snap = _snapshot()
        self.assertEqual(snap.top_cpu_process().name, "chrome.exe")

    def test_process_named(self) -> None:
        snap = _snapshot()
        proc = snap.process_named("NOTEPAD.EXE")
        self.assertIsNotNone(proc)
        self.assertEqual(proc.name, "notepad.exe")

    def test_storage_for_drive(self) -> None:
        snap = _snapshot()
        drive = snap.storage_for_drive("C:\\")
        self.assertIsNotNone(drive)
        self.assertEqual(drive.free_gb, 112.0)


# ═════════════════════════════════════════════════════════════════════
# 2. Instant Answers
# ═════════════════════════════════════════════════════════════════════


class TestInstantAnswers(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = _snapshot()

    def test_battery_question(self) -> None:
        reply = answer(self.snap, "What is my battery?")
        self.assertIsNotNone(reply)
        self.assertIn("82%", reply)

    def test_battery_health(self) -> None:
        reply = answer(self.snap, "what's my battery health?")
        self.assertIsNotNone(reply)
        self.assertIn("95%", reply)

    def test_top_ram_question(self) -> None:
        reply = answer(self.snap, "which app uses the most RAM?")
        self.assertIsNotNone(reply)
        self.assertIn("chrome.exe", reply)

    def test_top_cpu_question(self) -> None:
        reply = answer(self.snap, "which app uses the most cpu?")
        self.assertIsNotNone(reply)
        self.assertIn("chrome.exe", reply)

    def test_top_ram_question_alt_wording(self) -> None:
        reply = answer(self.snap, "what is the top ram process?")
        self.assertIsNotNone(reply)
        self.assertIn("chrome.exe", reply)

    def test_top_cpu_question_alt_wording(self) -> None:
        reply = answer(self.snap, "which process has the top cpu usage?")
        self.assertIsNotNone(reply)
        self.assertIn("chrome.exe", reply)

    def test_tabs_question(self) -> None:
        reply = answer(self.snap, "how many chrome tabs do I have open?")
        self.assertIsNotNone(reply)
        self.assertIn("2", reply)

    def test_network_question(self) -> None:
        reply = answer(self.snap, "what network am I connected to?")
        self.assertIsNotNone(reply)
        self.assertIn("HomeWiFi", reply)

    def test_storage_question(self) -> None:
        reply = answer(self.snap, "how much free space is on my drive?")
        self.assertIsNotNone(reply)
        self.assertIn("C", reply)
        self.assertIn("112", reply)

    def test_downloads_question_no_data(self) -> None:
        # No world-model system info → honest "no data" answer, not a crash.
        snap = _snapshot(system=None)
        reply = answer(snap, "what is downloading?")
        self.assertIsNotNone(reply)
        self.assertIn("download", reply.casefold())

    def test_media_question(self) -> None:
        class _Media:
            title = "Song"
            artist = "Artist"
            volume = 0.5
            mic_active = False
        reply = answer(_snapshot(media=_Media()), "what's playing?")
        self.assertIsNotNone(reply)
        self.assertIn("Song", reply)

    def test_action_command_returns_none(self) -> None:
        # Plain action commands must NOT be answered by the awareness gate.
        self.assertIsNone(answer(self.snap, "open chrome"))
        self.assertIsNone(answer(self.snap, "close notepad"))
        self.assertIsNone(answer(self.snap, "increase volume"))
        self.assertIsNone(answer(self.snap, "turn on bluetooth"))

    def test_empty_input_returns_none(self) -> None:
        self.assertIsNone(answer(self.snap, ""))
        self.assertIsNone(answer(self.snap, None))  # type: ignore[arg-type]

    def test_battery_not_present(self) -> None:
        snap = _snapshot(battery=BatteryInfo(percent=-1.0, charging=False,
                                             time_remaining_seconds=-1.0,
                                             health_percent=None, present=False))
        reply = answer(snap, "what is my battery?")
        self.assertIsNotNone(reply)
        self.assertIn("no battery", reply.casefold())

    def test_describe_renders_summary(self) -> None:
        summary = describe(self.snap)
        self.assertIn("focused window: Chrome - Example", summary)
        self.assertIn("battery: 82%", summary)
        self.assertIn("HomeWiFi", summary)
        self.assertIn("chrome.exe", summary)

    def test_describe_empty(self) -> None:
        self.assertEqual(describe(None), "(no system awareness data)")
        self.assertEqual(describe(SystemAwarenessSnapshot.empty()),
                         "(no system awareness data)")


# ═════════════════════════════════════════════════════════════════════
# 3. Collector Structure Tests
# ═════════════════════════════════════════════════════════════════════


class TestAwarenessCollectors(unittest.TestCase):
    def test_processes_collector_structure(self) -> None:
        from system_awareness.collectors import ProcessesCollector
        result = ProcessesCollector().collect()
        self.assertIn("processes", result)
        for key in ("top_cpu_processes", "top_ram_processes", "processes_started_today"):
            self.assertIn(key, result)
            self.assertIsInstance(result[key], list)

    def test_windows_collector_structure(self) -> None:
        from system_awareness.collectors import WindowsCollector
        result = WindowsCollector().collect()
        self.assertIn("windows", result)
        self.assertIn("focused_window", result)

    def test_battery_collector_structure(self) -> None:
        from system_awareness.collectors import BatteryCollector
        result = BatteryCollector().collect()
        self.assertIn("battery", result)
        batt = result["battery"]
        self.assertIn("present", batt)
        self.assertIn("percent", batt)
        self.assertIn("charging", batt)

    def test_network_collector_structure(self) -> None:
        from system_awareness.collectors import NetworkCollector
        result = NetworkCollector().collect()
        self.assertIn("network", result)
        net = result["network"]
        self.assertIn("connected", net)
        self.assertIn("download_bytes_per_sec", net)
        self.assertIn("ipv4", net)

    def test_storage_collector_structure(self) -> None:
        from system_awareness.collectors import StorageCollector
        result = StorageCollector().collect()
        self.assertIn("storage", result)
        for drive in result["storage"]:
            self.assertIn("drive", drive)
            self.assertIn("total_gb", drive)
            self.assertIn("free_gb", drive)

    def test_service_collector_structure(self) -> None:
        from system_awareness.collectors import ServiceCollector
        result = ServiceCollector().collect()
        self.assertIn("services", result)
        for svc in result["services"]:
            self.assertIn("name", svc)

    def test_collector_error_is_contained(self) -> None:
        class _Broken(BaseCollector):
            def collect(self) -> dict:
                raise RuntimeError("boom")

        svc = SystemAwarenessService(collectors=[_Broken(poll_interval=0.1)])
        svc.start()
        time.sleep(0.3)
        svc.stop()
        # No crash; snapshot remains a valid empty snapshot.
        self.assertIsInstance(svc.current(), SystemAwarenessSnapshot)


# ═════════════════════════════════════════════════════════════════════
# 4. Service Orchestrator Tests
# ═════════════════════════════════════════════════════════════════════


class _MockCollector(BaseCollector):
    def __init__(self, fragment: dict, interval: float = 0.1) -> None:
        super().__init__(poll_interval=interval)
        self._fragment = fragment
        self.collect_count = 0

    def collect(self) -> dict:
        self.collect_count += 1
        return self._fragment


class TestSystemAwarenessService(unittest.TestCase):
    def setUp(self) -> None:
        self.fragment = {
            "battery": {"present": True, "percent": 60.0, "charging": False,
                        "time_remaining_seconds": 3600, "health_percent": 90.0},
            "windows": [{"hwnd": 1, "pid": 1, "title": "Chrome",
                         "is_active": True, "is_visible": True}],
            "focused_window": "Chrome",
        }
        self.svc = SystemAwarenessService(collectors=[_MockCollector(self.fragment)])

    def tearDown(self) -> None:
        try:
            self.svc.stop()
        except Exception:
            pass

    def test_initial_snapshot_is_empty(self) -> None:
        self.assertIsInstance(self.svc.current(), SystemAwarenessSnapshot)

    def test_start_and_stop_populates(self) -> None:
        self.svc.start()
        time.sleep(0.4)
        self.svc.stop()
        snap = self.svc.current()
        self.assertIsInstance(snap, SystemAwarenessSnapshot)
        self.assertIsNotNone(snap.battery)
        self.assertEqual(snap.battery.percent, 60.0)
        self.assertEqual(snap.focused_window, "Chrome")

    def test_snapshot_is_immutable(self) -> None:
        self.svc.start()
        time.sleep(0.4)
        self.svc.stop()
        with self.assertRaises(AttributeError):
            self.svc.current().timestamp = 0.0  # type: ignore[misc]

    def test_thread_safety(self) -> None:
        import threading
        self.svc.start()

        errors = []

        def _reader() -> None:
            for _ in range(20):
                try:
                    snap = self.svc.current()
                    self.assertIsInstance(snap, SystemAwarenessSnapshot)
                except Exception as exc:  # pragma: no cover
                    errors.append(exc)

        threads = [threading.Thread(target=_reader) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.svc.stop()
        self.assertEqual(errors, [])

    def test_poll_intervals_respected(self) -> None:
        fast = _MockCollector({"battery": {"present": True, "percent": 50.0,
                                           "charging": False, "time_remaining_seconds": -1.0,
                                           "health_percent": None}}, interval=0.1)
        slow = _MockCollector({"battery": {"present": True, "percent": 70.0,
                                           "charging": False, "time_remaining_seconds": -1.0,
                                           "health_percent": None}}, interval=0.8)
        svc = SystemAwarenessService(collectors=[fast, slow])
        svc.start()
        time.sleep(1.2)
        svc.stop()
        self.assertGreater(fast.collect_count, slow.collect_count)

    def test_world_model_reuse(self) -> None:
        wm = MagicMock()
        wm.get_snapshot.return_value.media = MagicMock(title="Song")
        wm.get_snapshot.return_value.system = MagicMock(cpu_percent=42.0)
        svc = SystemAwarenessService(collectors=[_MockCollector(self.fragment)],
                                     world_model=wm)
        svc.start()
        time.sleep(0.4)
        svc.stop()
        snap = svc.current()
        self.assertEqual(snap.media.title, "Song")
        self.assertEqual(snap.system.cpu_percent, 42.0)


# ═════════════════════════════════════════════════════════════════════
# 5. Pipeline Integration
# ═════════════════════════════════════════════════════════════════════


class _FakeAwareness:
    def __init__(self, snap: SystemAwarenessSnapshot) -> None:
        self._snap = snap

    def current(self) -> SystemAwarenessSnapshot:
        return self._snap


class TestPipelineAwarenessGate(unittest.TestCase):
    def test_system_question_answered_instantly(self) -> None:
        from brain.parser import Parser
        from brain.planner import Planner
        from thinking.pipeline import PipelineEngine

        pipeline = PipelineEngine(
            parser=Parser(),
            planner=Planner(),
            system_awareness=_FakeAwareness(_snapshot()),
        )
        response = pipeline.process("what is my battery?")
        self.assertTrue(response.success)
        self.assertEqual(response.data.get("category"), "system_awareness")
        self.assertIn("82%", response.message)

    def test_action_passes_through_gate(self) -> None:
        from brain.parser import Parser
        from brain.planner import Planner
        from models.response import Response
        from thinking.pipeline import PipelineEngine
        from thinking.reasoner import ReasonedPlan

        class _Reasoner:
            def reason(self, text, memory=None, world_state=None, awareness=None):
                return ReasonedPlan(
                    mode="ACT", intent="focus_app",
                    entities={"app_name": "chrome"}, confidence=0.95,
                )

            def continue_(self, original_text, question, answer,
                          memory=None, world_state=None, awareness=None):
                return None

        class _Exec:
            def __init__(self) -> None:
                self.plans = []

            def execute(self, plan, cancel_event=None):
                self.plans.append(plan)
                return Response(success=True, message="Focused Chrome.", data={})

        exec_ = _Exec()
        pipeline = PipelineEngine(
            parser=Parser(),
            planner=Planner(),
            executor=exec_,
            reasoner=_Reasoner(),
            system_awareness=_FakeAwareness(_snapshot()),
        )
        response = pipeline.process("focus chrome")
        # Action command should not be hijacked by the awareness gate.
        self.assertNotEqual(response.data.get("category"), "system_awareness")
        self.assertTrue(response.success)
        self.assertEqual(len(exec_.plans), 1)

    def test_no_awareness_service_falls_through(self) -> None:
        from brain.parser import Parser
        from brain.planner import Planner
        from thinking.pipeline import PipelineEngine

        pipeline = PipelineEngine(parser=Parser(), planner=Planner())
        response = pipeline.process("what is my battery?")
        # Without awareness wiring, the normal (non-aware) path runs — still
        # returns a valid Response rather than raising.
        self.assertIsNotNone(response)


if __name__ == "__main__":
    unittest.main()
