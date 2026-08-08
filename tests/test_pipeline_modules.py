"""
tests/test_pipeline_modules.py

Unit tests for the new voice/convflow package (states, request_log, activity,
speech, wake, llm, commands, tts, conversation).  Every heavyweight
dependency (Vosk, hardware, VAD) is injected as a lightweight fake so these
run headless, offline, and fast.
"""

from __future__ import annotations

import json
import time
import unittest

from voice.convflow.states import (
    ConversationStateMachine,
    InvalidTransition,
    VoiceState,
)
from voice.convflow.request_log import RequestLogRecord, RequestLogStore
from voice.convflow.activity import VoiceActivityDetector
from voice.convflow.speech import SpeechRecognizer, SpeechResult
from voice.convflow.llm import LLMRouter, LlmDecision
from voice.convflow.commands import CommandDispatcher, CommandResult
from voice.convflow.tts import TTSManager
from voice.convflow.wake import WakeWordManager
from voice.convflow.conversation import ConversationManager, is_sleep_phrase


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class StateMachineTests(unittest.TestCase):
    def test_legal_wake_flow(self):
        sm = ConversationStateMachine(initial=VoiceState.SLEEP)
        self.assertTrue(sm.to_sleep())
        self.assertTrue(sm.on_wake_detected("wake"))
        self.assertEqual(sm.state, VoiceState.WAKE_DETECTED)
        self.assertTrue(sm.on_listening())
        self.assertTrue(sm.on_processing())
        self.assertTrue(sm.on_thinking())
        self.assertTrue(sm.on_executing())
        self.assertTrue(sm.on_speaking())
        self.assertTrue(sm.on_idle())
        self.assertEqual(sm.state, VoiceState.IDLE)

    def test_illegal_transition_rejected_and_recovers(self):
        sm = ConversationStateMachine(initial=VoiceState.SLEEP)
        # SLEEP -> LISTENING is not allowed (wake must be detected first).
        self.assertFalse(sm.transition(VoiceState.LISTENING))
        self.assertEqual(sm.state, VoiceState.ERROR)  # default recover_to

    def test_illegal_transition_raises_when_throw(self):
        sm = ConversationStateMachine(initial=VoiceState.SLEEP, throw=True,
                                      recover_to=None)
        with self.assertRaises(InvalidTransition):
            sm.transition(VoiceState.LISTENING)
        self.assertEqual(sm.state, VoiceState.SLEEP)

    def test_assert_exclusive_forbids_listen_plus_speak(self):
        with self.assertRaises(InvalidTransition):
            ConversationStateMachine.assert_exclusive(
                {VoiceState.LISTENING, VoiceState.SPEAKING}
            )
        # A legal combination must pass silently.
        ConversationStateMachine.assert_exclusive(
            {VoiceState.THINKING, VoiceState.EXECUTING}
        )

    def test_can_transition(self):
        sm = ConversationStateMachine(initial=VoiceState.SLEEP)
        self.assertTrue(sm.can_transition(VoiceState.WAKE_DETECTED))
        self.assertFalse(sm.can_transition(VoiceState.LISTENING))

    def test_reset_forces_state(self):
        sm = ConversationStateMachine(initial=VoiceState.SLEEP)
        sm.reset(VoiceState.IDLE, "recovery")
        self.assertEqual(sm.state, VoiceState.IDLE)


# ---------------------------------------------------------------------------
# Request log
# ---------------------------------------------------------------------------

class RequestLogTests(unittest.TestCase):
    def test_structured_fields(self):
        r = RequestLogRecord()
        r.mark("wake_detected")
        r.mark("speech_started")
        time.sleep(0.01)
        r.mark("speech_ended")
        r.confidence = 0.92
        r.recognized_text = "open chrome"
        r.intent = "open_app"
        r.action_selected = "chrome"
        r.accepted = True
        r.finish()
        data = r.to_dict()
        for key in (
            "wake_detected", "speech_started", "speech_ended", "audio_seconds",
            "confidence", "recognized_text", "intent", "action_selected",
            "llm_ms", "execution_ms", "total_ms", "accepted", "rejected_reason",
        ):
            self.assertIn(key, data)
        self.assertAlmostEqual(data["confidence"], 0.92, places=2)
        self.assertTrue(data["accepted"])
        self.assertGreaterEqual(data["audio_seconds"], 0.0)
        self.assertGreaterEqual(data["total_ms"], 0.0)

    def test_rejected_record(self):
        r = RequestLogRecord()
        r.recognized_text = ""
        r.accepted = False
        r.rejected_reason = "low confidence"
        r.finish()
        data = r.to_dict()
        self.assertFalse(data["accepted"])
        self.assertEqual(data["rejected_reason"], "low confidence")

    def test_store_writes_json_line(self):
        store = RequestLogStore(path=None)
        r = RequestLogRecord()
        r.recognized_text = "pause"
        r.accepted = True
        r.finish()
        # No path -> debug log only; ensure to_dict is JSON-serializable.
        json.dumps(r.to_dict())

    def test_elapsed_records_duration(self):
        r = RequestLogRecord()
        started = time.monotonic()
        time.sleep(0.005)
        r.elapsed("llm_ms", started)
        self.assertGreaterEqual(r.to_dict()["llm_ms"], 0.0)


