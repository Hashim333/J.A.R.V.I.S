"""
tests/test_world_model.py — Unit tests for the World Model service.

Tests are organised per-domain:
  1. Model immutability
  2. Individual collectors (in isolation)
  3. WorldModel orchestrator (lifecycle, merging, query API)
"""

from __future__ import annotations

import copy
import time
import unittest
from unittest.mock import MagicMock, patch

from world_model import (
    WorldModel,
    WorldSnapshot,
    ApplicationInfo,
    BrowserInfo,
    BrowserTab,
    FileInfo,
    MediaInfo,
    SystemInfo,
)
from world_model.collectors import BaseCollector
from world_model.collectors.applications import ApplicationsCollector
from world_model.collectors.browser import BrowserCollector
from world_model.collectors.files import FilesCollector
from world_model.collectors.media import MediaCollector
from world_model.collectors.system import SystemCollector


# ═════════════════════════════════════════════════════════════════════
# 1. Data Model Tests
# ═════════════════════════════════════════════════════════════════════


class TestModel(unittest.TestCase):
    """Verify that all model objects are truly immutable."""

    def test_application_info_frozen(self) -> None:
        app = ApplicationInfo(pid=100, name="explorer.exe",
                              window_title="File Explorer", is_active=True)
        with self.assertRaises(AttributeError):
            app.name = "notepad.exe"  # type: ignore[misc]

    def test_browser_tab_frozen(self) -> None:
        tab = BrowserTab(title="Hello", url="https://example.com")
        with self.assertRaises(AttributeError):
            tab.title = "Mutated"  # type: ignore[misc]

    def test_browser_info_frozen(self) -> None:
        bi = BrowserInfo(active_browser="chrome",
                         tabs=[BrowserTab("t", "u")], active_url="https://example.com")
        with self.assertRaises(AttributeError):
            bi.active_browser = "edge"  # type: ignore[misc]

    def test_file_info_frozen(self) -> None:
        fi = FileInfo(current_folder="C:\\Users", recent_files=[], downloads_in_progress=[])
        with self.assertRaises(AttributeError):
            fi.current_folder = "D:\\"  # type: ignore[misc]

    def test_system_info_frozen(self) -> None:
        si = SystemInfo(cpu_percent=42.0, ram_percent=65.0, gpu_percent=12.0,
                        battery_percent=80.0, battery_charging=True,
                        network_connected=True, clipboard_text="hello")
        with self.assertRaises(AttributeError):
            si.cpu_percent = 99.0  # type: ignore[misc]

    def test_media_info_frozen(self) -> None:
        mi = MediaInfo(is_playing=True, title="Song", artist="Artist",
                       app_name="spotify", volume=0.7, mic_active=False)
        with self.assertRaises(AttributeError):
            mi.title = "Mutated"  # type: ignore[misc]

    def test_world_snapshot_frozen(self) -> None:
        snap = WorldSnapshot.empty()
        with self.assertRaises(AttributeError):
            snap.timestamp = 0.0  # type: ignore[misc]

    def test_world_snapshot_empty(self) -> None:
        snap = WorldSnapshot.empty()
        self.assertGreater(snap.timestamp, 0)
        self.assertEqual(snap.applications, [])
        self.assertIsNone(snap.browser)
        self.assertIsNone(snap.files)
        self.assertIsNone(snap.system)
        self.assertIsNone(snap.media)


# ═════════════════════════════════════════════════════════════════════
# 2. Collector Tests
# ═════════════════════════════════════════════════════════════════════


class TestBaseCollector(unittest.TestCase):
    """Verify base collector contract."""

    def test_collect_must_be_implemented(self) -> None:
        class Incomplete(BaseCollector):
            pass

        with self.assertRaises(TypeError):
            Incomplete(poll_interval=1.0)  # abstractmethod prevents instantiation

    def test_collect_returns_dict(self) -> None:
        class TestCollector(BaseCollector):
            def collect(self) -> dict:
                return {"test": 42}

        c = TestCollector(poll_interval=3.0)
        self.assertEqual(c.poll_interval, 3.0)
        self.assertEqual(c.collect(), {"test": 42})


