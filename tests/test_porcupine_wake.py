"""
tests/test_porcupine_wake.py

Unit tests for voice/porcupine_wake.py.

The real Picovoice native library is only touched when an access key is
present; the tests inject a fake ``pvporcupine`` module to exercise the
buffer/process path, and assert the graceful off-switch when no key is set.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from voice.porcupine_wake import PorcupineWakeWord


class _FakePorcupine:
    frame_length = 512

    def __init__(self) -> None:
        self.processed = 0
        self.deleted = False

    def process(self, frame) -> int:
        self.processed += 1
        # keyword heard when the frame contains a non-silent marker
        return 1 if b"WAKE" in frame else -1

    def delete(self) -> None:
        self.deleted = True


def _install_fake():
    fake = _FakePorcupine()
    created = {"obj": None}

    def create(**kwargs):
        created["obj"] = fake
        created["kwargs"] = kwargs
        return fake

    module = type(
        "pvporcupine",
        (),
        {"create": staticmethod(create)},
    )
    patcher = patch.dict("sys.modules", {"pvporcupine": module})
    patcher.start()
    return fake, created, patcher


class TestPorcupineDisabled(unittest.TestCase):
    def test_no_key_disables_detector(self) -> None:
        with patch.dict(
            "os.environ",
            {"JARVIS_PICOVOICE_ACCESS_KEY": ""},
            clear=False,
        ):
            detector = PorcupineWakeWord(access_key="")
        self.assertFalse(detector.available)
        self.assertFalse(detector.process_audio(b"\x00\x00" * 1024))

    def test_invalid_key_never_crashes(self) -> None:
        with patch.dict("sys.modules", {"pvporcupine": None}, clear=False):
            detector = PorcupineWakeWord(access_key="bad-key")
        self.assertFalse(detector.available)


class TestPorcupineActive(unittest.TestCase):
    def test_detection_round_trip(self) -> None:
        fake, created, patcher = _install_fake()
        try:
            detector = PorcupineWakeWord(access_key="test-key", keyword="jarvis")
            self.assertTrue(detector.available)
            self.assertEqual(created["kwargs"]["keywords"], ["jarvis"])
            # feed silence then the wake marker (512 frames * 2 bytes)
            self.assertFalse(
                detector.process_audio(b"\x00\x00" * 1024 + b"\x00\x00" * 1024)
            )
            self.assertTrue(detector.process_audio(b"WAKE" * 256 + b"\x00\x00" * 0))
        finally:
            patcher.stop()

    def test_partial_frame_buffering(self) -> None:
        fake, created, patcher = _install_fake()
        try:
            detector = PorcupineWakeWord(access_key="test-key")
            # feed 300 bytes then the rest to complete a frame
            self.assertFalse(detector.process_audio(b"\x00\x00" * 150))
            self.assertFalse(
                detector.process_audio(b"\x00\x00" * 362)
            )  # silence frame, no detect
        finally:
            patcher.stop()

    def test_reset_clears_buffer(self) -> None:
        fake, created, patcher = _install_fake()
        try:
            detector = PorcupineWakeWord(access_key="test-key")
            detector.process_audio(b"\x00\x00" * 512)  # partial leftover
            detector.reset()
            self.assertEqual(len(detector._frame_buffer), 0)
        finally:
            patcher.stop()

    def test_close_releases_native(self) -> None:
        fake, created, patcher = _install_fake()
        try:
            detector = PorcupineWakeWord(access_key="test-key")
            detector.close()
            self.assertTrue(fake.deleted)
            self.assertFalse(detector.available)
        finally:
            patcher.stop()

    def test_custom_keyword_path(self) -> None:
        fake, created, patcher = _install_fake()
        try:
            detector = PorcupineWakeWord(
                access_key="test-key", keyword_path=r"C:\models\jarvis.ppn"
            )
            self.assertEqual(
                created["kwargs"]["keyword_paths"],
                [r"C:\models\jarvis.ppn"],
            )
        finally:
            patcher.stop()


if __name__ == "__main__":
    unittest.main()
