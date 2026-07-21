"""
dev_tests/test_voice_pipeline.py

Deterministic unit tests for voice.pipeline.VoiceConversationPipeline.

These tests do NOT require microphone hardware, real speech, or
real speech recognition.  All external dependencies are mocked.
"""

from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock, patch

from voice.pipeline import VoiceConversationPipeline
from voice.speech_recognition import SpeechRecognitionResult


class FakeAudioData:
    """Minimal stand-in for sr.AudioData."""
    def __init__(self, frame_data: bytes = b"audio", sample_rate: int = 16000, sample_width: int = 2):
        self.frame_data = frame_data
        self.sample_rate = sample_rate
        self.sample_width = sample_width


class TestVoiceConversationPipeline(unittest.TestCase):
    """Tests for the VoiceConversationPipeline class."""

    def setUp(self) -> None:
        self.listener_service = MagicMock()
        self.voice_manager = MagicMock()
        self.microphone_stream = MagicMock()
        self.wake_event = threading.Event()

    def make_pipeline(self, **kwargs: object) -> VoiceConversationPipeline:
        return VoiceConversationPipeline(
            listener_service=self.listener_service,
            voice_manager=self.voice_manager,
            microphone_stream=self.microphone_stream,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Successful flow
    # ------------------------------------------------------------------

    def test_successful_capture_and_transcription(self) -> None:
        """Happy path: wake → capture → transcribe → return text."""
        self.wake_event.set()
        self.microphone_stream.capture_utterance.return_value = FakeAudioData()
        self.listener_service.transcribe.return_value = SpeechRecognitionResult(
            success=True, text="open notepad",
        )

        pipeline = self.make_pipeline(max_retries=3)
        result = pipeline.wait_for_command(self.wake_event)

        self.assertEqual(result, "open notepad")
        self.microphone_stream.capture_utterance.assert_called_once_with(timeout=10.0)
        self.listener_service.transcribe.assert_called_once()
        self.voice_manager.speak.assert_any_call("Yes?")
        self.assertFalse(self.wake_event.is_set(), "Event should be cleared after wake")

    def test_calls_beep_and_yes_on_wake(self) -> None:
        """Confirmation sound and 'Yes?' are played after wake detection."""
        self.wake_event.set()
        self.microphone_stream.capture_utterance.return_value = FakeAudioData()
        self.listener_service.transcribe.return_value = SpeechRecognitionResult(
            success=True, text="hello",
        )

        pipeline = self.make_pipeline()
        pipeline.wait_for_command(self.wake_event)

        self.voice_manager.speak.assert_any_call("Yes?")

    # ------------------------------------------------------------------
    # Retry behaviour
    # ------------------------------------------------------------------

    def test_retries_on_no_audio(self) -> None:
        """When no audio is captured, retry up to max_retries, then return None."""
        self.wake_event.set()
        self.microphone_stream.capture_utterance.return_value = None

        pipeline = self.make_pipeline(max_retries=3)
        result = pipeline.wait_for_command(self.wake_event)

        self.assertIsNone(result)
        self.assertEqual(self.microphone_stream.capture_utterance.call_count, 3)
        self.listener_service.transcribe.assert_not_called()

    def test_retries_on_stt_failure(self) -> None:
        """When STT returns failure, retry up to max_retries, then return None."""
        self.wake_event.set()
        self.microphone_stream.capture_utterance.return_value = FakeAudioData()
        self.listener_service.transcribe.return_value = SpeechRecognitionResult(
            success=False, error="No speech could be recognized.",
        )

        pipeline = self.make_pipeline(max_retries=3)
        result = pipeline.wait_for_command(self.wake_event)

        self.assertIsNone(result)
        self.assertEqual(self.microphone_stream.capture_utterance.call_count, 3)
        self.assertEqual(self.listener_service.transcribe.call_count, 3)

    def test_retries_speaks_retry_prompts(self) -> None:
        """Appropriate retry prompts are spoken on failure."""
        self.wake_event.set()
        self.microphone_stream.capture_utterance.return_value = FakeAudioData()
        self.listener_service.transcribe.return_value = SpeechRecognitionResult(
            success=False, error="No speech could be recognized.",
        )

        pipeline = self.make_pipeline(max_retries=3)
        pipeline.wait_for_command(self.wake_event)

        # Yes? + 2 repeats + 1 sorry = 4
        self.assertEqual(self.voice_manager.speak.call_count, 4)
        calls = [c[0][0] for c in self.voice_manager.speak.call_args_list]
        self.assertIn("Yes?", calls)
        self.assertIn("I didn't catch that. Please repeat.", calls)
        self.assertIn("Sorry, I could not understand that.", calls)

    def test_recovers_after_retry(self) -> None:
        """After an initial failure, a subsequent attempt succeeds."""
        self.wake_event.set()
        self.microphone_stream.capture_utterance.side_effect = [
            None,
            FakeAudioData(),
        ]
        self.listener_service.transcribe.return_value = SpeechRecognitionResult(
            success=True, text="open calculator",
        )

        pipeline = self.make_pipeline(max_retries=3)
        result = pipeline.wait_for_command(self.wake_event)

        self.assertEqual(result, "open calculator")
        # Two capture attempts (first was None, second succeeded)
        self.assertEqual(self.microphone_stream.capture_utterance.call_count, 2)
        self.listener_service.transcribe.assert_called_once()

    def test_single_retry_no_repeat_prompt(self) -> None:
        """With max_retries=1, no 'repeat' prompt is issued on failure."""
        self.wake_event.set()
        self.microphone_stream.capture_utterance.return_value = None

        pipeline = self.make_pipeline(max_retries=1)
        pipeline.wait_for_command(self.wake_event)

        # 1 beep prompt (Yes?) + 1 final sorry = 2 calls
        # No "repeat" because there's no retry after the only attempt
        self.assertEqual(self.voice_manager.speak.call_count, 2)
        calls = [c[0][0] for c in self.voice_manager.speak.call_args_list]
        self.assertIn("Sorry, I could not understand that.", calls)

    # ------------------------------------------------------------------
    # Empty / edge text
    # ------------------------------------------------------------------

    def test_empty_text_from_stt_treated_as_failure(self) -> None:
        """Empty recognized text is treated as a failure and retried."""
        self.wake_event.set()
        self.microphone_stream.capture_utterance.return_value = FakeAudioData()
        self.listener_service.transcribe.return_value = SpeechRecognitionResult(
            success=True, text="",
        )

        pipeline = self.make_pipeline(max_retries=2)
        result = pipeline.wait_for_command(self.wake_event)

        self.assertIsNone(result)
        self.assertEqual(self.microphone_stream.capture_utterance.call_count, 2)

    # ------------------------------------------------------------------
    # Voice manager is optional
    # ------------------------------------------------------------------

    def test_no_voice_manager_does_not_crash(self) -> None:
        """Pipeline works without a voice manager (speak is a no-op)."""
        self.wake_event.set()
        self.microphone_stream.capture_utterance.return_value = FakeAudioData()
        self.listener_service.transcribe.return_value = SpeechRecognitionResult(
            success=True, text="hello",
        )

        pipeline = VoiceConversationPipeline(
            listener_service=self.listener_service,
            voice_manager=None,
            microphone_stream=self.microphone_stream,
        )
        result = pipeline.wait_for_command(self.wake_event)

        self.assertEqual(result, "hello")

    # ------------------------------------------------------------------
    # Logging output verification
    # ------------------------------------------------------------------

    @patch("voice.pipeline.logger")
    def test_logging_on_wake(self, mock_logger: MagicMock) -> None:
        """'Wake detected' and 'Waiting for user' are logged."""
        self.wake_event.set()
        self.microphone_stream.capture_utterance.return_value = FakeAudioData()
        self.listener_service.transcribe.return_value = SpeechRecognitionResult(
            success=True, text="test",
        )

        pipeline = self.make_pipeline()
        pipeline.wait_for_command(self.wake_event)

        mock_logger.info.assert_any_call("Wake detected")
        mock_logger.info.assert_any_call("Waiting for user")

    @patch("voice.pipeline.logger")
    def test_logging_on_successful_stt(self, mock_logger: MagicMock) -> None:
        """STT success and recognized text are logged."""
        self.wake_event.set()
        self.microphone_stream.capture_utterance.return_value = FakeAudioData()
        self.listener_service.transcribe.return_value = SpeechRecognitionResult(
            success=True, text="open notepad",
        )

        pipeline = self.make_pipeline()
        pipeline.wait_for_command(self.wake_event)

        mock_logger.info.assert_any_call("STT success: '%s'", "open notepad")
        mock_logger.info.assert_any_call("Recognized text: '%s'", "open notepad")

    @patch("voice.pipeline.logger")
    def test_logging_on_stt_failure(self, mock_logger: MagicMock) -> None:
        """STT failure is logged with warning level."""
        self.wake_event.set()
        self.microphone_stream.capture_utterance.return_value = FakeAudioData()
        self.listener_service.transcribe.return_value = SpeechRecognitionResult(
            success=False, error="No speech could be recognized.",
        )

        pipeline = self.make_pipeline(max_retries=1)
        pipeline.wait_for_command(self.wake_event)

        mock_logger.warning.assert_any_call(
            "STT failure (attempt %d/%d): %s",
            1, 1, "No speech could be recognized.",
        )

    @patch("voice.pipeline.logger")
    def test_logging_on_no_audio(self, mock_logger: MagicMock) -> None:
        """No-audio warning is logged."""
        self.wake_event.set()
        self.microphone_stream.capture_utterance.return_value = None

        pipeline = self.make_pipeline(max_retries=1)
        pipeline.wait_for_command(self.wake_event)

        mock_logger.warning.assert_any_call(
            "No audio captured (attempt %d/%d)",
            1, 1,
        )


if __name__ == "__main__":
    unittest.main()
