"""
brain/llm.py

Provider-neutral LLM entry point for JARVIS reasoning.

``Brain`` / ``Reasoner`` / ``UtteranceClassifier`` use only this module
(``LLM.ask`` / ``health_check`` / ``is_available``) and never see provider
HTTP details, which live in ``brain.llm_providers``.

Provider selection (``config.settings.llm_provider``):
  * ``gemini`` (default when ``GEMINI_API_KEY`` is configured) — Google
    Gemini online API.  Reduces local CPU/RAM load to zero for reasoning.
  * ``ollama`` — legacy local server.  Used automatically when no online
    key is configured, or when explicitly selected.  Ollama is NOT removed.

``OllamaError`` is still importable from here for backward compatibility.
"""

from __future__ import annotations

import logging
from typing import Any

from brain.llm_providers import (
    GeminiError,
    GeminiProvider,
    LLMError,
    LLMProvider,
    OllamaError,
    OllamaProvider,
)
from config.settings import settings

logger = logging.getLogger(__name__)

__all__ = ["LLM", "LLMError", "OllamaError", "GeminiError"]


class LLM:
    """
    Dispatcher over the configured reasoning provider.

    Single responsibility preserved: send a prompt, return generated text.
    No memory, no parsing, no side effects.  Provider is resolved lazily
    (never on a hot path) and never probed per request — providers carry
    their own fail-fast cool-down.
    """

    def __init__(self, provider: LLMProvider | None = None) -> None:
        # Legacy attributes retained: older tests and debuggers poke these
        # directly (see tests/test_voice_pipeline_fixes.py).  When set
        # manually they act as overrides for the legacy Ollama path.
        from config.settings import OLLAMA_CONNECTION_TIMEOUT

        self._endpoint = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
        self._model = settings.model
        self._timeout = settings.timeout
        self._connection_timeout = OLLAMA_CONNECTION_TIMEOUT
        self._unavailable = False
        self._unavailable_at: float | None = None
        self._last_health_ok: bool | None = None
        self._last_health_at: float | None = None
        self._provider: LLMProvider | None = provider

    # ------------------------------------------------------------------
    # Provider resolution
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        """Active provider id ("gemini" / "ollama"). Never probes."""
        return self._ensure_provider().name

    def _ensure_provider(self) -> LLMProvider:
        # getattr: tests construct LLM.__new__ and poke legacy attrs
        # directly, bypassing __init__ (see test_ollama_unavailable_fallback).
        if getattr(self, "_provider", None) is not None:
            return self._provider  # type: ignore[no-any-return]
        configured = ""
        try:
            configured = (settings.llm_provider or "").strip().casefold()
        except Exception:
            configured = ""
        if configured == "gemini":
            key = ""
            try:
                key = (settings.gemini_api_key or "").strip()
            except Exception:
                key = ""
            if key:
                self._provider = GeminiProvider()
                logger.info(
                    "LLM provider: gemini (model=%s)", self._provider._model
                )
                return self._provider
            logger.warning(
                "LLM provider configured as gemini but GEMINI_API_KEY is "
                "missing — using legacy Ollama path."
            )
        self._provider = self._legacy_ollama_provider()
        return self._provider

    def _legacy_ollama_provider(self) -> OllamaProvider:
        """Build the legacy provider, honouring manually overridden attrs
        (used by tests that construct ``LLM.__new__`` and poke fields)."""
        provider = OllamaProvider.__new__(OllamaProvider)
        provider._endpoint = getattr(
            self, "_endpoint",
            f"{settings.ollama_base_url.rstrip('/')}/api/generate",
        )
        provider._model = getattr(self, "_model", settings.model)
        provider._timeout = getattr(self, "_timeout", settings.timeout)
        provider._connection_timeout = getattr(
            self, "_connection_timeout", 3.0
        )
        provider._unavailable = getattr(self, "_unavailable", False)
        provider._unavailable_at = getattr(self, "_unavailable_at", None)
        provider._last_health_ok = getattr(self, "_last_health_ok", None)
        provider._last_health_at = getattr(self, "_last_health_at", None)
        return provider

    def _sync_legacy_state(self, provider: OllamaProvider) -> None:
        """Mirror legacy provider state back onto our compat attributes so
        direct attribute readers (tests, debuggers) observe reality."""
        for attr in (
            "_unavailable", "_unavailable_at",
            "_last_health_ok", "_last_health_at",
        ):
            try:
                setattr(self, attr, getattr(provider, attr))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public API (unchanged contract)
    # ------------------------------------------------------------------

    def ask(
        self,
        prompt: str,
        timeout: float | None = None,
        tools: list[dict] | None = None,
    ) -> str:
        """
        Send *prompt* to the active provider and return the full text.

        Args:
            prompt: The raw prompt string.  Must not be empty.
            timeout: Optional per-request timeout override (provider
                read budget).  Nested callers pass the parent budget's
                remaining time (PART 11).
            tools: Optional JSON function declarations.  Forwarded to
                providers with function-calling support; the reply is
                still returned as inert text for the local layers.

        Returns:
            The model's complete text response as a single string.

        Raises:
            ValueError: If *prompt* is empty.
            LLMError (OllamaError / GeminiError): On provider failure.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        provider = self._ensure_provider()
        try:
            return provider.ask(prompt, timeout=timeout, tools=tools)
        finally:
            if isinstance(provider, OllamaProvider):
                self._sync_legacy_state(provider)

    @property
    def is_available(self) -> bool | None:
        """Last known reachability: True/False, None if unchecked."""
        try:
            return self._ensure_provider().is_available
        except Exception:
            return self._last_health_ok

    def health_check(self, timeout: float = 2.0) -> bool:
        """Lazy reachability probe (startup/recovery only — never per
        request).  Delegates to the active provider.  Never raises."""
        try:
            ok = self._ensure_provider().health_check(timeout=timeout)
        except Exception as exc:
            logger.warning("LLM health check failed (%s).", exc)
            ok = False
        try:
            self._last_health_ok = ok
            from time import monotonic

            self._last_health_at = monotonic()
        except Exception:
            pass
        return ok
