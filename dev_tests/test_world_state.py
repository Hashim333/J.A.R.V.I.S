import time
import unittest
from types import SimpleNamespace

from context_manager.browser_detector import BrowserDetector
from intelligence.world_state import BrowserState, WorldState, WorldStateService


class FakeMedia:
    is_playing = False


class FakeSystem:
    clipboard_text = "hello clipboard"


class FakeBrowserInfo:
    def __init__(self, active_browser=None, tabs=(), active_url=None):
        self.active_browser = active_browser
        self.tabs = list(tabs)
        self.active_url = active_url


class FakeBase:
    def __init__(self, applications=(), browser=None, media=None):
        self.applications = list(applications)
        self.browser = browser or FakeBrowserInfo()
        self.system = FakeSystem()
        self.media = media or FakeMedia()


class FakeWorldModel:
    def __init__(self, base):
        self._base = base

    def start(self):
        pass

    def stop(self):
        pass

    def get_snapshot(self):
        return self._base


class FastWorldStateService(WorldStateService):
    def _browser_window_titles(self):
        return {}

    def _visible_dialogs(self):
        return []

    def _mouse_position(self):
        return (10, 20)


class TestWorldStateBuild(unittest.TestCase):
    def test_builds_from_snapshot(self):
        base = FakeBase(
            applications=[
                SimpleNamespace(
                    pid=1, name="notepad.exe", window_title="notes.txt - Notepad",
                    is_active=True, process_path="C:\\notepad.exe",
                )
            ]
        )
        s = FastWorldStateService(world_model=FakeWorldModel(base))
        ws = s.current()
        self.assertIsInstance(ws, WorldState)
        self.assertEqual(len(ws.applications), 1)
        self.assertEqual(ws.applications[0].name, "notepad.exe")
        self.assertEqual(ws.focused_window, "notes.txt - Notepad")
        self.assertEqual(ws.clipboard, "hello clipboard")
        self.assertEqual(ws.mouse_position, (10, 20))

    def test_app_running_query(self):
        base = FakeBase(
            applications=[
                SimpleNamespace(
                    pid=1, name="notepad.exe", window_title="notes.txt - Notepad",
                    is_active=False, process_path="",
                )
            ]
        )
        s = FastWorldStateService(world_model=FakeWorldModel(base))
        ws = s.current()
        self.assertTrue(ws.app_running("notepad"))
        self.assertTrue(ws.app_running("Notepad"))
        self.assertFalse(ws.app_running("chrome"))

    def test_browser_state_from_snapshot(self):
        base = FakeBase(
            browser=FakeBrowserInfo(
                active_browser="chrome",
                tabs=[
                    SimpleNamespace(title="YouTube", url="https://youtube.com/watch?v=x", active=True),
                    SimpleNamespace(title="Google", url="https://google.com", active=False),
                ],
                active_url="https://youtube.com/watch?v=x",
            )
        )
        s = FastWorldStateService(
            world_model=FakeWorldModel(base),
            browser_detector=BrowserDetector(),
        )
        ws = s.current()
        chrome = ws.browser("chrome")
        self.assertIsNotNone(chrome)
        self.assertIsInstance(chrome, BrowserState)
        self.assertTrue(chrome.running)
        self.assertEqual(len(chrome.windows), 2)
        self.assertEqual(chrome.active_website, "youtube")
        self.assertTrue(chrome.playing)
        self.assertTrue(ws.active_website, "youtube")
        self.assertTrue(ws.video_playing)

    def test_caching(self):
        base = FakeBase()
        model = FakeWorldModel(base)
        s = FastWorldStateService(world_model=model, cache_ttl=10.0)
        w1 = s.current()
        w2 = s.current()
        self.assertIs(w1, w2)

    def test_snapshot_proxies(self):
        base = FakeBase()
        model = FakeWorldModel(base)
        s = FastWorldStateService(world_model=model)
        self.assertIs(s.snapshot(), base)


if __name__ == "__main__":
    unittest.main()
