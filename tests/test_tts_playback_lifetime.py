"""FIX 1 regression tests: ElevenLabs streaming lifetime + honest verdicts.

Covers the confirmed use-after-close race where _play_pcm_stream handed a
lazy response.read() generator to the player worker and returned True
before the response lifetime finished — playback died with 0 bytes while
success was reported ("streaming finished (played 0.0 sec)" + "OK").

No network, no audio hardware: responses and PyAudio are faked.
"""
from __future__ import annotations

import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from voice.elevenlabs_provider import ElevenLabsProvider
from voice.manager import VoiceManager
from voice.player import VoicePlayer


class FakeResponse:
    """Minimal HTTP-response double tracking lifetime."""

    def __init__(self, chunks, fail_after=None):
        self._chunks = list(chunks)
        self._fail_after = fail_after
        self.reads = 0
        self.closed = False

    def read(self, n=-1):
        if self.closed:
            raise ValueError("read on closed response")
        if self._fail_after is not None and self.reads >= self._fail_after:
            raise OSError("connection reset")
        self.reads += 1
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    def close(self):
        self.closed = True


def _make_provider(player=None):
    return ElevenLabsProvider(
        api_key="k123",
        voice_id="v123",
        model="eleven_multilingual_v2",
        output_format="pcm_22050",
        player=player or MagicMock(),
    )


class TestStreamingLifetime(unittest.TestCase):
    def test_empty_stream_returns_false(self) -> None:
        """Zero-chunk response: no fake success, response released."""
        provider = _make_provider()
        resp = FakeResponse([])
        self.assertFalse(provider._play_pcm_stream(resp, time.monotonic(), "audio/pcm"))
        self.assertTrue(resp.closed)

    def test_read_failure_before_first_chunk_returns_false(self) -> None:
        provider = _make_provider()
        resp = FakeResponse([b"\x01\x02" * 512], fail_after=0)
        self.assertFalse(provider._play_pcm_stream(resp, time.monotonic(), "audio/pcm"))
        self.assertTrue(resp.closed)

    def test_full_stream_drains_and_closes_response(self) -> None:
        """Normal path: every chunk reaches the player, response closed after."""
        player = MagicMock()
        received = []

        def fake_play_stream(chunks, **kwargs):
            # Drain synchronously like the worker would.
            for piece in chunks:
                received.append(piece)

        player.play_stream.side_effect = fake_play_stream
        provider = _make_provider(player=player)
        chunks = [b"\x01\x02" * 512 for _ in range(5)]
        resp = FakeResponse(list(chunks))
        self.assertTrue(provider._play_pcm_stream(resp, time.monotonic(), "audio/pcm"))
        # Give the daemon pump a beat to finish + close (bounded wait).
        deadline = time.monotonic() + 5.0
        while not resp.closed and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(resp.closed, "pump must release the response")
        self.assertEqual(b"".join(received), b"".join(chunks))

    def test_stop_cancels_inflight_download(self) -> None:
        """Barge-in stop() must unblock a stalled download without hanging."""
        player = MagicMock()
        player.play_stream.side_effect = lambda chunks, **kw: None  # never drains
        provider = _make_provider(player=player)
        resp = FakeResponse([b"\x01\x02" * 2048] * 200)  # endless-ish supply
        done: list = []

        def run():
            # First chunk arrives, then stop() while the pump keeps producing.
            result = provider._play_pcm_stream(resp, time.monotonic(), "audio/pcm")
            done.append(result)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        time.sleep(0.5)
        provider.stop()  # must not hang, must cancel the pump
        t.join(timeout=5.0)
        self.assertFalse(t.is_alive(), "speak path must terminate after stop()")
        deadline = time.monotonic() + 5.0
        while not resp.closed and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(resp.closed)


class TestPlaybackVerdict(unittest.TestCase):
    def _manager(self):
        config = SimpleNamespace(
            voice_provider="system", voice_id="", voice_model="",
            elevenlabs_api_key="", voice_stability=None, voice_similarity=None,
            voice_style=None, voice_speaker_boost=None,
        )
        return VoiceManager(config=config)

    def _stub_provider(self, speak_ok=True, played_bytes=0):
        stub = SimpleNamespace()
        stub.speak = lambda text: speak_ok
        stub.is_playing = False
        stub.stop = lambda *a, **k: None
        stub.player = SimpleNamespace(
            last_play_bytes=played_bytes, last_play_error=None,
        )
        return stub

    def test_zero_bytes_consumed_is_failure(self) -> None:
        """The 0.0-sec success must become FAILED + fail over, not OK."""
        manager = self._manager()
        manager._provider = self._stub_provider(speak_ok=True, played_bytes=0)
        with patch.object(manager, "_fallback_to_system") as fb:
            result = manager._speak_with_fallback("hello")
        self.assertFalse(result)
        fb.assert_called_once()  # failover attempted, not silent OK

    def test_consumed_bytes_is_success(self) -> None:
        manager = self._manager()
        manager._provider = self._stub_provider(speak_ok=True, played_bytes=44100)
        with patch.object(manager, "_fallback_to_system") as fb:
            result = manager._speak_with_fallback("hello")
        self.assertTrue(result)
        fb.assert_not_called()

    def test_interrupted_counts_as_delivered(self) -> None:
        """Barge-in cut short must not trigger fallback/retry loops."""
        manager = self._manager()
        manager._provider = self._stub_provider(speak_ok=True, played_bytes=0)
        manager._interrupted = True
        with patch.object(manager, "_fallback_to_system") as fb:
            result = manager._speak_with_fallback("hello")
        self.assertTrue(result)
        fb.assert_not_called()

    def test_no_accounting_keeps_legacy_verdict(self) -> None:
        """System voice (no player) preserves old speak()==success behavior."""
        manager = self._manager()
        stub = SimpleNamespace()
        stub.speak = lambda text: True
        stub.is_playing = False
        stub.stop = lambda *a, **k: None
        manager._provider = stub  # no .player attribute at all
        self.assertTrue(manager._speak_with_fallback("hello"))


