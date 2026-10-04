"""
config/settings.py

Single source of truth for all JARVIS runtime configuration.
All values can be overridden via environment variables or a .env file.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Project paths (resolved relative to this file so they survive cwd changes)
# ---------------------------------------------------------------------------

ROOT_DIR: Path = Path(__file__).parent.parent.resolve()
DATA_DIR: Path = ROOT_DIR / "data"
LOGS_DIR: Path = ROOT_DIR / "logs"


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    """Immutable runtime configuration for JARVIS."""

    # --- Ollama (legacy reasoning provider; kept, not required) ---
    ollama_base_url: str
    model: str
    timeout: int

    # --- LLM reasoning provider ---
    # llm_provider: "gemini" (online default when GEMINI_API_KEY is set)
    # or "ollama" (legacy local).  Brain/Planner never see this choice.
    llm_provider: str
    gemini_model: str
    gemini_api_key: str

    # --- General ---
    debug: bool
    debug_safe_mode: bool

    # --- Voice ---
    voice_enabled: bool
    voice_provider: str
    voice_id: str
    voice_model: str
    elevenlabs_api_key: str
    voice_stability: float
    voice_similarity: float
    voice_style: float
    voice_speaker_boost: bool
    voice_speed: float

    # --- Piper (local, offline TTS fallback) ---
    piper_voice_model_path: str
    piper_voice_name: str

    # --- Microphone ---
    mic_sensitivity: float
    mic_agc_enabled: bool
    mic_agc_target_level: float
    mic_noise_gate_enabled: bool
    mic_noise_gate_threshold: float
    mic_dc_removal_enabled: bool
    mic_high_pass_enabled: bool
    mic_high_pass_cutoff_hz: float
    mic_speech_normalization_enabled: bool

    # --- Speech recognition (Faster-Whisper) ---
    whisper_model: str
    whisper_language: str
    whisper_threads: int

    # --- Wake word (Porcupine, optional) ---
    # WAKE_WORD_ENABLED=false (default): direct listening — no wake word.
    # true: classic wake-gated path (the wake word must precede commands).
    wake_word_enabled: bool
    picovoice_access_key: str
    porcupine_keyword: str
    porcupine_keyword_path: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bool_env(key: str, default: bool) -> bool:
    """Parse a boolean from an environment variable."""
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _str_env(key: str, default: str) -> str:
    """Read and trim a string environment variable."""
    return os.getenv(key, default).strip()


def _float_env(key: str, default: float) -> float:
    """Parse a float environment variable with a safe default."""
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_CACHED_DIAGNOSTICS: list[str] = []


def validate_config(s: Settings) -> list[str]:
    """Validate the resolved configuration.

    Returns a list of diagnostic messages.  An empty list means all checks
    passed.
    """
    msgs: list[str] = []

    provider = s.voice_provider.strip().casefold()
    if provider not in ("system", "elevenlabs"):
        msgs.append(
            f"Invalid VOICE_PROVIDER={s.voice_provider!r}; "
            f"expected 'system' or 'elevenlabs'."
        )

    if provider == "elevenlabs":
        if not s.elevenlabs_api_key:
            msgs.append("ElevenLabs provider selected but API key is missing.")
        if not s.voice_id:
            msgs.append("ElevenLabs provider selected but VOICE_ID is missing.")
        if not s.voice_model:
            msgs.append("VOICE_MODEL must not be empty when using ElevenLabs.")

    url = s.ollama_base_url.strip()
    if not url.startswith(("http://", "https://")):
        msgs.append(
            f"OLLAMA_BASE_URL={s.ollama_base_url!r} must start with "
            f"http:// or https://."
        )

    if s.timeout < 1:
        msgs.append(f"OLLAMA_TIMEOUT={s.timeout} must be a positive integer.")

    if s.llm_provider.strip().casefold() not in ("gemini", "ollama"):
        msgs.append(
            f"Invalid JARVIS_LLM_PROVIDER={s.llm_provider!r}; "
            f"expected 'gemini' or 'ollama'."
        )
    if s.llm_provider.strip().casefold() == "gemini" and not s.gemini_api_key:
        msgs.append(
            "JARVIS_LLM_PROVIDER=gemini but GEMINI_API_KEY is missing; "
            "reasoning falls back to the legacy Ollama path."
        )
    if not s.gemini_model:
        msgs.append("JARVIS_GEMINI_MODEL must not be empty (e.g. 'gemini-3.5-flash-lite').")

    for key, val in (
        ("VOICE_STABILITY", s.voice_stability),
        ("VOICE_SIMILARITY", s.voice_similarity),
        ("VOICE_STYLE", s.voice_style),
    ):
        if not 0.0 <= val <= 1.0:
            msgs.append(
                f"{key}={val} is out of range. Must be between 0.0 and 1.0."
            )

    if not 0.7 <= s.voice_speed <= 1.2:
        msgs.append(
            f"VOICE_SPEED={s.voice_speed} is out of range. Must be between 0.7 and 1.2."
        )

    if s.mic_sensitivity < 0.0:
        msgs.append(
            f"MIC_SENSITIVITY={s.mic_sensitivity} must be >= 0.0."
        )
    if not 0.001 <= s.mic_agc_target_level <= 1.0:
        msgs.append(
            f"MIC_AGC_TARGET_LEVEL={s.mic_agc_target_level} is out of range. "
            f"Must be between 0.001 and 1.0."
        )
    if not 0.001 <= s.mic_noise_gate_threshold <= 0.5:
        msgs.append(
            f"MIC_NOISE_GATE_THRESHOLD={s.mic_noise_gate_threshold} is out of range. "
            f"Must be between 0.001 and 0.5."
        )
    if not 20.0 <= s.mic_high_pass_cutoff_hz <= 2000.0:
        msgs.append(
            f"MIC_HIGH_PASS_CUTOFF_HZ={s.mic_high_pass_cutoff_hz} is out of range. "
            f"Must be between 20.0 and 2000.0 Hz."
        )

    if not s.whisper_model:
        msgs.append("JARVIS_WHISPER_MODEL must not be empty (e.g. 'small').")

    if s.picovoice_access_key and not s.porcupine_keyword and not s.porcupine_keyword_path:
        msgs.append(
            "Porcupine enabled but neither JARVIS_PORCUPINE_KEYWORD nor "
            "JARVIS_PORCUPINE_KEYWORD_PATH is set."
        )

    return msgs


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _mask_key(key: str) -> str:
    """Mask an API key for safe display.

    >>> _mask_key("abc12345")
    'ab****45'
    >>> _mask_key("ab")
    '********'
    """
    if len(key) > 4:
        return key[:2] + "****" + key[-2:]
    return "********"


def print_config_summary(s: Settings) -> None:
    """Print a formatted summary of the active configuration."""
    api_key = s.elevenlabs_api_key
    masked = _mask_key(api_key) if api_key else "(not set)"

    lines = [
        "\nConfiguration Loaded",
        "-" * 50,
        "",
        f"  Voice Provider:   {s.voice_provider.capitalize()}",
        f"  Voice Enabled:    {'Yes' if s.voice_enabled else 'No'}",
        f"  Voice ID:         {s.voice_id or '(not set)'}",
        f"  Model:            {s.voice_model}",
        f"  Speed:            {s.voice_speed:.2f}x",
        f"  API Key:          {masked}",
        f"  Ollama URL:       {s.ollama_base_url}",
        f"  Ollama Model:     {s.model}",
        f"  Ollama Timeout:   {s.timeout}s",
        f"  LLM Provider:     {s.llm_provider} (model: {s.gemini_model}, "
        f"key: {'set' if s.gemini_api_key else 'not set'})",
        f"  Debug:            {'Yes' if s.debug else 'No'}",
        f"  Debug Safe Mode:  {'On' if s.debug_safe_mode else 'Off'}",
        f"  Mic Sensitivity:  {s.mic_sensitivity}",
        f"  Mic AGC:          {'On' if s.mic_agc_enabled else 'Off'} (target: {s.mic_agc_target_level})",
        f"  Mic Noise Gate:   {'On' if s.mic_noise_gate_enabled else 'Off'} (threshold: {s.mic_noise_gate_threshold})",
        f"  Mic Preprocess:   DC={'On' if s.mic_dc_removal_enabled else 'Off'} "
        f"HP={'On' if s.mic_high_pass_enabled else 'Off'} "
        f"({s.mic_high_pass_cutoff_hz:.0f} Hz) "
        f"SpeechNorm={'On' if s.mic_speech_normalization_enabled else 'Off'}",
        f"  Whisper Model:    {s.whisper_model} (lang: {s.whisper_language})",
        f"  Wake Word:        {'Enabled' if s.wake_word_enabled else 'Off (direct listening)'}",
        f"  Porcupine:        {'On' if s.picovoice_access_key else 'Off (local wake)'}",
        "",
    ]
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def get_diagnostics() -> tuple[str, ...]:
    """Return the most recent validation diagnostics."""
    return tuple(_CACHED_DIAGNOSTICS)


def _load() -> Settings:
    """Construct Settings from environment variables + .env file."""
    load_dotenv()

    s = Settings(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
        timeout=int(os.getenv("OLLAMA_TIMEOUT", "30")),
        llm_provider=_str_env("JARVIS_LLM_PROVIDER", "gemini"),
        gemini_model=_str_env("JARVIS_GEMINI_MODEL", "gemini-3.5-flash-lite"),
        gemini_api_key=_str_env("GEMINI_API_KEY", ""),
        debug=_bool_env("DEBUG", default=False),
        debug_safe_mode=_bool_env("DEBUG_SAFE_MODE", default=False),
        voice_enabled=_bool_env("VOICE_ENABLED", default=False),
        voice_provider=_str_env("VOICE_PROVIDER", "system"),
        voice_id=_str_env("VOICE_ID", ""),
        voice_model=_str_env("VOICE_MODEL", "eleven_multilingual_v2"),
        elevenlabs_api_key=_str_env("ELEVENLABS_API_KEY", ""),
        voice_stability=_float_env("VOICE_STABILITY", 0.5),
        voice_similarity=_float_env("VOICE_SIMILARITY", 0.75),
        voice_style=_float_env("VOICE_STYLE", 0.0),
        voice_speaker_boost=_bool_env("VOICE_SPEAKER_BOOST", default=True),
        voice_speed=_float_env("VOICE_SPEED", 1.2),
        piper_voice_model_path=_str_env(
            "PIPER_VOICE_MODEL_PATH",
            str(ROOT_DIR / "models" / "piper" / "en_US-lessac-medium.onnx"),
        ),
        piper_voice_name=_str_env("PIPER_VOICE_NAME", "en_US-lessac-medium"),
        mic_sensitivity=_float_env("MIC_SENSITIVITY", 1.0),
        mic_agc_enabled=_bool_env("MIC_AGC_ENABLED", default=True),
        mic_agc_target_level=_float_env("MIC_AGC_TARGET_LEVEL", 0.15),
        mic_noise_gate_enabled=_bool_env("MIC_NOISE_GATE_ENABLED", default=True),
        mic_noise_gate_threshold=_float_env("MIC_NOISE_GATE_THRESHOLD", 0.02),
        mic_dc_removal_enabled=_bool_env("MIC_DC_REMOVAL_ENABLED", default=True),
        mic_high_pass_enabled=_bool_env("MIC_HIGH_PASS_ENABLED", default=True),
        mic_high_pass_cutoff_hz=_float_env("MIC_HIGH_PASS_CUTOFF_HZ", 80.0),
        mic_speech_normalization_enabled=_bool_env("MIC_SPEECH_NORMALIZATION", default=True),
        whisper_model=_str_env("JARVIS_WHISPER_MODEL", "small"),
        whisper_language=_str_env("JARVIS_WHISPER_LANG", "en"),
        whisper_threads=int(os.getenv("JARVIS_WHISPER_THREADS", "0") or "0"),
        wake_word_enabled=_bool_env("WAKE_WORD_ENABLED", default=False),
        picovoice_access_key=_str_env("JARVIS_PICOVOICE_ACCESS_KEY", ""),
        porcupine_keyword=_str_env("JARVIS_PORCUPINE_KEYWORD", "monday"),
        porcupine_keyword_path=_str_env("JARVIS_PORCUPINE_KEYWORD_PATH", ""),
    )

    global _CACHED_DIAGNOSTICS
    _CACHED_DIAGNOSTICS = validate_config(s)

    if not os.getenv("PYTEST_CURRENT_TEST"):
        for msg in _CACHED_DIAGNOSTICS:
            print(f"WARNING: {msg}", file=sys.stderr)
        print_config_summary(s)

    return s


# Module-level singleton — import this everywhere.
settings: Settings = _load()

# ---------------------------------------------------------------------------
# Flat aliases so brain/llm.py can import names directly:
#   from config.settings import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL: str = settings.ollama_base_url
OLLAMA_MODEL: str = settings.model
OLLAMA_TIMEOUT: int = settings.timeout
LLM_PROVIDER: str = settings.llm_provider
GEMINI_MODEL: str = settings.gemini_model
GEMINI_API_KEY: str = settings.gemini_api_key
DEBUG: bool = settings.debug
DEBUG_SAFE_MODE: bool = settings.debug_safe_mode
VOICE_ENABLED: bool = settings.voice_enabled
VOICE_PROVIDER: str = settings.voice_provider
VOICE_ID: str = settings.voice_id
VOICE_MODEL: str = settings.voice_model
ELEVENLABS_API_KEY: str = settings.elevenlabs_api_key
VOICE_STABILITY: float = settings.voice_stability
VOICE_SIMILARITY: float = settings.voice_similarity
VOICE_STYLE: float = settings.voice_style
VOICE_SPEAKER_BOOST: bool = settings.voice_speaker_boost
VOICE_SPEED: float = settings.voice_speed
PIPER_VOICE_MODEL_PATH: str = settings.piper_voice_model_path
PIPER_VOICE_NAME: str = settings.piper_voice_name
MIC_SENSITIVITY: float = settings.mic_sensitivity
MIC_AGC_ENABLED: bool = settings.mic_agc_enabled
MIC_AGC_TARGET_LEVEL: float = settings.mic_agc_target_level
MIC_NOISE_GATE_ENABLED: bool = settings.mic_noise_gate_enabled
MIC_NOISE_GATE_THRESHOLD: float = settings.mic_noise_gate_threshold
MIC_DC_REMOVAL_ENABLED: bool = settings.mic_dc_removal_enabled
MIC_HIGH_PASS_ENABLED: bool = settings.mic_high_pass_enabled
MIC_HIGH_PASS_CUTOFF_HZ: float = settings.mic_high_pass_cutoff_hz
MIC_SPEECH_NORMALIZATION: bool = settings.mic_speech_normalization_enabled
WHISPER_MODEL: str = settings.whisper_model
WHISPER_LANGUAGE: str = settings.whisper_language
WHISPER_THREADS: int = settings.whisper_threads
WAKE_WORD_ENABLED: bool = settings.wake_word_enabled
PICOVOICE_ACCESS_KEY: str = settings.picovoice_access_key
PORCUPINE_KEYWORD: str = settings.porcupine_keyword
PORCUPINE_KEYWORD_PATH: str = settings.porcupine_keyword_path

# FIX-VOICE-003: Ollama connection timeout for fast failure detection
OLLAMA_CONNECTION_TIMEOUT: float = 3.0
