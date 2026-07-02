from __future__ import annotations

import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from voice.microphone import MicrophoneCapture, MicrophoneManager
from voice.push_to_talk import PushToTalk
from voice.speech_recognition import SpeechRecognition, SpeechRecognitionResult


class FakeSource:
    closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True
        return False


class FakeRecognizer:
    def __init__(self, *, audio="audio", text="open chrome", listen_error=None, recognize_error=None):
        self.audio = audio
        self.text = text
        self.listen_error = listen_error
        self.recognize_error = recognize_error
        self.adjusted = False

    def adjust_for_ambient_noise(self, source, duration=0.2):
        self.adjusted = True

    def listen(self, source, timeout=5.0, phrase_time_limit=10.0):
        if self.listen_error:
            raise self.listen_error
        return self.audio

    def recognize_google(self, audio, language="en-US"):
        if self.recognize_error:
            raise self.recognize_error
        return self.text


class PushToTalkTests(unittest.TestCase):
    def test_microphone_capture_opens_and_closes_once(self) -> None:
        source = FakeSource()
        recognizer = FakeRecognizer(audio="captured-audio")
        manager = MicrophoneManager(
            recognizer_factory=lambda: recognizer,
            microphone_factory=lambda: source,
        )

        result = manager.capture_once()

        self.assertTrue(result.success)
        self.assertEqual(result.audio, "captured-audio")
        self.assertTrue(source.closed)
        self.assertTrue(recognizer.adjusted)

    def test_microphone_unavailable_returns_friendly_error(self) -> None:
        manager = MicrophoneManager(
            recognizer_factory=lambda: FakeRecognizer(),
            microphone_factory=lambda: (_ for _ in ()).throw(OSError("missing mic")),
        )

        result = manager.capture_once()

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Microphone is unavailable.")

    def test_speech_recognition_success(self) -> None:
        recognizer = SpeechRecognition(
            recognizer_factory=lambda: FakeRecognizer(text="open notepad")
        )

        result = recognizer.recognize("audio")

        self.assertTrue(result.success)
        self.assertEqual(result.text, "open notepad")

    def test_speech_recognition_failure(self) -> None:
        recognizer = SpeechRecognition(
            recognizer_factory=lambda: FakeRecognizer(recognize_error=ValueError("no speech"))
        )

        result = recognizer.recognize("audio")

        self.assertFalse(result.success)
        self.assertEqual(result.error, "No speech could be recognized.")

    def test_configuration_loading(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PUSH_TO_TALK_ENABLED": "true",
                "PUSH_TO_TALK_KEY": "F10",
            },
        ):
            import config.settings as settings_module

            reloaded = importlib.reload(settings_module)

        self.assertTrue(reloaded.settings.push_to_talk_enabled)
        self.assertEqual(reloaded.settings.push_to_talk_key, "F10")

    def test_push_to_talk_workflow(self) -> None:
        microphone = SimpleNamespace(
            capture_once=lambda: MicrophoneCapture(success=True, audio="audio")
        )
        speech = SimpleNamespace(
            recognize=lambda audio: SpeechRecognitionResult(success=True, text="open chrome")
        )
        push_to_talk = PushToTalk(
            microphone=microphone,
            speech_recognition=speech,
            enabled=True,
        )

        self.assertEqual(push_to_talk.listen_once(), "open chrome")
        self.assertEqual(push_to_talk.last_error, "")

    def test_push_to_talk_disabled_does_not_open_microphone(self) -> None:
        microphone = SimpleNamespace(
            capture_once=lambda: self.fail("microphone should not open")
        )
        push_to_talk = PushToTalk(microphone=microphone, enabled=False)

        self.assertEqual(push_to_talk.listen_once(), "")
        self.assertEqual(push_to_talk.last_error, "Push-to-talk is disabled.")

    def test_push_to_talk_capture_failure(self) -> None:
        microphone = SimpleNamespace(
            capture_once=lambda: MicrophoneCapture(
                success=False,
                error="Microphone is unavailable.",
            )
        )
        push_to_talk = PushToTalk(microphone=microphone, enabled=True)

        self.assertEqual(push_to_talk.listen_once(), "")
        self.assertEqual(push_to_talk.last_error, "Microphone is unavailable.")


if __name__ == "__main__":
    unittest.main()