class TestPlayerGenerations(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("voice.player.pyaudio")
        self.mock_pyaudio_mod = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_pyaudio_instance = MagicMock()
        self.mock_pyaudio_mod.PyAudio.return_value = self.mock_pyaudio_instance
        self.mock_stream = MagicMock()
        self.mock_pyaudio_instance.open.return_value = self.mock_stream
        self.player = VoicePlayer()

    def tearDown(self) -> None:
        self.player.shutdown()

    def test_stale_finish_does_not_fire_callback_or_clobber(self) -> None:
        self.player.play(b"\x00\x01" * 2000)
        current_gen = self.player._generation
        # A newer utterance starts (bumps generation, resets accounting).
        self.player.play(b"\x00\x01" * 2000)
        self.player.stop()
        # Spy attached now: only a *late* finish from the old generation
        # could fire it — which must be dropped entirely.
        fired: list = []
        self.player.on_playback_finished = lambda: fired.append(True)
        before = (self.player.last_play_bytes, self.player.last_play_error)
        self.player._finish_generation(current_gen, 99999, None)
        self.assertEqual(fired, [])
        self.assertEqual(
            (self.player.last_play_bytes, self.player.last_play_error), before
        )

    def test_stale_worker_does_not_close_new_stream(self) -> None:
        self.player.play(b"\x00\x01" * 2000)
        old_gen = self.player._generation
        new_stream = MagicMock()
        with self.player._lock:
            self.player._stream = new_stream
            self.player._stream_gen = old_gen + 1
            self.player._generation = old_gen + 1
        self.player._close_owned_stream(old_gen)
        new_stream.close.assert_not_called()
        self.player._close_owned_stream(old_gen + 1)
        new_stream.close.assert_called_once()
        self.player.stop()

    def test_generator_error_recorded_not_swallowed(self) -> None:
        def bad_chunks():
            yield b"\x00\x01" * 100
            raise OSError("socket died")

        self.player.play_stream(bad_chunks())
        deadline = time.monotonic() + 5.0
        while self.player.is_playing and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertGreater(self.player.last_play_bytes, 0)
        self.assertIsNotNone(self.player.last_play_error)
        self.assertIn("socket died", self.player.last_play_error)
        self.player.stop()


class TestMuteOwnership(unittest.TestCase):
    def test_overlapping_mutes_are_reference_counted(self) -> None:
        from voice.microphone_stream import MicrophoneStream

        ms = MicrophoneStream.__new__(MicrophoneStream)
        ms._lock = threading.Lock()
        ms._muted = False
        ms._mute_owners = set()
        ms.mute("tts")
        ms.mute("capture")
        self.assertTrue(ms._muted)
        ms.unmute("tts")
        self.assertTrue(ms._muted, "capture's mute must survive tts unmute")
        self.assertEqual(ms.mute_owners, ("capture",))
        ms.unmute("capture")
        self.assertFalse(ms._muted)

    def test_legacy_unmute_clears_all(self) -> None:
        """Bare unmute() keeps the historical safety-restore semantic."""
        from voice.microphone_stream import MicrophoneStream

        ms = MicrophoneStream.__new__(MicrophoneStream)
        ms._lock = threading.Lock()
        ms._muted = False
        ms._mute_owners = set()
        ms.mute("a")
        ms.mute("b")
        ms.unmute()
        self.assertFalse(ms._muted)
        self.assertEqual(ms.mute_owners, ())

    def test_dev_test_compat_flag_synced(self) -> None:
        from voice.microphone_stream import MicrophoneStream

        ms = MicrophoneStream.__new__(MicrophoneStream)
        ms._lock = threading.Lock()
        ms._muted = False
        ms._mute_owners = set()
        ms.mute()
        self.assertTrue(ms._muted)
        ms.unmute()
        self.assertFalse(ms._muted)


class TestLegacyBargeInConsumerSafety(unittest.TestCase):
    def _engine(self):
        from voice.engine import VoiceEngine

        stream = MagicMock()
        stream._consumer = None
        engine = VoiceEngine.__new__(VoiceEngine)
        engine._voice_manager = MagicMock()
        engine._voice_manager.is_playing = True
        engine._microphone_stream = stream
        engine._duplex_session = None
        engine._barge_in_active = False
        engine._barge_in_fired = False
        engine._barge_in_vad = None
        engine._barge_in_pending = False
        engine._barge_in_timer = None
        engine._barge_in_grace_until = 0.0
        return engine, stream

    def test_start_refuses_owned_consumer(self) -> None:
        """Legacy barge-in must not steal the duplex/STT feed."""
        engine, stream = self._engine()

        class Owner:
            def process_chunk(self, chunk):
                pass

        stream._consumer = Owner().process_chunk
        engine.start_barge_in()
        # Consumer untouched, engine did not arm the legacy path.
        self.assertIs(stream._consumer.__self__.__class__, Owner)
        self.assertFalse(engine._barge_in_active)
        self.assertIsNone(engine._barge_in_vad)

    def test_stop_never_nulls_foreign_consumer(self) -> None:
        engine, stream = self._engine()

        class Owner:
            def process_chunk(self, chunk):
                pass

        foreign = Owner().process_chunk
        stream._consumer = foreign
        engine._barge_in_active = True  # simulate stale active flag
        engine.stop_barge_in()
        self.assertIs(stream._consumer, foreign)


if __name__ == "__main__":
    unittest.main()
