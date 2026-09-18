import unittest
from unittest.mock import MagicMock, patch

from brain.execution_plan import ExecutionPlan, Step
from models.action_result import ActionResult
from models.task_result import TaskResult
from automation.cdp import CdpTab


def _results_tab() -> CdpTab:
    return CdpTab(
        tab_id="tab-1",
        title="results - YouTube",
        url="https://www.youtube.com/results?search_query=test",
        active=True,
        window_id=1,
        ws_url="ws://127.0.0.1:9222/tab-1",
    )


def _fake_client(click_result=None, state_result=None) -> MagicMock:
    """A CDP client stub that returns canned DOM evaluation results."""
    client = MagicMock()
    client.list_tabs.return_value = [_results_tab()]
    client.activate.return_value = True

    def evaluate(tab, expression, await_promise=True):
        if state_result is not None and "youtube\\.com\\/watch" in expression:
            return state_result
        return click_result

    client.evaluate.side_effect = evaluate
    client.page_state.return_value = {
        "url": "https://www.youtube.com/watch?v=abc",
        "title": "Video - YouTube",
        "selectedText": "",
        "readyState": "complete",
    }
    return client


class TestYoutubeDOM(unittest.TestCase):
    def test_click_first_organic_js_targets_organic_renderers_only(self):
        """The "skip sponsored" rule is deterministic: the DOM selector must
        match organic video renderers and never the ad-slot renderer."""
        from automation.youtube import _CLICK_FIRST_ORGANIC_JS

        self.assertIn("ytd-video-renderer", _CLICK_FIRST_ORGANIC_JS)
        self.assertNotIn("ytd-ad-slot-renderer", _CLICK_FIRST_ORGANIC_JS)

    def test_video_state_js_reports_full_playback_state(self):
        from automation.youtube import _VIDEO_STATE_JS

        for token in ("playing", "paused", "current_time", "duration",
                      "volume", "muted", "fullscreen", "ad_present",
                      "ad_skippable", "playlist"):
            self.assertIn(token, _VIDEO_STATE_JS)


class TestYoutubePlayFirstResult(unittest.TestCase):
    def test_empty_query_reuses_open_results_tab(self):
        from automation.youtube import play_first_result

        fake = _fake_client(click_result={"clicked": True, "title": "Song"})
        with patch("automation.youtube._client", return_value=fake), \
                patch("automation.youtube._results_tab", return_value=_results_tab()), \
                patch("automation.youtube._wait_for_watch_page", return_value=True):
            result = play_first_result("   ")
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "success")

    def test_empty_query_with_no_results_page_fails(self):
        from automation.youtube import play_first_result

        fake = _fake_client()
        with patch("automation.youtube._client", return_value=fake), \
                patch("automation.youtube._results_tab", return_value=None):
            result = play_first_result("   ")
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "failed")

    @patch("automation.youtube._wait_for_watch_page", return_value=True)
    @patch("automation.youtube._results_tab", return_value=_results_tab())
    def test_success_clicking_first_organic(self, *mocks):
        from automation.youtube import play_first_result

        fake = _fake_client(click_result={"clicked": True, "title": "Song"})
        with patch("automation.youtube._client", return_value=fake), \
                patch("automation.browser.search",
                      return_value={"success": True, "message": "ok"}):
            result = play_first_result("billie eilish")
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "success")
        self.assertIn("billie eilish", result["message"])

    @patch("automation.youtube._wait_for_watch_page", return_value=False)
    @patch("automation.youtube._results_tab", return_value=_results_tab())
    def test_video_loading_reports_waiting(self, *mocks):
        from automation.youtube import play_first_result

        fake = _fake_client(click_result={"clicked": True, "title": "Song"})
        with patch("automation.youtube._client", return_value=fake), \
                patch("automation.browser.search",
                      return_value={"success": True, "message": "ok"}):
            result = play_first_result("billie eilish")
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "waiting")

    @patch("automation.youtube._results_tab", return_value=_results_tab())
    def test_no_video_found_retries(self, *mocks):
        from automation.youtube import play_first_result

        fake = _fake_client(click_result={"clicked": False})
        with patch("automation.youtube._client", return_value=fake), \
                patch("automation.browser.search",
                      return_value={"success": True, "message": "ok"}):
            result = play_first_result("billie eilish")
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "retrying")

    @patch("automation.youtube._results_tab", return_value=_results_tab())
    def test_search_failure_reports_failed(self, *mocks):
        from automation.youtube import play_first_result

        fake = _fake_client()
        with patch("automation.youtube._client", return_value=fake), \
                patch("automation.browser.search",
                      return_value={"success": False, "message": "search failed"}):
            result = play_first_result("billie eilish")
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "failed")


