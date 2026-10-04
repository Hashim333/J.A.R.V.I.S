"""
screen/vision.py

Vision model integration for visual understanding fallback.
Uses existing JARVIS multimodal provider (Gemini) for image analysis.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from dataclasses import dataclass
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class VisionResult:
    """Result from vision analysis."""
    description: str = ""
    elements: list[dict] = None  # type: ignore
    text: str = ""
    success: bool = False
    error: str | None = None

    def __post_init__(self):
        if self.elements is None:
            self.elements = []


class VisionAnalyzer:
    """
    Vision analyzer using JARVIS's existing multimodal provider.

    Prefers the already-configured provider (Gemini) rather than
    adding a separate AI stack.
    """

    def __init__(self, provider_name: str | None = None):
        self.provider_name = provider_name or "gemini"
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        """Initialize the vision-capable provider."""
        try:
            from brain.llm import LLM
            self._llm = LLM()
            logger.info(f"VisionAnalyzer ready (will use {self.provider_name})")
        except Exception as exc:
            logger.warning(f"VisionAnalyzer init: {exc}")
            self._llm = None

    def analyze_image(
        self,
        image: Image.Image,
        prompt: str = "Describe all UI elements, buttons, text, and interactive controls on this screen.",
        max_tokens: int = 1024,
    ) -> VisionResult:
        """
        Analyze an image using the vision-capable LLM.

        Args:
            image: PIL Image to analyze
            prompt: Custom prompt for analysis
            max_tokens: Max response tokens

        Returns:
            VisionResult with description and structured elements
        """
        try:
            # Convert image to base64
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

            # Use brain's LLM class which handles provider selection
            if not self._llm:
                return VisionResult(success=False, error="LLM not initialized")

            provider = self._llm._ensure_provider()

            # Check if provider supports vision
            if not hasattr(provider, 'analyze_image'):
                return self._analyze_with_chat(provider, b64, prompt, max_tokens)

            result = provider.analyze_image(b64, prompt, max_tokens)
            return VisionResult(
                success=True,
                description=result.get("description", ""),
                elements=result.get("elements", []),
                text=result.get("text", ""),
            )

        except Exception as exc:
            logger.exception("Vision analysis failed")
            return VisionResult(success=False, error=str(exc))

    def _analyze_with_chat(
        self,
        provider,
        b64: str,
        prompt: str,
        max_tokens: int,
    ) -> VisionResult:
        """Fallback using chat completion with image."""
        try:
            # Try to use provider's chat method with image
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }
            ]
            # This depends on provider implementation
            response = provider.chat(messages, max_tokens=max_tokens)
            return VisionResult(
                success=True,
                description=response,
                elements=[],
            )
        except Exception as exc:
            logger.warning(f"Vision chat fallback failed: {exc}")
            return VisionResult(success=False, error=str(exc))

    def find_element_visual(
        self,
        query: str,
        capture,
        prompt: str | None = None,
    ) -> list[dict]:
        """
        Find a specific element visually.

        Returns list of dicts with bounds, name, role, confidence.
        """
        if prompt is None:
            prompt = (
                f"Find the UI element matching: '{query}'. "
                f"Return JSON with list of elements, each having: "
                f"x, y, width, height (bounding box), name, role, confidence (0-1). "
                f"Only return elements that match the query."
            )

        result = self.analyze_image(capture.image, prompt)

        if not result.success:
            return []

        elements = result.elements
        if not elements and result.description:
            # Try to parse from description
            elements = self._parse_elements_from_text(result.description, query)

        # Filter and validate
        filtered = []
        for elem in elements:
            if self._validate_element(elem):
                filtered.append(elem)

        return filtered

    def _validate_element(self, elem: dict) -> bool:
        """Validate element has required fields."""
        required = ["x", "y", "width", "height"]
        return all(k in elem for k in required)

    def _parse_elements_from_text(self, text: str, query: str) -> list[dict]:
        """Attempt to extract element info from description text."""
        elements = []
        query_lower = query.casefold()

        # Simple heuristic: look for coordinate-like patterns
        import re
        coord_pattern = r"(\d+)\s*[,x]\s*(\d+)"
        for match in re.finditer(coord_pattern, text):
            try:
                x, y = int(match.group(1)), int(match.group(2))
                elements.append({
                    "x": x, "y": y, "width": 50, "height": 30,
                    "name": query, "role": "unknown", "confidence": 0.3,
                })
            except Exception:
                pass

        return elements

    def read_screen_text(self, image: Image.Image) -> VisionResult:
        """Read all visible text from screen (OCR via vision)."""
        prompt = (
            "Read all visible text on this screen. "
            "Return the text content in reading order. "
            "Focus on buttons, headings, menu items, and form labels."
        )
        return self.analyze_image(image, prompt)

    def describe_screen(self, image: Image.Image) -> VisionResult:
        """Get a structured description of the screen."""
        prompt = (
            "Describe this screen in detail. Identify: "
            "1. Application/window title "
            "2. Main UI areas (toolbar, sidebar, content, status bar) "
            "3. All visible buttons with their labels "
            "4. Input fields and their labels "
            "5. Current focus/selection "
            "6. Any dialogs, alerts, or notifications "
            "Return as structured description."
        )
        return self.analyze_image(image, prompt)


# Module-level function
_default_vision: VisionAnalyzer | None = None


def _get_vision() -> VisionAnalyzer:
    global _default_vision
    if _default_vision is None:
        _default_vision = VisionAnalyzer()
    return _default_vision


def find_element_visual(query: str, capture) -> list[dict]:
    """Find element visually - module-level function."""
    return _get_vision().find_element_visual(query, capture)