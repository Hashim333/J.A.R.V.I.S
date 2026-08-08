"""
voice/convflow package.

A standalone, modular redesign of the JARVIS conversation flow that composes
the existing DSP building blocks (VAD, AEC, noise suppressor, streaming STT,
wake detector, voice engine) into clean, independently-testable modules:

    states        -- strict 9-state ConversationStateMachine
    request_log   -- structured per-request JSON timing/decision log
    activity      -- VoiceActivityDetector (1500 ms no-speech tolerance)
    speech        -- SpeechRecognizer (multi-turn confidence-gated ASR)
    audio         -- AudioCapture (mic + AEC/NS/AGC chain)
    wake          -- WakeWordManager (always-on, low-CPU)
    llm           -- LLMRouter (LLM-gate for valid speech only)
    commands      -- CommandDispatcher (worker-bounded executions)
    tts           -- TTSManager (interruptible TTS + AEC reference)
    conversation  -- ConversationManager (Sleep / Conversation mode)

This package is intentionally NOT wired into ``run.py`` so the existing,
working voice stack (including ``voice/pipeline.py``) and its test baseline
remain untouched.  Each module is injectable and unit-testable in isolation.
"""
from __future__ import annotations

from voice.convflow.states import (
    ConversationStateMachine,
    InvalidTransition,
    VoiceState,
)
from voice.convflow.request_log import RequestLogRecord, RequestLogStore
from voice.convflow.activity import VoiceActivityDetector
from voice.convflow.speech import SpeechRecognizer, SpeechResult
from voice.convflow.audio import AudioCapture, FeedSession
from voice.convflow.wake import WakeWordManager
from voice.convflow.llm import LLMRouter, LlmDecision
from voice.convflow.commands import CommandDispatcher, CommandResult
from voice.convflow.tts import TTSManager
from voice.convflow.conversation import (
    is_sleep_phrase,
)

__all__ = [
    "ConversationStateMachine",
    "VoiceState",
    "RequestLogRecord",
    "RequestLogStore",
    "VoiceActivityDetector",
    "SpeechRecognizer",
    "SpeechResult",
    "AudioCapture",
    "FeedSession",
    "WakeWordManager",
    "LLMRouter",
    "LlmDecision",
    "CommandDispatcher",
    "CommandResult",
    "TTSManager",
    "is_sleep_phrase",
]