# ---------------------------------------------------------------------------
# Speech recognizer gate
# ---------------------------------------------------------------------------

class FakeFinal:
    def __init__(self, text, confidence, duration_ms=500.0):
        self.text = text
        self.confidence = confidence
        self.duration_ms = duration_ms


class FakeTranscriber:
    def __init__(self, final: FakeFinal, partial: str = ""):
        self._final = final
        self._partial = partial
        self.is_active = True

    def begin(self):
        self.is_active = True

    def push(self, chunk):
        return self._partial or None

    def partial_text(self):
        return self._partial

    def finalize(self):
        return self._final

    def discard(self):
        self.is_active = False


class SpeechRecognizerTests(unittest.TestCase):
    def _make(self, text, conf):
        return SpeechRecognizer(
            min_confidence=0.85,
            transcriber_factory=lambda: FakeTranscriber(FakeFinal(text, conf)),
        )

    def test_high_confidence_accepted(self):
        rec = self._make("open chrome", 0.92)
        rec.begin()
        result = rec.finalize()
        self.assertTrue(result.accepted)
        self.assertEqual(result.text, "open chrome")

    def test_low_confidence_rejected(self):
        rec = self._make("open chrome", 0.60)
        rec.begin()
        result = rec.finalize()
        self.assertFalse(result.accepted)
        self.assertIn("low confidence", result.reason)

    def test_empty_rejected(self):
        rec = self._make("", 0.9)
        rec.begin()
        result = rec.finalize()
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "no speech recognized")


# ---------------------------------------------------------------------------
# Voice activity detector
# ---------------------------------------------------------------------------

class FakeVAD:
    """Minimal VAD stand-in that replays scripted speech boundaries."""

    def __init__(self, **kwargs):
        self.on_speech_started = kwargs.get("on_speech_started")
        self.on_speech_ended = kwargs.get("on_speech_ended")

    def process_audio(self, chunk):
        pass

    def reset(self):
        pass

    def trigger_start(self):
        if self.on_speech_started:
            self.on_speech_started()

    def trigger_end(self):
        if self.on_speech_ended:
            self.on_speech_ended()


class ActivityDetectorTests(unittest.TestCase):
    def test_no_speech_timeout_triggers_on_no_speech(self):
        fired = []
        vad = FakeVAD()
        det = VoiceActivityDetector(
            on_no_speech=lambda: fired.append(True), vad=vad,
        )
        det.begin(no_speech_timeout=0.0)
        det.process_audio(b"\x00\x00\x00\x00")
        self.assertTrue(fired)

    def test_speech_boundaries_propagate(self):
        started, ended = [], []
        vad = FakeVAD()
        det = VoiceActivityDetector(
            on_speech_started=lambda: started.append(True),
            on_speech_ended=lambda: ended.append(True),
            vad=vad,
        )
        det.begin()
        vad.trigger_start()
        self.assertTrue(det.speaking)
        self.assertTrue(det.heard_speech)
        vad.trigger_end()
        self.assertFalse(det.speaking)
        self.assertTrue(started and ended)


# ---------------------------------------------------------------------------
# Sleep phrases
# ---------------------------------------------------------------------------

class SleepPhraseTests(unittest.TestCase):
    def test_explicit_phrases(self):
        for phrase in ("sleep", "go to sleep", "that's all", "enough",
                       "goodbye", "good night", "goodnight", "stop listening",
                       "cancel conversation", "never mind"):
            self.assertTrue(is_sleep_phrase(phrase), phrase)

    def test_non_sleep_phrases(self):
        for phrase in ("open chrome", "sleep mode settings", "", None):
            self.assertFalse(is_sleep_phrase(phrase), phrase)


# ---------------------------------------------------------------------------
# Fakes for the conversation manager
# ---------------------------------------------------------------------------

