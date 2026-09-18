"""FIX-QUOTA-NO-RETRY: regression tests for the ElevenLabs provider.

A 401 (invalid/quota key) or 429 (quota exceeded) is a permanent condition —
retrying only stacks silent dead seconds onto every spoken line before the
VoiceManager fallback chain (Piper -> system) eventually takes over.  The
provider must:

  * fail immediately (no retry) on 401 / 429,
  * stay blocked for the rest of the process (no repeated API attempts), and
  * still retry transient failures (URLError, 5xx) once.
"""
from __future__ import annotations

import io
import unittest
import urllib.error
from unittest.mock import MagicMock
from unittest.mock import patch

from voice.elevenlabs_provider import ElevenLabsProvider


def _make_provider():
    return ElevenLabsProvider(
        api_key="k123",
        voice_id="v123",
        model="eleven_multilingual_v2",
        output_format="pcm_22050",
        player=MagicMock(),
    )


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.elevenlabs.io",
        code=code,
        msg="error",
        hdrs={},
        fp=io.BytesIO(b"quota exceeded"),
    )


class _http_side_effect_factory:
    """Build a urlopen mock that raises HTTPError(code) on every call."""

    def __init__(self, code: int):
        self._code = code

    def __call__(self, request, timeout=None):
        raise _http_error(self._code)


class TestElevenLabsQuotaNoRetry(unittest.TestCase):
    def test_401_fails_immediately_and_blocks_provider(self) -> None:
        provider = _make_provider()
        with patch(
            "voice.elevenlabs_provider.urllib.request.urlopen",
            side_effect=_http_side_effect_factory(401),
        ) as mock_open:
            result = provider.speak("hello")
        self.assertFalse(result)
        # No retry: urlopen must have been attempted exactly once.
        self.assertEqual(mock_open.call_count, 1,
                         "401 must not be retried")
        self.assertTrue(provider._quota_blocked,
                        "provider must be marked blocked after 401")

    def test_429_fails_immediately_and_blocks_provider(self) -> None:
        provider = _make_provider()
        with patch(
            "voice.elevenlabs_provider.urllib.request.urlopen",
            side_effect=_http_side_effect_factory(429),
        ) as mock_open:
            result = provider.speak("hello")
        self.assertFalse(result)
        self.assertEqual(mock_open.call_count, 1,
                         "429 must not be retried")
        self.assertTrue(provider._quota_blocked)

    def test_blocked_provider_never_hits_api_again(self) -> None:
        provider = _make_provider()
        provider._quota_blocked = True
        with patch(
            "voice.elevenlabs_provider.urllib.request.urlopen",
            return_value=MagicMock(status=200),
        ) as mock_open:
            result = provider.speak("hello")
        self.assertFalse(result)
        mock_open.assert_not_called()

    def test_transient_http_error_still_retries(self) -> None:
        provider = _make_provider()
        with patch(
            "voice.elevenlabs_provider.urllib.request.urlopen",
            side_effect=_http_side_effect_factory(503),
        ) as mock_open:
            result = provider.speak("hello")
        self.assertFalse(result)
        # _MAX_RETRIES = 1 -> 2 attempts for a transient (non-401/429) HTTP
        # error before giving up.
        self.assertEqual(mock_open.call_count, 2,
                         "transient HTTP errors should still retry")
        self.assertFalse(provider._quota_blocked)


if __name__ == "__main__":
    unittest.main()