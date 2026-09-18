"""Provider-neutral LLM tests: Gemini online path + Ollama legacy path.

No network is used — ``requests.post`` is stubbed.  Covers the P0
migration contract: parsing, bounded retry, rate-limit respect, recovery,
local-only tool execution (text-only returns), and secret hygiene.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from brain.llm import LLM, GeminiError, LLMError, OllamaError
from brain import llm_providers
from brain.llm_providers import GeminiProvider, OllamaProvider, _scrub


class _Resp:
    def __init__(self, status, text="", payload=None):
        self.status_code = status
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


def _gemini_ok(text="Hello there."):
    return _Resp(200, '{"candidates": [...]}', {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
    })


def _gemini_empty():
    return _Resp(200, "{}", {"candidates": [{"content": {"parts": []}}]})


def _provider(**kw):
    kw.setdefault("api_key", "test-key-123")
    kw.setdefault("model", "gemini-3.5-flash-lite")
    return GeminiProvider(**kw)


class TestGeminiParsing(unittest.TestCase):
    def test_success_returns_text(self) -> None:
        with patch.object(llm_providers.requests, "post",
                          return_value=_gemini_ok("Hi!")) as post:
            self.assertEqual(_provider().ask("hello", timeout=5.0), "Hi!")
            self.assertEqual(post.call_count, 1)

    def test_empty_candidates_raise(self) -> None:
        with patch.object(llm_providers.requests, "post",
                          return_value=_gemini_empty()):
            with self.assertRaises(GeminiError):
                _provider().ask("hello", timeout=5.0)

    def test_empty_prompt_rejected_without_network(self) -> None:
        with patch.object(llm_providers.requests, "post") as post:
            with self.assertRaises(ValueError):
                _provider().ask("   ")
            post.assert_not_called()

    def test_missing_key_never_touches_network(self) -> None:
        with patch.object(llm_providers.requests, "post") as post:
            with self.assertRaises(GeminiError):
                GeminiProvider(api_key="").ask("hello", timeout=5.0)
            post.assert_not_called()


class TestGeminiFailurePolicy(unittest.TestCase):
    def test_auth_failure_no_retry_and_cooldown(self) -> None:
        with patch.object(llm_providers.requests, "post",
                          return_value=_Resp(400, "API key not valid")) as post:
            p = _provider()
            with self.assertRaises(GeminiError):
                p.ask("hello", timeout=5.0)
            self.assertEqual(post.call_count, 1)  # never retried
            import time
            t0 = time.monotonic()
            with self.assertRaises(GeminiError):
                p.ask("hello", timeout=5.0)
            self.assertLess(time.monotonic() - t0, 1.0)  # fail-fast
            self.assertEqual(post.call_count, 1)  # still 1: cool-down, no loop

    def test_rate_limit_respected_no_retry(self) -> None:
        with patch.object(llm_providers.requests, "post",
                          return_value=_Resp(429, "quota")) as post:
            with self.assertRaises(GeminiError):
                _provider().ask("hello", timeout=5.0)
            self.assertEqual(post.call_count, 1)

    def test_server_error_retried_exactly_once(self) -> None:
        calls = []

        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                return _Resp(500, "backend error")
            return _gemini_ok("recovered")

        with patch.object(llm_providers.requests, "post", side_effect=flaky):
            self.assertEqual(_provider().ask("hello", timeout=5.0), "recovered")
            self.assertEqual(len(calls), 2)

    def test_persistent_500_gives_up_after_two(self) -> None:
        with patch.object(llm_providers.requests, "post",
                          return_value=_Resp(503, "down")) as post:
            with self.assertRaises(GeminiError):
                _provider().ask("hello", timeout=5.0)
            self.assertEqual(post.call_count, 2)

    def test_timeout_bounded(self) -> None:
        import requests as _rq

        with patch.object(llm_providers.requests, "post",
                          side_effect=_rq.exceptions.Timeout("slow")) as post:
            import time
            t0 = time.monotonic()
            with self.assertRaises(GeminiError):
                _provider().ask("hello", timeout=2.0)
            self.assertLess(time.monotonic() - t0, 10.0)
            self.assertEqual(post.call_count, 2)  # one bounded retry only

    def test_recovery_after_cooldown(self) -> None:
        with patch.object(llm_providers.requests, "post",
                          return_value=_Resp(400, "bad")):
            p = _provider()
            with self.assertRaises(GeminiError):
                p.ask("hello", timeout=5.0)
        # Simulate cool-down expiry without waiting 30 s.
        p._unavailable = False
        p._unavailable_at = None
        with patch.object(llm_providers.requests, "post",
                          return_value=_gemini_ok("back")) as post:
            self.assertEqual(p.ask("hello", timeout=5.0), "back")
            self.assertEqual(post.call_count, 1)


class TestSecretHygiene(unittest.TestCase):
    def test_key_scrubbed(self) -> None:
        dirty = "https://x/y?key=SECRETABC123&other=1"
        self.assertNotIn("SECRETABC123", _scrub(dirty))
        self.assertIn("key=***", _scrub(dirty))

    def test_key_never_in_raised_errors(self) -> None:
        def leaking(*a, **k):
            raise RuntimeError("failed url with key=SECRETABC123 inside")

        with patch.object(llm_providers.requests, "post", side_effect=leaking):
            try:
                _provider(api_key="SECRETABC123").ask("hello", timeout=5.0)
                self.fail("expected GeminiError")
            except GeminiError as exc:
                self.assertNotIn("SECRETABC123", str(exc))

    def test_key_never_logged(self) -> None:
        def bad_key(*a, **k):
            return _Resp(400, "API key not valid")

        with patch.object(llm_providers.requests, "post", side_effect=bad_key):
            with self.assertLogs("brain.llm_providers", level="INFO") as logs:
                try:
                    _provider(api_key="SECRETABC123").ask("hello", timeout=5.0)
                except GeminiError:
                    pass
        blob = "\n".join(logs.output)
        self.assertNotIn("SECRETABC123", blob)


class TestToolExecutionStaysLocal(unittest.TestCase):
    def test_provider_returns_text_only(self) -> None:
        evil = "```python\nimport os; os.system('x')\n```"
        with patch.object(llm_providers.requests, "post",
                          return_value=_gemini_ok(evil)):
            out = _provider().ask("do evil", timeout=5.0)
        self.assertIsInstance(out, str)
        self.assertEqual(out, evil)  # returned inertly; nothing executed

    def test_no_exec_side_effects_in_module(self) -> None:
        import inspect

        src = inspect.getsource(llm_providers)
        for token in ("os.system", "subprocess", "eval(", "exec("):
            self.assertNotIn(token, src)

    def test_tool_declarations_forwarded_inertly(self) -> None:
        seen: dict = {}

        def capture(url, params=None, json=None, timeout=None):
            seen["body"] = json
            return _gemini_ok('{"intent": "open_app"}')

        tools = [{"name": "open_app", "description": "open an app",
                  "parameters": {"type": "object"}}]
        with patch.object(llm_providers.requests, "post", side_effect=capture):
            out = _provider().ask("open chrome", timeout=5.0, tools=tools)
        self.assertEqual(out, '{"intent": "open_app"}')  # inert text, not run
        decls = seen["body"]["tools"][0]["functionDeclarations"]
        self.assertEqual(decls[0]["name"], "open_app")


class FakeSettings:
    def __init__(self, llm_provider="gemini", key="", model="gemini-3.5-flash-lite"):
        self.llm_provider = llm_provider
        self.gemini_api_key = key
        self.gemini_model = model
        self.ollama_base_url = "http://localhost:11434"
        self.model = "qwen2.5:3b"
        self.timeout = 30


class TestDispatcher(unittest.TestCase):
    def test_gemini_selected_when_key_present(self) -> None:
        import brain.llm as llm_mod

        fake = FakeSettings("gemini", key="k", model="gemini-3.5-flash-lite")
        with patch.object(llm_mod, "settings", fake):
            llm = LLM()
            self.assertEqual(llm.provider_name, "gemini")

    def test_ollama_fallback_when_no_key(self) -> None:
        import brain.llm as llm_mod

        fake = FakeSettings("gemini", key="")
        with patch.object(llm_mod, "settings", fake):
            llm = LLM()
            self.assertEqual(llm.provider_name, "ollama")

    def test_explicit_ollama_selection(self) -> None:
        import brain.llm as llm_mod

        fake = FakeSettings("ollama", key="k")
        with patch.object(llm_mod, "settings", fake):
            llm = LLM()
            self.assertEqual(llm.provider_name, "ollama")

    def test_ollama_error_compat(self) -> None:
        # Existing callers catch OllamaError from brain.llm.
        self.assertTrue(issubclass(OllamaError, LLMError))

    def test_dispatcher_ask_delegates(self) -> None:
        llm = LLM()
        provider = OllamaProvider.__new__(OllamaProvider)
        provider.ask = lambda prompt, timeout=None, tools=None: "delegated"  # type: ignore[method-assign]
        provider.name = "ollama"
        llm._provider = provider
        self.assertEqual(llm.ask("hi"), "delegated")


if __name__ == "__main__":
    unittest.main()