class TestYoutubeControls(unittest.TestCase):
    def _run(self, func, result_dict):
        fake = _fake_client(click_result=result_dict)
        with patch("automation.youtube._client", return_value=fake), \
                patch("automation.youtube._youtube_tab", return_value=_results_tab()):
            return func()

    def test_pause(self):
        from automation.youtube import pause
        result = self._run(pause, {"ok": True, "paused": True})
        self.assertTrue(result["success"])

    def test_resume_missing_video_retries(self):
        from automation.youtube import resume
        result = self._run(resume, {"ok": False})
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "retrying")

    def test_play_next(self):
        from automation.youtube import play_next
        result = self._run(play_next, {"ok": True})
        self.assertTrue(result["success"])

    def test_skip_ad(self):
        from automation.youtube import skip_ad
        result = self._run(skip_ad, {"ok": True})
        self.assertTrue(result["success"])

    def test_like_video(self):
        from automation.youtube import like_video
        result = self._run(like_video, {"ok": True, "already_liked": False})
        self.assertTrue(result["success"])

    def test_like_already_liked_message(self):
        from automation.youtube import like_video
        result = self._run(like_video, {"ok": True, "already_liked": True})
        self.assertTrue(result["success"])
        self.assertIn("already liked", result["message"])

    def test_subscribe(self):
        from automation.youtube import subscribe
        result = self._run(subscribe, {"ok": True, "already_subscribed": False})
        self.assertTrue(result["success"])


class TestYoutubeGetState(unittest.TestCase):
    def test_get_state_reports_playback(self):
        from automation.youtube import get_state

        fake = _fake_client(state_result={
            "url": "https://www.youtube.com/watch?v=abc",
            "title": "Song - YouTube",
            "on_watch_page": True,
            "video": {
                "loaded": True, "playing": True, "paused": False,
                "current_time": 42.0, "duration": 200.0,
                "volume": 0.8, "muted": False, "playback_rate": 1.0,
                "fullscreen": False, "ad_present": False, "ad_skippable": False,
            },
            "playlist": {"length": 0, "index": -1, "active": False},
        })
        with patch("automation.youtube._client", return_value=fake), \
                patch("automation.youtube._youtube_tab", return_value=_results_tab()):
            result = get_state()
        self.assertTrue(result["success"])
        details = result["details"]
        self.assertTrue(details["playing"])
        self.assertEqual(details["current_time"], 42.0)
        self.assertEqual(details["volume"], 0.8)
        self.assertFalse(details["ad_present"])

    def test_get_state_no_youtube_tab_fails(self):
        from automation.youtube import get_state

        fake = _fake_client()
        with patch("automation.youtube._client", return_value=fake), \
                patch("automation.youtube._youtube_tab", return_value=None):
            result = get_state()
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "failed")


class TestYoutubeContinueWatching(unittest.TestCase):
    def test_paused_video_resumes(self):
        from automation.youtube import continue_watching

        fake = _fake_client(state_result={
            "video": {"loaded": True, "playing": False, "paused": True},
        })
        with patch("automation.youtube._client", return_value=fake), \
                patch("automation.youtube._youtube_tab", return_value=_results_tab()), \
                patch("automation.youtube.resume",
                      return_value={"success": True, "status": "success", "message": "Resumed."}):
            result = continue_watching()
        self.assertTrue(result["success"])

    def test_playing_video_reports_already_playing(self):
        from automation.youtube import continue_watching

        fake = _fake_client(state_result={
            "video": {"loaded": True, "playing": True, "paused": False},
        })
        with patch("automation.youtube._client", return_value=fake), \
                patch("automation.youtube._youtube_tab", return_value=_results_tab()):
            result = continue_watching()
        self.assertTrue(result["success"])
        self.assertIn("already playing", result["message"])

    def test_clicks_first_video_link_when_nothing_loaded(self):
        from automation.youtube import continue_watching

        fake = _fake_client(state_result={
            "video": {"loaded": False, "playing": False, "paused": False},
        })
        fake.evaluate.side_effect = [
            {"video": {"loaded": False, "playing": False, "paused": False}},
            {"clicked": True, "title": "Continue"},
        ]
        with patch("automation.youtube._client", return_value=fake), \
                patch("automation.youtube._youtube_tab", return_value=_results_tab()), \
                patch("automation.youtube._wait_for_watch_page", return_value=True):
            result = continue_watching()
        self.assertTrue(result["success"])


class TestBrowserHandlerClickFirstVideo(unittest.TestCase):
    def test_dispatch_calls_youtube_play(self):
        from automation.handlers import BrowserHandler

        plan = ExecutionPlan(
            raw_text="play x", intent="play_music", confidence=1.0,
            steps=[Step("click_first_video", "billie eilish", {"query": "billie eilish"}, "click")],
            metadata={},
        )
        handler = BrowserHandler()
        with patch("automation.youtube.play_first_result", return_value={
            "success": True, "status": "success", "message": "Now playing.",
        }) as fake_play:
            result = handler.run(plan.steps[0])
            fake_play.assert_called_once_with("billie eilish", index=1)
        ar = ActionResult.from_handler(result)
        self.assertEqual(ar.task_result, TaskResult.SUCCESS)

    def test_waiting_status_maps(self):
        from automation.handlers import BrowserHandler

        plan = ExecutionPlan(
            raw_text="play x", intent="play_music", confidence=1.0,
            steps=[Step("click_first_video", "x", {"query": "x"}, "click")],
            metadata={},
        )
        handler = BrowserHandler()
        with patch("automation.youtube.play_first_result", return_value={
            "success": False, "status": "waiting", "message": "Video loading.",
        }):
            result = handler.run(plan.steps[0])
        ar = ActionResult.from_handler(result)
        self.assertEqual(ar.task_result, TaskResult.WAITING)


if __name__ == "__main__":
    unittest.main()
