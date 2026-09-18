"""
brain/llm_providers.py

Provider-neutral LLM layer for JARVIS reasoning.

``Brain`` / ``Reasoner`` / ``UtteranceClassifier`` only ever talk to
``brain.llm.LLM`` (``ask`` / ``health_check`` / ``is_available``) and never
see provider HTTP details.  Each provider below implements the small
``LLMProvider`` contract:

    name            human-readable provider id ("gemini", "ollama", ...)
    ask(prompt, timeout) -> str   full generated text (never streams)
    health_check(timeout) -> bool lazy reachability probe, cached
    is_available                   last-known reachability

Design rules (P0 migration):
  * Ollama stays as the legacy provider; nothing requires it for normal
    conversation when an online provider is configured.
  * Failover is bounded (one retry, transient errors only), observable
    (every outcome is logged with latency), safe (tool execution stays
    local — providers return text only), and non-looping (fail-fast
    cool-down after a failure, no per-request health probes).
  * Secrets never reach logs: request URLs carry the API key by provider
    convention, so all logging and raised errors are scrubbed.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests

from monitoring.turn_trace import mark as turn_mark

logger = logging.getLogger(__name__)

# How long a failed provider stays in fail-fast cool-down before the next
# real attempt (mirrors the legacy Ollama behaviour callers rely on).
_FAIL_FAST_SECONDS = 30.0

# Upper bound for one provider read even when the caller passes no budget.
# The reasoner additionally bounds the call on its own worker, so this is
# a backstop, not the UX latency (normal Gemini answers land in ~1-3 s).
_MAX_READ_SECONDS = 15.0

# Never emit more than this many chars of provider payloads/errors.
_LOG_CLIP = 200

_KEY_PATTERN = re.compile(r"((?:[?&]|\b)key=)[^&\s]+")


def _scrub(text: str) -> str:
    """Remove API keys from text before logging / raising."""
    try:
        return _KEY_PATTERN.sub(r"\1***", str(text))
    except Exception:
        return "<unscrubbable>"


class LLMError(Exception):
    """Base class for all LLM provider failures."""


class OllamaError(LLMError):
    """Raised when the (legacy) Ollama server returns an error or is
    unreachable.  Kept as a distinct subclass so existing callers and
    tests that catch ``OllamaError`` keep working unchanged."""


class GeminiError(LLMError):
    """Raised when the Gemini online provider fails."""


class _TransientError(Exception):
    """Internal: retryable provider failure (timeout/connection/5xx)."""


class LLMProvider:
    """Minimal contract every reasoning provider implements.

    ``tools`` is an optional list of JSON function declarations forwarded
    to providers that support function calling.  Providers return the
    model's reply as text only — any tool request inside it is parsed by
    the existing local layers; nothing executes here.
    """

    name = "unknown"

    def ask(
        self,
        prompt: str,
        timeout: float | None = None,
        tools: list[dict] | None = None,
    ) -> str:
        raise NotImplementedError

    def health_check(self, timeout: float = 2.0) -> bool:
        raise NotImplementedError

    @property
    def is_available(self) -> bool | None:
        raise NotImplementedError


class _FailFastMixin:
    """Shared fail-fast cool-down bookkeeping (no per-request probes)."""

    _unavailable: bool = False
    _unavailable_at: float | None = None
    _last_health_ok: bool | None = None
    _last_health_at: float | None = None

    def _in_cooldown(self) -> bool:
        if not self._unavailable:
            return False
        elapsed = 0.0
        if self._unavailable_at is not None:
            elapsed = time.monotonic() - self._unavailable_at
        if elapsed < _FAIL_FAST_SECONDS:
            return True
        self._unavailable = False
        self._unavailable_at = None
        return False

    def _mark_down(self) -> None:
        self._unavailable = True
        self._unavailable_at = time.monotonic()

    def _mark_up(self) -> None:
        if self._unavailable:
            self._unavailable = False
            self._unavailable_at = None

    @property
    def is_available(self) -> bool | None:
        if self._unavailable:
            return False
        return self._last_health_ok


class OllamaProvider(_FailFastMixin, LLMProvider):
    """Legacy local Ollama provider.  Logic preserved verbatim from the
    original ``brain.llm.LLM`` so existing behaviour (fail-fast windows,
    messages, timeouts) is unchanged."""

    name = "ollama"

    def __init__(
        self,
        endpoint: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        connection_timeout: float | None = None,
    ) -> None:
        from config.settings import settings, OLLAMA_CONNECTION_TIMEOUT

        self._endpoint = (
            endpoint
            or f"{settings.ollama_base_url.rstrip('/')}/api/generate"
        )
        self._model = model if model is not None else settings.model
        self._timeout = timeout if timeout is not None else settings.timeout
        self._connection_timeout = (
            connection_timeout
            if connection_timeout is not None
            else OLLAMA_CONNECTION_TIMEOUT
        )
        self._unavailable = False
        self._unavailable_at = None
        self._last_health_ok = None
        self._last_health_at = None

    def ask(
        self,
        prompt: str,
        timeout: float | None = None,
        tools: list[dict] | None = None,
    ) -> str:
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        if tools:
            logger.debug("Ollama legacy path ignores %d tool declarations", len(tools))
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }
        raw = self._post(payload, timeout=timeout)
        return self._extract_text(raw)

    def _post(self, payload: dict, timeout: float | None = None) -> dict:
        if self._in_cooldown():
            raise OllamaError(
                f"Ollama unavailable at '{self._endpoint}'. "
                "Will retry in ~30 seconds."
            )
        start = time.monotonic()
        try:
            response = requests.post(
                self._endpoint,
                json=payload,
                timeout=self._connection_timeout,
            )
        except requests.exceptions.ConnectionError as exc:
            self._mark_down()
            raise OllamaError(
                f"Cannot reach Ollama at '{self._endpoint}'. "
                "Ensure the server is running (`ollama serve`)."
            ) from exc
        except requests.exceptions.Timeout as exc:
            self._mark_down()
            raise OllamaError(
                f"Ollama request timed out after "
                f"{self._connection_timeout}s."
            ) from exc
        elapsed_ms = (time.monotonic() - start) * 1000.0

        if response.status_code != 200:
            raise OllamaError(
                f"Ollama returned HTTP {response.status_code}: {response.text[:_LOG_CLIP]}"
            )

        if self._unavailable:
            self._mark_up()
            logger.info("Ollama connection restored")
        logger.debug("Ollama ask ok (%.0f ms)", elapsed_ms)
        return response.json()

    def health_check(self, timeout: float = 2.0) -> bool:
        import urllib.request

        url = f"{self._endpoint.rsplit('/api/generate', 1)[0]}/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                ok = response.status == 200
        except Exception as exc:
            logger.warning(
                "Ollama health check failed (%s) — reasoning falls back "
                "to the rule pipeline; start it with `ollama serve`.",
                exc,
            )
            ok = False
        self._last_health_ok = ok
        self._last_health_at = time.monotonic()
        if not ok:
            self._mark_down()
        logger.info("Ollama health: %s", "reachable" if ok else "UNAVAILABLE")
        return ok

    @staticmethod
    def _extract_text(data: dict) -> str:
        try:
            return data["response"]
        except KeyError as exc:
            raise OllamaError(
                f"Unexpected Ollama response shape. Keys present: {list(data.keys())}"
            ) from exc


class GeminiProvider(_FailFastMixin, LLMProvider):
    """Google Gemini online provider (default reasoning path).

    Uses the ``generateContent`` REST endpoint (non-streaming — the
    ``LLM.ask`` contract returns full text, so streaming would change
    every caller; kept as a documented follow-up).  Tool execution stays
    local: only generated text is returned, parsed by the existing
    reasoner/classifier exactly like Ollama text was.
    """

    name = "gemini"

    _BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        from config.settings import settings

        key = (api_key if api_key is not None else settings.gemini_api_key) or ""
        self._api_key = key.strip()
        self._model = (
            (model if model is not None else settings.gemini_model) or ""
        ).strip() or "gemini-3.5-flash-lite"
        self._unavailable = False
        self._unavailable_at = None
        self._last_health_ok = None
        self._last_health_at = None

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _url(self) -> str:
        return f"{self._BASE}/{self._model}:generateContent"

    def ask(
        self,
        prompt: str,
        timeout: float | None = None,
        tools: list[dict] | None = None,
    ) -> str:
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        if not self._api_key:
            raise GeminiError(
                "Gemini API key is not configured (GEMINI_API_KEY). "
                "Falling back without contacting the network."
            )
        if self._in_cooldown():
            raise GeminiError(
                "Gemini provider in fail-fast cool-down after a recent "
                "failure. Will retry shortly."
            )
        # Bounded read: caller budget wins, otherwise the backstop.  Never
        # the legacy 30 s Ollama timeout — an online stall must surface in
        # seconds, not half a minute.
        read_timeout = timeout if timeout and timeout > 0 else _MAX_READ_SECONDS
        body: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 512},
        }
        if tools:
            # Function declarations are forwarded so the model may *request*
            # tools in its reply text; execution stays local (parsed by the
            # existing reasoner/planner layers, never run here).
            body["tools"] = [{"functionDeclarations": list(tools)}]
        start = time.monotonic()
        turn_mark(
            "LLM_REQUEST_START",
            provider=self.name,
            model=self._model,
            key_loaded=True,
        )
        try:
            text = self._post_once(body, read_timeout)
        except _TransientError as exc:
            # One bounded retry on transient failure only (network,
            # timeout, 5xx).  4xx/429 never reach here.
            logger.info(
                "Gemini: transient failure (%s) — one retry",
                _scrub(str(exc))[:_LOG_CLIP],
            )
            try:
                text = self._post_once(body, read_timeout)
            except Exception as retry_exc:
                self._mark_down()
                logger.warning(
                    "Gemini: request failed after retry (%.0f ms): %s",
                    (time.monotonic() - start) * 1000.0,
                    _scrub(str(retry_exc))[:_LOG_CLIP],
                )
                raise GeminiError(
                    "Gemini request failed (network/timeout/server)."
                ) from retry_exc
        elapsed_ms = (time.monotonic() - start) * 1000.0
        self._mark_up()
        logger.info("Gemini: ask ok (model=%s %.0f ms)", self._model, elapsed_ms)
        turn_mark(
            "LLM_RESPONSE_RECEIVED",
            provider=self.name,
            model=self._model,
            chars=len(text),
            elapsed_ms=round(elapsed_ms),
        )
        return text

    def _post_once(self, body: dict, read_timeout: float) -> str:
        start = time.monotonic()
        try:
            response = requests.post(
                self._url(),
                params={"key": self._api_key},
                json=body,
                timeout=(3.0, read_timeout),
            )
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ) as exc:
            raise _TransientError(_scrub(str(exc))) from exc
        except Exception as exc:  # noqa: BLE001 — e.g. SSLError, InvalidURL
            # Never retry, never leak: request objects can embed the URL
            # (and thus the key) in the exception text.
            self._mark_down()
            raise GeminiError(
                f"Gemini transport failure: {_scrub(str(exc))[:_LOG_CLIP]}"
            ) from exc
        elapsed_ms = (time.monotonic() - start) * 1000.0
        status = response.status_code
        if status == 200:
            return self._extract_text(response.json(), elapsed_ms)
        clipped = (response.text or "")[:_LOG_CLIP]
        if status in (400, 401, 403, 404):
            # Permanent: bad key, unknown model, bad request.  Never retry
            # (would loop on every turn); cool down and fail truthfully.
            self._mark_down()
            logger.warning(
                "Gemini: HTTP %d (%.0f ms, permanent): %s",
                status, elapsed_ms, clipped,
            )
            raise GeminiError(
                f"Gemini rejected the request (HTTP {status}). "
                "Check GEMINI_API_KEY / model name."
            )
        if status == 429:
            # Rate limited: respect it — cool down, no retry, no loop.
            self._mark_down()
            logger.warning(
                "Gemini: HTTP 429 rate-limited (%.0f ms). Cooling down.",
                elapsed_ms,
            )
            raise GeminiError("Gemini rate limit reached. Cooling down.")
        if 500 <= status < 600:
            logger.info("Gemini: HTTP %d (%.0f ms, transient)", status, elapsed_ms)
            raise _TransientError(f"HTTP {status}")
        self._mark_down()
        logger.warning("Gemini: HTTP %d (%.0f ms): %s", status, elapsed_ms, clipped)
        raise GeminiError(f"Gemini returned HTTP {status}.")

    @staticmethod
    def _extract_text(data: dict, elapsed_ms: float = 0.0) -> str:
        try:
            candidates = data.get("candidates") or []
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(
                p.get("text", "") for p in parts if isinstance(p, dict)
            ).strip()
        except (IndexError, AttributeError, TypeError) as exc:
            raise GeminiError(
                "Unexpected Gemini response shape."
            ) from exc
        if not text:
            # Safety blocks / empty candidates surface here, not as crashes.
            raise GeminiError("Gemini returned no text (empty/blocked response).")
        return text

    def health_check(self, timeout: float = 2.0) -> bool:
        """Lazy probe: a tiny generation, cached.  Called at startup and on
        recovery only — never per request (fail-fast cache covers that)."""
        if not self._api_key:
            logger.info("Gemini health: no API key — provider unconfigured")
            self._last_health_ok = False
            self._last_health_at = time.monotonic()
            return False
        try:
            self.ask("Reply with the single word: ok.", timeout=timeout)
        except Exception as exc:
            logger.warning("Gemini health check failed (%s).", _scrub(str(exc))[:_LOG_CLIP])
            self._last_health_ok = False
            self._last_health_at = time.monotonic()
            return False
        self._last_health_ok = True
        self._last_health_at = time.monotonic()
        logger.info("Gemini health: reachable (model=%s)", self._model)
        return True