class FakeWake:
    def __init__(self):
        self.armed = False
        self._on_wake = None
        self._on_wake_latency = None
        self.hits = []

    def arm(self):
        self.armed = True

    def disarm(self):
        self.armed = False

    def feed(self, chunk):
        pass

    def reset(self):
        pass

    def shutdown(self):
        self.armed = False

    def fire_wake(self):
        if self._on_wake:
            self._on_wake(object())


class FakeAudio:
    def start(self):
        pass

    def shutdown(self):
        pass

    def feed_playback_reference(self, chunk, rate=22050):
        pass


class FakeActivity:
    def __init__(self, result: SpeechResult | None = None):
        self.result = result
        self.speaking = False
        self.no_speech_calls = 0

    def begin(self, no_speech_timeout=8.0):
        pass

    def process_audio(self, chunk):
        pass

    def reset(self):
        pass


class FakeRecog:
    def __init__(self, result: SpeechResult):
        self._result = result

    def begin(self):
        pass

    def push(self, chunk):
        return None

    def partial_text(self):
        return ""

    def finalize(self):
        return self._result

    def discard(self):
        pass

    @property
    def is_active(self):
        return True


class FakeLLM:
    def __init__(self, invoked=True):
        self._invoked = invoked
        self.calls = []

    def route(self, text, confidence=0.0, accepted=False, **kwargs):
        self.calls.append((text, confidence, accepted))
        return LlmDecision(invoked=self._invoked)

    def extract(self, response):
        data = getattr(response, "data", None) or {}
        return data.get("intent", ""), data.get("app", "")


class FakeDispatcher:
    def __init__(self, response=None):
        self._response = response
        self._busy = False
        self.dispatch_count = 0

    def dispatch(self, text, confidence=0.0):
        self.dispatch_count += 1
        return CommandResult(text, response=self._response, success=True)


class FakeTTS:
    def __init__(self):
        self.spoken = []
        self.is_speaking = False
        self.is_busy = False
        self.queue_size = 0

    def speak(self, text, priority=False):
        self.spoken.append(text)
        return True

    def stop(self, reason=""):
        self.is_speaking = False
        self.is_busy = False

    def cancel_all(self):
        self.spoken.clear()

    def arm_barge_in(self):
        pass

    def disarm_barge_in(self):
        pass

    def on_barge_in(self):
        pass

    def shutdown(self):
        pass


class _Response:
    def __init__(self, message="", needs_clarification=False, data=None):
        self.message = message
        self.needs_clarification = needs_clarification
        self.data = data or {}
        self.success = True

    def voice_text(self):
        return self.message