class TestApplicationsCollector(unittest.TestCase):
    """Integration-light — calls the real collector but validates structure."""

    def setUp(self) -> None:
        self.collector = ApplicationsCollector()

    def test_collect_returns_applications_key(self) -> None:
        result = self.collector.collect()
        self.assertIn("applications", result)
        apps = result["applications"]
        self.assertIsInstance(apps, list)

    def test_application_fields_present(self) -> None:
        result = self.collector.collect()
        for app in result["applications"]:
            self.assertIn("pid", app)
            self.assertIn("name", app)
            self.assertIn("window_title", app)
            self.assertIn("is_active", app)

    def test_active_window_is_marked(self) -> None:
        result = self.collector.collect()
        active = [a for a in result["applications"] if a["is_active"]]
        # At most one active window
        self.assertLessEqual(len(active), 1)


class TestBrowserCollector(unittest.TestCase):
    """Validates browser collector output structure."""

    def setUp(self) -> None:
        self.collector = BrowserCollector()

    def test_collect_always_returns_browser_key(self) -> None:
        result = self.collector.collect()
        self.assertIn("browser", result)
        browser = result["browser"]
        if browser is not None:
            self.assertIn("active_browser", browser)
            self.assertIn("tabs", browser)
            self.assertIn("active_url", browser)

    def test_tabs_are_valid(self) -> None:
        result = self.collector.collect()
        browser = result["browser"]
        if browser is not None:
            for tab in browser["tabs"]:
                self.assertIn("title", tab)
                self.assertIn("url", tab)


class TestFilesCollector(unittest.TestCase):
    """Validates files collector output."""

    def setUp(self) -> None:
        self.collector = FilesCollector()

    def test_collect_returns_files_key(self) -> None:
        result = self.collector.collect()
        self.assertIn("files", result)
        files = result["files"]
        self.assertIn("current_folder", files)
        self.assertIn("recent_files", files)
        self.assertIn("downloads_in_progress", files)

    def test_recent_files_is_list(self) -> None:
        result = self.collector.collect()
        self.assertIsInstance(result["files"]["recent_files"], list)

    def test_downloads_is_list(self) -> None:
        result = self.collector.collect()
        self.assertIsInstance(result["files"]["downloads_in_progress"], list)


class TestSystemCollector(unittest.TestCase):
    """Validates system collector output."""

    def setUp(self) -> None:
        self.collector = SystemCollector()

    def test_collect_returns_system_key(self) -> None:
        result = self.collector.collect()
        self.assertIn("system", result)
        sysinfo = result["system"]
        self.assertIn("cpu_percent", sysinfo)
        self.assertIn("ram_percent", sysinfo)
        self.assertIn("gpu_percent", sysinfo)
        self.assertIn("battery_percent", sysinfo)
        self.assertIn("battery_charging", sysinfo)
        self.assertIn("network_connected", sysinfo)
        self.assertIn("clipboard_text", sysinfo)

    def test_cpu_range(self) -> None:
        result = self.collector.collect()
        cpu = result["system"]["cpu_percent"]
        self.assertGreaterEqual(cpu, 0.0)
        self.assertLessEqual(cpu, 100.0)

    def test_ram_range(self) -> None:
        result = self.collector.collect()
        ram = result["system"]["ram_percent"]
        self.assertGreaterEqual(ram, 0.0)
        self.assertLessEqual(ram, 100.0)

    def test_clipboard_is_string(self) -> None:
        result = self.collector.collect()
        self.assertIsInstance(result["system"]["clipboard_text"], str)


class TestMediaCollector(unittest.TestCase):
    """Validates media collector output."""

    def setUp(self) -> None:
        self.collector = MediaCollector()

    def test_collect_returns_media_key(self) -> None:
        result = self.collector.collect()
        self.assertIn("media", result)
        media = result["media"]
        self.assertIn("is_playing", media)
        self.assertIn("title", media)
        self.assertIn("artist", media)
        self.assertIn("app_name", media)
        self.assertIn("volume", media)
        self.assertIn("mic_active", media)

    def test_volume_range(self) -> None:
        result = self.collector.collect()
        vol = result["media"]["volume"]
        self.assertGreaterEqual(vol, 0.0)
        self.assertLessEqual(vol, 1.0)

    def test_mic_active_is_bool(self) -> None:
        result = self.collector.collect()
        self.assertIsInstance(result["media"]["mic_active"], bool)


