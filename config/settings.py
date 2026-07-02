"""
config/settings.py

Single source of truth for all JARVIS runtime configuration.
All values can be overridden via environment variables.
"""

import os
from dataclasses import dataclass
from pathlib import Path


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

    # --- Ollama ---
    ollama_base_url: str
    model: str
    timeout: int

    # --- General ---
    debug: bool

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
    push_to_talk_enabled: bool
    push_to_talk_key: str


def _bool_env(key: str, default: bool) -> bool:
    """Parse a boolean from an environment variable."""
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes"}


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


def _load() -> Settings:
    """Construct Settings from environment variables with safe defaults."""
    return Settings(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
        timeout=int(os.getenv("OLLAMA_TIMEOUT", "30")),
        debug=_bool_env("DEBUG", default=False),
        voice_enabled=_bool_env("VOICE_ENABLED", default=False),
        voice_provider=_str_env("VOICE_PROVIDER", "system"),
        voice_id=_str_env("VOICE_ID", ""),
        voice_model=_str_env("VOICE_MODEL", "eleven_multilingual_v2"),
        elevenlabs_api_key=_str_env("ELEVENLABS_API_KEY", ""),
        voice_stability=_float_env("VOICE_STABILITY", 0.5),
        voice_similarity=_float_env("VOICE_SIMILARITY", 0.75),
        voice_style=_float_env("VOICE_STYLE", 0.0),
        voice_speaker_boost=_bool_env("VOICE_SPEAKER_BOOST", default=True),
        push_to_talk_enabled=_bool_env("PUSH_TO_TALK_ENABLED", default=False),
        push_to_talk_key=_str_env("PUSH_TO_TALK_KEY", "F9"),
    )


# Module-level singleton — import this everywhere.
settings: Settings = _load()

# ---------------------------------------------------------------------------
# Flat aliases so brain/llm.py can import names directly:
#   from config.settings import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL: str  = settings.ollama_base_url
OLLAMA_MODEL: str     = settings.model
OLLAMA_TIMEOUT: int   = settings.timeout
DEBUG: bool           = settings.debug
VOICE_ENABLED: bool   = settings.voice_enabled
VOICE_PROVIDER: str   = settings.voice_provider
VOICE_ID: str         = settings.voice_id
VOICE_MODEL: str      = settings.voice_model
ELEVENLABS_API_KEY: str = settings.elevenlabs_api_key
VOICE_STABILITY: float = settings.voice_stability
VOICE_SIMILARITY: float = settings.voice_similarity
VOICE_STYLE: float = settings.voice_style
VOICE_SPEAKER_BOOST: bool = settings.voice_speaker_boost
PUSH_TO_TALK_ENABLED: bool = settings.push_to_talk_enabled
PUSH_TO_TALK_KEY: str = settings.push_to_talk_key
