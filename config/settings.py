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


def _bool_env(key: str, default: bool) -> bool:
    """Parse a boolean from an environment variable."""
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes"}


def _load() -> Settings:
    """Construct Settings from environment variables with safe defaults."""
    return Settings(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
        timeout=int(os.getenv("OLLAMA_TIMEOUT", "30")),
        debug=_bool_env("DEBUG", default=False),
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