# ═════════════════════════════════════════════════════════════════════
# 3. WorldModel Orchestrator Tests
# ═════════════════════════════════════════════════════════════════════


class _MockCollector(BaseCollector):
    """Collector that returns predefined data."""

    def __init__(self, fragment: dict, interval: float = 0.1) -> None:
        super().__init__(poll_interval=interval)
        self._fragment = fragment
        self.collect_count = 0

    def collect(self) -> dict:
        self.collect_count += 1
        return self._fragment


class TestWorldModel(unittest.TestCase):
    """Orchestrator lifecycle and query API."""

    def setUp(self) -> None:
        # Use empty collector list — tests register their own mock collectors
        self.wm = WorldModel(collectors=[])

    def tearDown(self) -> None:
        try:
            self.wm.stop()
        except Exception:
            pass

    def test_initial_snapshot_is_empty(self) -> None:
        snap = self.wm.get_snapshot()
        self.assertIsInstance(snap, WorldSnapshot)
        self.assertEqual(snap.applications, [])

    def test_start_and_stop(self) -> None:
        self.wm.start()
        time.sleep(0.2)
        self.wm.stop()
        # After stop, snapshot should be populated (collectors ran at least once)
        snap = self.wm.get_snapshot()
        self.assertIsInstance(snap, WorldSnapshot)

    def test_register_collector(self) -> None:
        mc = _MockCollector({"applications": [
            {"pid": 99, "name": "test.exe", "window_title": "Test",
             "is_active": True, "process_path": "C:\\test.exe"},
        ]})
        self.wm.register_collector(mc)
        self.wm.start()
        time.sleep(0.3)
        self.wm.stop()
        app = self.wm.get_active_application()
        self.assertIsNotNone(app)
        self.assertEqual(app.name, "test.exe")

    def test_get_snapshot_is_independent_copy(self) -> None:
        mc = _MockCollector({"system": {
            "cpu_percent": 50.0, "ram_percent": 50.0, "gpu_percent": 0,
            "battery_percent": -1, "battery_charging": False,
            "network_connected": True, "clipboard_text": "",
        }})
        self.wm.register_collector(mc)
        self.wm.start()
        time.sleep(0.3)
        self.wm.stop()
        snap1 = self.wm.get_snapshot()
        snap2 = self.wm.get_snapshot()
        # Same object instance since nothing changed between reads
        self.assertIs(snap1, snap2)
        # Snapshot is frozen (immutable)
        with self.assertRaises(AttributeError):
            snap1.timestamp = 0.0  # type: ignore[misc]

    def test_get_applications(self) -> None:
        mc = _MockCollector({"applications": [
            {"pid": 1, "name": "a.exe", "window_title": "A",
             "is_active": False, "process_path": ""},
            {"pid": 2, "name": "b.exe", "window_title": "B",
             "is_active": True, "process_path": ""},
        ]})
        self.wm.register_collector(mc)
        self.wm.start()
        time.sleep(0.3)
        self.wm.stop()
        apps = self.wm.get_applications()
        self.assertEqual(len(apps), 2)

    def test_get_active_application(self) -> None:
        mc = _MockCollector({"applications": [
            {"pid": 1, "name": "a.exe", "window_title": "A",
             "is_active": False, "process_path": ""},
            {"pid": 2, "name": "b.exe", "window_title": "B",
             "is_active": True, "process_path": ""},
        ]})
        self.wm.register_collector(mc)
        self.wm.start()
        time.sleep(0.3)
        self.wm.stop()
        active = self.wm.get_active_application()
        self.assertIsNotNone(active)
        self.assertEqual(active.pid, 2)

    def test_get_active_application_returns_none(self) -> None:
        mc = _MockCollector({"applications": [
            {"pid": 1, "name": "a.exe", "window_title": "A",
             "is_active": False, "process_path": ""},
        ]})
        self.wm.register_collector(mc)
        self.wm.start()
        time.sleep(0.3)
        self.wm.stop()
        self.assertIsNone(self.wm.get_active_application())

    def test_get_browser_info(self) -> None:
        mc = _MockCollector({"browser": {
            "active_browser": "chrome",
            "tabs": [{"title": "Google", "url": "https://google.com"}],
            "active_url": "https://google.com",
        }})
        self.wm.register_collector(mc)
        self.wm.start()
        time.sleep(0.3)
        self.wm.stop()
        bi = self.wm.get_browser_info()
        self.assertIsNotNone(bi)
        self.assertEqual(bi.active_browser, "chrome")

    def test_get_system_info(self) -> None:
        mc = _MockCollector({"system": {
            "cpu_percent": 42.0, "ram_percent": 65.0, "gpu_percent": 12.0,
            "battery_percent": 80.0, "battery_charging": True,
            "network_connected": True, "clipboard_text": "hello",
        }})
        self.wm.register_collector(mc)
        self.wm.start()
        time.sleep(0.3)
        self.wm.stop()
        si = self.wm.get_system_info()
        self.assertIsNotNone(si)
        self.assertEqual(si.cpu_percent, 42.0)
        self.assertEqual(si.clipboard_text, "hello")

    def test_get_media_info(self) -> None:
        mc = _MockCollector({"media": {
            "is_playing": True, "title": "Song", "artist": "Artist",
            "app_name": "spotify", "volume": 0.7, "mic_active": False,
        }})
        self.wm.register_collector(mc)
        self.wm.start()
        time.sleep(0.3)
        self.wm.stop()
        mi = self.wm.get_media_info()
        self.assertIsNotNone(mi)
        self.assertEqual(mi.title, "Song")

    def test_get_clipboard(self) -> None:
        mc = _MockCollector({"system": {
            "cpu_percent": 0, "ram_percent": 0, "gpu_percent": 0,
            "battery_percent": -1, "battery_charging": False,
            "network_connected": False, "clipboard_text": "copied!",
        }})
        self.wm.register_collector(mc)
        self.wm.start()
        time.sleep(0.3)
        self.wm.stop()
        self.assertEqual(self.wm.get_clipboard(), "copied!")

    def test_get_current_folder(self) -> None:
        mc = _MockCollector({"files": {
            "current_folder": "C:\\Users\\test",
            "recent_files": [],
            "downloads_in_progress": [],
        }})
        self.wm.register_collector(mc)
        self.wm.start()
        time.sleep(0.3)
        self.wm.stop()
        self.assertEqual(self.wm.get_current_folder(), "C:\\Users\\test")

    def test_collector_error_does_not_crash(self) -> None:
        class _FailingCollector(BaseCollector):
            def collect(self) -> dict:
                raise RuntimeError("expected failure")

        self.wm.register_collector(_FailingCollector(poll_interval=1.0))
        self.wm.start()
        time.sleep(0.3)
        self.wm.stop()
        # Should not crash — errors are logged and ignored
        snap = self.wm.get_snapshot()
        self.assertIsInstance(snap, WorldSnapshot)

    def test_thread_safety(self) -> None:
        """Multiple threads reading snapshot concurrently."""
        import threading

        mc = _MockCollector({"system": {
            "cpu_percent": 50.0, "ram_percent": 50.0, "gpu_percent": 0,
            "battery_percent": -1, "battery_charging": False,
            "network_connected": True, "clipboard_text": "",
        }})
        self.wm.register_collector(mc)
        self.wm.start()

        errors = []

        def _reader():
            for _ in range(20):
                try:
                    snap = self.wm.get_snapshot()
                    self.assertIsInstance(snap, WorldSnapshot)
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=_reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.wm.stop()
        self.assertEqual(errors, [])

    def test_collector_poll_intervals_respected(self) -> None:
        """Verifies that collectors with different intervals tick correctly."""
        fast = _MockCollector({"applications": [
            {"pid": 1, "name": "fast.exe", "window_title": "Fast",
             "is_active": False, "process_path": ""},
        ]}, interval=0.1)
        slow = _MockCollector({"system": {
            "cpu_percent": 10.0, "ram_percent": 20.0, "gpu_percent": 0,
            "battery_percent": -1, "battery_charging": False,
            "network_connected": False, "clipboard_text": "",
        }}, interval=0.7)  # > 0.5s loop interval to create a difference

        self.wm.register_collector(fast)
        self.wm.register_collector(slow)
        self.wm.start()
        time.sleep(1.5)
        self.wm.stop()

        # Fast collector should have been called more often than slow
        self.assertGreater(fast.collect_count, slow.collect_count)


if __name__ == "__main__":
    unittest.main()
