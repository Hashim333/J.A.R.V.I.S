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


def _bool_env(key: str, default: bool) -> bool:
    """Parse a boolean from an environment variable."""
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes"}


def _str_env(key: str, default: str) -> str:
    """Read and trim a string environment variable."""
    return os.getenv(key, default).strip()


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
