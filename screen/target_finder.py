"""
screen/target_finder.py

Natural language -> UI element mapping.

Priority:
1. Exact UI Automation element name match
2. Semantic role/name match
3. Visible text match (from UIA)
4. Currently focused element
5. Visual detection from screenshot (fallback)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from screen.reader import ScreenReader, UIElement, get_active_window_info
from screen.capture import capture_for_vision, ScreenCapture
from screen.vision import find_element_visual, VisionAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class Target:
    """A located UI target ready for interaction."""
    element: UIElement | None = None
    bounds: tuple[int, int, int, int] | None = None  # x, y, w, h
    center: tuple[int, int] | None = None
    name: str = ""
    role: str = ""
    confidence: float = 0.0
    method: str = "uia"  # "uia", "vision", "focused"
    source_capture: ScreenCapture | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "element": self.element.to_dict() if self.element else None,
            "bounds": self.bounds,
            "center": self.center,
            "name": self.name,
            "role": self.role,
            "confidence": self.confidence,
            "method": self.method,
        }

    @property
    def is_valid(self) -> bool:
        return self.element is not None or (self.bounds is not None and self.center is not None)


class TargetFinder:
    """
    Finds UI targets from natural language queries.

    Uses UI Automation first (fast, precise), falls back to vision
    when UIA cannot locate the target.
    """

    def __init__(self, reader: ScreenReader | None = None, vision: VisionAnalyzer | None = None):
        self.reader = reader or ScreenReader()
        self.vision = vision or VisionAnalyzer()

    def find(self, query: str, hwnd: int | None = None) -> list[Target]:
        """
        Find targets matching the query.

        Args:
            query: Natural language query (e.g., "Settings button", "search box", "first result")
            hwnd: Window handle (optional, uses active window if None)

        Returns:
            List of Target objects sorted by confidence.
        """
        if hwnd is None:
            window_info = get_active_window_info()
            if not window_info.get("success"):
                return []
            hwnd = window_info["hwnd"]

        targets = []

        # Strategy 1: Check if query is a pure role (button, link, field, etc.)
        # If so, search directly by role first
        pure_role = self._extract_pure_role(query)
        if pure_role:
            role_elements = self.reader.find_element_by_role(pure_role, hwnd)
            if not role_elements:
                # Try case-insensitive
                all_elements = self.reader.get_ui_elements(hwnd)
                role_elements = [e for e in all_elements if pure_role.casefold() in e.control_type_name.casefold()]
            for elem in role_elements:
                if elem.name:
                    targets.append(Target(
                        element=elem,
                        bounds=elem.bounds,
                        center=elem.center,
                        name=elem.name,
                        role=elem.control_type_name,
                        confidence=0.9,
                        method="uia_role",
                    ))
            if targets:
                return targets  # Pure role query - return role matches directly

        # Strategy 2: Exact name match in UIA
        uia_targets = self._find_by_uia_name(query, hwnd)
        targets.extend(uia_targets)

        # Strategy 3: Role + name semantic match
        if not targets:
            role_targets = self._find_by_uia_role_and_name(query, hwnd)
            targets.extend(role_targets)

        # Strategy 3: Focused element if query is vague
        if not targets and self._is_vague_query(query):
            focused = self.reader.get_focused_element(hwnd)
            if focused:
                targets.append(Target(
                    element=focused,
                    bounds=focused.bounds,
                    center=focused.center,
                    name=focused.name or "focused element",
                    role=focused.control_type_name,
                    confidence=0.7,
                    method="focused",
                ))

        # Strategy 4: Vision fallback (screenshot + visual understanding)
        if not targets:
            vision_targets = self._find_by_vision(query, hwnd)
            targets.extend(vision_targets)

        # Sort by confidence
        targets.sort(key=lambda t: t.confidence, reverse=True)
        return targets

    def find_one(self, query: str, hwnd: int | None = None) -> Target | None:
        """Find the best single target."""
        targets = self.find(query, hwnd)
        return targets[0] if targets else None

    def _find_by_uia_name(self, query: str, hwnd: int) -> list[Target]:
        """Find by exact or partial name match in UI Automation."""
        elements = self.reader.find_element_by_name(query, hwnd, exact=False)
        targets = []

        # Normalize query for matching
        query_norm = query.casefold().strip()
        query_words = query_norm.split()

        for elem in elements:
            name_norm = elem.name.casefold().strip()
            if not name_norm:
                continue

            # Score the match
            score = 0.0
            if query_norm == name_norm:
                score = 1.0  # Exact match
            elif query_norm in name_norm:
                score = 0.8  # Contains
            elif name_norm in query_norm:
                score = 0.7  # Name contained in query
            elif any(word in name_norm for word in query_words if len(word) > 2):
                score = 0.5  # Partial word match
            else:
                continue

            targets.append(Target(
                element=elem,
                bounds=elem.bounds,
                center=elem.center,
                name=elem.name,
                role=elem.control_type_name,
                confidence=score,
                method="uia",
            ))

        return targets

    def _find_by_uia_role_and_name(self, query: str, hwnd: int) -> list[Target]:
        """Find by role + name semantic matching."""
        query_norm = query.casefold()

        # Extract potential role from query
        role_keywords = {
            "button": ["button", "btn", "click"],
            "edit": ["input", "field", "box", "textbox", "search"],
            "combobox": ["dropdown", "combo", "select"],
            "checkbox": ["checkbox", "check"],
            "radiobutton": ["radio", "option"],
            "hyperlink": ["link", "hyperlink"],
            "menuitem": ["menu", "item"],
            "listitem": ["item", "result"],
            "tabitem": ["tab"],
            "slider": ["slider", "scrollbar"],
        }

        detected_role = None
        for role, keywords in role_keywords.items():
            if any(kw in query_norm for kw in keywords):
                detected_role = role
                break

        # Find elements with that role
        if detected_role:
            elements = self.reader.find_element_by_role(detected_role, hwnd)
        else:
            elements = self.reader.get_ui_elements(hwnd)

        # If no elements found with role, try case-insensitive search
        if not elements and detected_role:
            all_elements = self.reader.get_ui_elements(hwnd)
            elements = [e for e in all_elements if detected_role.casefold() in e.control_type_name.casefold()]

        # Also look for name matches within those elements
        targets = []
        for elem in elements:
            name_norm = elem.name.casefold().strip()
            if not name_norm:
                continue

            # Remove role words from query to get target name
            target_name = query_norm
            for role, keywords in role_keywords.items():
                for kw in keywords:
                    target_name = target_name.replace(kw, "").strip()

            target_name = target_name.strip()
            if not target_name:
                target_name = query_norm

            score = 0.0
            if target_name in name_norm:
                score = 0.8
            elif any(w in name_norm for w in target_name.split() if len(w) > 2):
                score = 0.5

            if score > 0:
                targets.append(Target(
                    element=elem,
                    bounds=elem.bounds,
                    center=elem.center,
                    name=elem.name,
                    role=elem.control_type_name,
                    confidence=score,
                    method="uia_semantic",
                ))

        return targets

    def _extract_pure_role(self, query: str) -> str | None:
        """Extract a pure role from query (e.g., 'button' from 'button' or 'click button')."""
        query_norm = query.casefold().strip()
        role_keywords = {
            "button": ["button", "btn"],
            "edit": ["input", "field", "textbox", "edit"],
            "combobox": ["dropdown", "combo", "select"],
            "checkbox": ["checkbox", "check"],
            "radiobutton": ["radio", "option"],
            "hyperlink": ["link", "hyperlink"],
            "menuitem": ["menuitem", "menu"],
            "listitem": ["item", "result"],
            "tabitem": ["tab"],
            "slider": ["slider", "scrollbar"],
            "text": ["text", "label"],
        }
        # Check if query is just a role word or "click <role>" etc.
        words = query_norm.split()
        if len(words) == 1 and words[0] in role_keywords:
            return words[0]
        if len(words) == 2 and words[0] in ("click", "tap", "press", "double click", "right click") and words[1] in role_keywords:
            return words[1]
        return None

    def _is_vague_query(self, query: str) -> bool:
        """Check if query is vague (click, tap, press without specific target)."""
        vague_patterns = [
            r"^(click|tap|press)\s*$",
            r"^(click|tap|press)\s+(it|that|this|there)\s*$",
        ]
        return any(re.match(p, query.casefold().strip()) for p in vague_patterns)

    def _find_by_vision(self, query: str, hwnd: int | None) -> list[Target]:
        """Vision fallback - screenshot and use vision model."""
        try:
            # Capture the relevant area
            cap = capture_for_vision(target="auto", hwnd=hwnd)

            # Use vision to find element
            vision_results = find_element_visual(query, cap)

            targets = []
            for result in vision_results:
                bounds = result.get("bounds") or result.get("region")
                if bounds:
                    x, y, w, h = bounds
                    targets.append(Target(
                        element=None,
                        bounds=(x, y, w, h),
                        center=(x + w // 2, y + h // 2),
                        name=result.get("name", query),
                        role=result.get("role", "unknown"),
                        confidence=result.get("confidence", 0.5),
                        method="vision",
                        source_capture=cap,
                    ))
            return targets
        except Exception as exc:
            logger.warning(f"Vision fallback failed: {exc}")
            return []


# Module-level function for simple usage
_default_finder: TargetFinder | None = None


def _get_finder() -> TargetFinder:
    global _default_finder
    if _default_finder is None:
        _default_finder = TargetFinder()
    return _default_finder


def find_target(query: str, hwnd: int | None = None) -> list[dict]:
    """Find targets matching query. Returns list of target dicts."""
    finder = _get_finder()
    targets = finder.find(query, hwnd)
    return [t.to_dict() for t in targets]


def find_target_one(query: str, hwnd: int | None = None) -> dict | None:
    """Find single best target."""
    finder = _get_finder()
    target = finder.find_one(query, hwnd)
    return target.to_dict() if target else None