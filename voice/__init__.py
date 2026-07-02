"""Voice subsystem public exports."""

from voice.elevenlabs_provider import ElevenLabsProvider
from voice.manager import VoiceManager
from voice.microphone import MicrophoneCapture, MicrophoneManager
from voice.provider import SpeechProvider, VoiceProvider, VoiceProviderError
from voice.push_to_talk import PushToTalk
from voice.speech_recognition import SpeechRecognition, SpeechRecognitionResult
from voice.system_provider import SystemProvider

__all__ = [
    "ElevenLabsProvider",
    "MicrophoneCapture",
    "MicrophoneManager",
    "PushToTalk",
    "SpeechProvider",
    "SpeechRecognition",
    "SpeechRecognitionResult",
    "SystemProvider",
    "VoiceManager",
    "VoiceProvider",
    "VoiceProviderError",
]
