"""
brain/llm.py

Responsible solely for sending prompts to a local Ollama server
and returning the generated text response.
"""

import requests

from config.settings import settings


class OllamaError(Exception):
    """Raised when the Ollama server returns an error or is unreachable."""


class LLM:
    """
    Thin client for a locally running Ollama inference server.

    Single responsibility: send a prompt, return generated text.
    No memory, no parsing, no side effects.
    """

    def __init__(self) -> None:
        self._endpoint = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
        self._model = settings.model
        self._timeout = settings.timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ask(self, prompt: str) -> str:
        """
        Send *prompt* to Ollama and return the full generated text.

        Args:
            prompt: The raw prompt string to send to the model.

        Returns:
            The model's complete text response as a single string.

        Raises:
            ValueError: If *prompt* is empty.
            OllamaError: If the server is unreachable or returns an error.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")

        payload = self._build_payload(prompt)
        raw = self._post(payload)
        return self._extract_text(raw)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_payload(self, prompt: str) -> dict:
        """Construct the JSON body for the /api/generate endpoint."""
        return {
            "model": self._model,
            "prompt": prompt,
            "stream": False,  # receive a single JSON response, not SSE chunks
        }

    def _post(self, payload: dict) -> dict:
        """
        POST *payload* to the Ollama endpoint.

        Returns:
            Parsed JSON response dict.

        Raises:
            OllamaError: On network failure, timeout, or non-200 status.
        """
        try:
            response = requests.post(
                self._endpoint,
                json=payload,
                timeout=self._timeout,
            )
        except requests.exceptions.ConnectionError as exc:
            raise OllamaError(
                f"Cannot reach Ollama at '{self._endpoint}'. "
                "Ensure the server is running (`ollama serve`)."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise OllamaError(
                f"Ollama request timed out after {self._timeout}s."
            ) from exc

        if response.status_code != 200:
            raise OllamaError(
                f"Ollama returned HTTP {response.status_code}: {response.text[:200]}"
            )

        return response.json()

    @staticmethod
    def _extract_text(data: dict) -> str:
        """
        Pull the generated text out of Ollama's response envelope.

        Raises:
            OllamaError: If the expected 'response' key is absent.
        """
        try:
            return data["response"]
        except KeyError as exc:
            raise OllamaError(
                f"Unexpected Ollama response shape. Keys present: {list(data.keys())}"
            ) from exc