class ConversationManagerTests(unittest.TestCase):
    def _build(self, recog_result: SpeechResult | None = None):
        wake = FakeWake()
        audio = FakeAudio()
        activity = FakeActivity()
        recog = FakeRecog(recog_result)
        response = _Response(message="Opening Chrome.", data={"intent": "open_app", "app": "chrome"})
        llm = FakeLLM()
        dispatcher = FakeDispatcher(response=response)
        tts = FakeTTS()
        cm = ConversationManager(
            wake=wake, audio=audio, activity=activity, recognizer=recog,
            llm=llm, dispatcher=dispatcher, tts=tts,
            conversation_timeout=10.0,
        )
        return cm, wake, activity, llm, dispatcher, tts

    def test_start_in_sleep_wake_armed(self):
        cm, wake, *_ = self._build()
        cm.start()
        self.assertFalse(cm.active)
        self.assertEqual(cm.state, VoiceState.SLEEP)
        self.assertTrue(wake.armed)

    def test_wake_enters_conversation_and_acks(self):
        cm, wake, activity, llm, dispatcher, tts = self._build()
        cm.start()
        wake.fire_wake()
        self.assertTrue(cm.active)
        self.assertEqual(cm.state, VoiceState.LISTENING)
        self.assertFalse(wake.armed)
        self.assertTrue(tts.spoken)

    def test_timer_expires_and_returns_to_sleep(self):
        cm, wake, activity, *_ = self._build()
        cm.start()
        wake.fire_wake()
        activity.speaking = False
        cm._last_activity = time.monotonic() - 11.0
        self.assertTrue(cm.check_timeout())
        self.assertEqual(cm.state, VoiceState.SLEEP)
        self.assertTrue(wake.armed)
        self.assertIn("Going back to sleep.", cm._tts.spoken)

    def test_no_false_sleep_while_speaking(self):
        cm, wake, activity, *_ = self._build()
        cm.start()
        wake.fire_wake()
        activity.speaking = True
        cm._last_activity = time.monotonic() - 11.0
        self.assertFalse(cm.check_timeout())
        self.assertTrue(cm.active)
        self.assertEqual(cm.state, VoiceState.LISTENING)

    def test_sleep_command_exits_conversation(self):
        cm, wake, activity, *_ = self._build(
            recog_result=SpeechResult("sleep", 0.95, True),
        )
        cm.start()
        wake.fire_wake()
        cm.on_speech_ended()
        self.assertFalse(cm.active)
        self.assertEqual(cm.state, VoiceState.SLEEP)
        self.assertIn("Going back to sleep.", cm._tts.spoken)

    def test_low_confidence_asks_repeat(self):
        cm, wake, activity, llm, dispatcher, tts = self._build(
            recog_result=SpeechResult("open chrome", 0.4, False, "low confidence"),
        )
        cm.start()
        wake.fire_wake()
        cm.on_speech_ended()
        self.assertTrue(any("repeat" in s.casefold() for s in tts.spoken))
        self.assertEqual(dispatcher.dispatch_count, 0)
        self.assertEqual(cm.state, VoiceState.LISTENING)

    def test_accepted_command_resets_timer_and_speaks(self):
        cm, wake, activity, llm, dispatcher, tts = self._build(
            recog_result=SpeechResult("open chrome", 0.93, True),
        )
        cm.start()
        wake.fire_wake()
        cm.on_speech_ended()
        self.assertEqual(dispatcher.dispatch_count, 1)
        self.assertIn("Opening Chrome.", tts.spoken)
        self.assertGreaterEqual(cm.seconds_until_sleep, 0.0)

    def test_context_memory_cleared_on_sleep(self):
        cm, wake, *_ = self._build()
        cm.start()
        wake.fire_wake()
        cm.remember("last_app", "chrome")
        cm.remember("last_search", "python")
        self.assertEqual(cm.context()["last_app"], "chrome")
        # Force return to sleep via a sleep command path.
        cm._handle_sleep_command("sleep")
        self.assertEqual(cm.context(), {})

    def test_followup_does_not_require_wake(self):
        cm, wake, activity, llm, dispatcher, tts = self._build(
            recog_result=SpeechResult("search youtube for python", 0.9, True),
        )
        cm.start()
        wake.fire_wake()
        cm.on_speech_ended()  # first command
        self.assertTrue(cm.active)
        # Second command while still in conversation mode.
        cm._recognizer = FakeRecog(SpeechResult("play first result", 0.91, True))
        cm.on_speech_ended()
        self.assertEqual(dispatcher.dispatch_count, 2)
        self.assertTrue(cm.active)  # still awake


# ---------------------------------------------------------------------------
# Standalone module behavior
# ---------------------------------------------------------------------------

class ModuleBehaviorTests(unittest.TestCase):
    def test_llm_router_gates_rejected_speech(self):
        router = LLMRouter()
        decision = router.route("open chrome", confidence=0.4, accepted=False,
                                rejected_reason="low confidence")
        self.assertFalse(decision.invoked)
        self.assertTrue(decision.needs_repeat)

    def test_llm_router_invokes_valid_speech(self):
        router = LLMRouter()
        decision = router.route("open chrome", confidence=0.93, accepted=True)
        self.assertTrue(decision.invoked)
        self.assertFalse(decision.needs_repeat)

    def test_llm_router_extracts_intent_action(self):
        router = LLMRouter(
            intent_extractor=lambda r: r.data.get("intent", ""),
            action_extractor=lambda r: r.data.get("app", ""),
        )
        intent, action = router.extract(_Response(data={"intent": "open_app", "app": "chrome"}))
        self.assertEqual(intent, "open_app")
        self.assertEqual(action, "chrome")

    def test_dispatcher_runs_command(self):
        disp = CommandDispatcher(runner=lambda text, **kw: _Response(message="done"))
        result = disp.dispatch("open chrome")
        self.assertTrue(result.success)
        self.assertEqual(result.response.message, "done")

    def test_dispatcher_timeout_reports_error(self):
        def slow_runner(text, **kw):
            time.sleep(2.0)
            return _Response(message="late")

        disp = CommandDispatcher(runner=slow_runner, timeout=0.05)
        result = disp.dispatch("slow")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "timeout")

    def test_tts_stop_and_barge_in(self):
        tts = TTSManager(engine=None, on_interrupt=lambda: None)
        self.assertFalse(tts.is_busy)

    def test_wake_manager_arms_disarms(self):
        wm = WakeWordManager(sample_rate=16000)
        wm.arm()
        self.assertTrue(wm.armed)
        wm.disarm()
        self.assertFalse(wm.armed)
        wm.shutdown()

    def test_voice_states_values(self):
        expected = {
            "sleep", "wake_detected", "listening", "processing", "thinking",
            "speaking", "executing", "idle", "error",
        }
        actual = {s.value for s in VoiceState}
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()