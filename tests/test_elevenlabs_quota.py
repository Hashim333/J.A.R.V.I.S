"""FIX-QUOTA-NO-RETRY: regression tests for the ElevenLabs provider.

A 401 (invalid/quota key) or 429 (quota exceeded) is a permanent condition —
retrying only stacks silent dead seconds onto every spoken line before the
VoiceManager fallback chain (Piper -> system) eventually takes over.  The
provider must:

  * fail immediately (no retry) on 401 / 429,
  * stay blocked for the rest of the process (no repeated API attempts),
  * still retry transient failures (transport errors, 5xx) once, and
  * never hand an error body to the audio player.

The provider performs HTTP through ``requests.Session.post`` (it no longer
uses ``urllib``), so these tests patch that call.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

import requests

from voice.elevenlabs_provider import ElevenLabsProvider


def _make_provider() -> ElevenLabsProvider:
    provider = ElevenLabsProvider(
        api_key="k123",
        voice_id="v123",
        model="eleven_multilingual_v2",
        output_format="pcm_22050",
        player=MagicMock(),
    )
    provider._player.reset_mock()
    return provider


def _response(status: int) -> MagicMock:
    """A response object shaped like a ``requests.Response``."""
    response = MagicMock()
    response.status_code = status
    response.headers = {"Content-Type": "application/json"}
    response.content = b'{"detail": "quota exceeded"}'
    response.iter_content.return_value = iter([b"\x00" * 2048])
    return response


class _status_factory:
    """Return a fresh response with a fixed status code on every call."""

    def __init__(self, status: int) -> None:
        self._status = status

    def __call__(self, url, **kwargs):
        return _response(self._status)


class TestElevenLabsQuotaNoRetry(unittest.TestCase):
    def test_401_fails_immediately_and_blocks_provider(self) -> None:
        provider = _make_provider()
        with patch(
            "requests.Session.post", side_effect=_status_factory(401),
        ) as mock_post:
            result = provider.speak("hello")
        self.assertFalse(result)
        # No retry: the request must have been attempted exactly once.
        self.assertEqual(mock_post.call_count, 1, "401 must not be retried")
        self.assertTrue(provider._quota_blocked,
                        "provider must be marked blocked after 401")

    def test_429_fails_immediately_and_blocks_provider(self) -> None:
        provider = _make_provider()
        with patch(
            "requests.Session.post", side_effect=_status_factory(429),
        ) as mock_post:
            result = provider.speak("hello")
        self.assertFalse(result)
        self.assertEqual(mock_post.call_count, 1,
                         "429 must not be retried")
        self.assertTrue(provider._quota_blocked)

    def test_blocked_provider_never_hits_api_again(self) -> None:
        provider = _make_provider()
        provider._quota_blocked = True
        with patch(
            "requests.Session.post", return_value=_response(200),
        ) as mock_post:
            result = provider.speak("hello")
        self.assertFalse(result)
        mock_post.assert_not_called()

    def test_transient_http_error_still_retries(self) -> None:
        provider = _make_provider()
        with patch(
            "requests.Session.post", side_effect=_status_factory(503),
        ) as mock_post:
            result = provider.speak("hello")
        self.assertFalse(result)
        # _MAX_RETRIES = 1 -> 2 attempts for a transient (non-401/429) HTTP
        # error before giving up.
        self.assertEqual(mock_post.call_count, 2,
                         "transient HTTP errors should still retry")
        self.assertFalse(provider._quota_blocked)

    def test_transport_error_still_retries(self) -> None:
        provider = _make_provider()
        with patch(
            "requests.Session.post",
            side_effect=requests.exceptions.ConnectionError("network down"),
        ) as mock_post:
            result = provider.speak("hello")
        self.assertFalse(result)
        self.assertEqual(mock_post.call_count, 2,
                         "transport errors should still retry")
        self.assertFalse(provider._quota_blocked)

    def test_quota_error_body_is_never_played(self) -> None:
        """A 401/429 body is JSON, not PCM — it must never reach the player.

        The status code used to be checked *after* the PCM-stream decision, so
        the JSON error body was streamed to the player as raw audio (audible
        noise) and reported as success, which also skipped the fallback chain.
        """
        provider = _make_provider()
        with patch("requests.Session.post", side_effect=_status_factory(429)):
            result = provider.speak("hello")
        self.assertFalse(result)
        provider._player.play.assert_not_called()
        provider._player.play_stream.assert_not_called()

    def test_server_error_body_is_never_played(self) -> None:
        provider = _make_provider()
        with patch("requests.Session.post", side_effect=_status_factory(500)):
            result = provider.speak("hello")
        self.assertFalse(result)
        provider._player.play.assert_not_called()
        provider._player.play_stream.assert_not_called()


if __name__ == "__main__":
    unittest.main()
