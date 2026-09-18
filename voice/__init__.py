"""Voice subsystem public exports.

The active voice path is the full-duplex pipeline
(``voice.duplex`` + ``voice.whisper_stt``, with ``voice.silero_vad`` for
capture/barge-in activity detection); the legacy one-shot Google STT stack
was removed in FIX-002 and the Vosk streaming transcriber
(``voice.streaming_stt``) is retained only as the shared ``FinalTranscript``
result type and a tested-but-inactive fallback engine.
"""

from voice.elevenlabs_provider import ElevenLabsProvider
from voice.manager import VoiceManager
from voice.piper_provider import PiperProvider
from voice.provider import SpeechProvider, VoiceProvider, VoiceProviderError
from voice.synonym_engine import CanonicalResult, SynonymEngine
from voice.system_provider import SystemProvider

__all__ = [
    "CanonicalResult",
    "ElevenLabsProvider",
    "PiperProvider",
    "SpeechProvider",
    "SynonymEngine",
    "SystemProvider",
    "VoiceManager",
    "VoiceProvider",
    "VoiceProviderError",
]
