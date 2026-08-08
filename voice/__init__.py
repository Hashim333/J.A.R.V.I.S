"""Voice subsystem public exports.

The active voice path is the full-duplex streaming pipeline
(``voice.duplex`` + ``voice.streaming_stt``); the legacy one-shot Google
STT stack was removed in FIX-002.
"""

from voice.elevenlabs_provider import ElevenLabsProvider
from voice.manager import VoiceManager
from voice.provider import SpeechProvider, VoiceProvider, VoiceProviderError
from voice.synonym_engine import CanonicalResult, SynonymEngine
from voice.system_provider import SystemProvider

__all__ = [
    "CanonicalResult",
    "ElevenLabsProvider",
    "SpeechProvider",
    "SynonymEngine",
    "SystemProvider",
    "VoiceManager",
    "VoiceProvider",
    "VoiceProviderError",
]
