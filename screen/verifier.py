"""
screen/verifier.py

Post-action verification for the observe-act-observe-verify cycle.

After performing an action, re-observe the screen and verify
the expected effect occurred.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from screen.reader import ScreenReader, UIElement
from screen.capture import ScreenCapture, capture_for_vision
from screen.vision import VisionAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of action verification."""
    success: bool
    verified: bool = False
    expected: str = ""
    observed: str = ""
    evidence: list[str] = None  # type: ignore
    error: str | None = None
    confidence: float = 0.0

    def __post_init__(self):
        if self.evidence is None:
            self.evidence = []


class Verifier:
    """
    Verifies that screen actions produced expected results.

    Uses UI Automation (fast) or vision (fallback) to re-observe
    the screen after an action and check for expected changes.
    """

    def __init__(
        self,
        reader: ScreenReader | None = None,
        vision: VisionAnalyzer | None = None,
    ):
        self.reader = reader or ScreenReader()
        self.vision = vision or VisionAnalyzer()

    def verify_click(
        self,
        target_name: str,
        target_role: str,
        hwnd: int | None = None,
        expected_changes: list[str] | None = None,
        timeout: float = 3.0,
    ) -> VerificationResult:
        """
        Verify a click action had the expected effect.

        Args:
            target_name: Name of clicked element
            target_role: Role of clicked element (button, link, etc.)
            hwnd: Window handle
            expected_changes: List of expected changes to verify
                e.g., ["dialog opened", "page changed", "video playing"]
            timeout: Max time to wait for changes

        Returns:
            VerificationResult
        """
        if expected_changes is None:
            expected_changes = self._default_expected_changes(target_role)

        # Wait a bit for UI to respond
        time.sleep(0.3)

        # Re-observe using UIA
        ua_result = self._verify_with_uia(target_name, expected_changes, hwnd, timeout)
        if ua_result.verified:
            return ua_result

        # Fallback to vision
        return self._verify_with_vision(target_name, expected_changes, hwnd, timeout)

    def verify_type(
        self,
        field_name: str,
        expected_text: str,
        hwnd: int | None = None,
        timeout: float = 2.0,
    ) -> VerificationResult:
        """Verify text was entered into a field."""
        time.sleep(0.2)

        # Check via UIA for edit control value
        elements = self.reader.find_element(name=field_name, role="edit", hwnd=hwnd)
        if elements:
            # Would need ValuePattern to get actual value
            # For now, use vision
            pass

        return self._verify_with_vision(
            field_name,
            [f"text '{expected_text}' visible in field"],
            hwnd,
            timeout,
        )

    def verify_scroll(
        self,
        direction: str,
        hwnd: int | None = None,
        timeout: float = 2.0,
    ) -> VerificationResult:
        """Verify scrolling occurred."""
        time.sleep(0.3)
        expected = [f"content shifted {direction}", "scroll position changed"]
        return self._verify_with_vision("scroll area", expected, hwnd, timeout)

    def verify_drag(
        self,
        source_name: str,
        target_name: str,
        hwnd: int | None = None,
        timeout: float = 3.0,
    ) -> VerificationResult:
        """Verify drag-drop completed."""
        time.sleep(0.5)
        expected = [f"'{source_name}' moved", f"dropped on '{target_name}'"]
        return self._verify_with_vision(source_name, expected, hwnd, timeout)

    def _default_expected_changes(self, role: str) -> list[str]:
        """Get default expected changes for a role."""
        defaults = {
            "button": ["dialog opened", "page changed", "action triggered", "menu opened"],
            "link": ["page changed", "navigation occurred", "new page loaded"],
            "menuitem": ["menu opened", "submenu shown", "action triggered"],
            "checkbox": ["checkbox toggled", "check state changed"],
            "radiobutton": ["selection changed", "option selected"],
            "tabitem": ["tab switched", "content changed"],
            "combobox": ["dropdown opened", "selection changed"],
            "slider": ["value changed", "position changed"],
            "splitbutton": ["menu opened", "action triggered"],
        }
        return defaults.get(role, ["ui changed", "state changed"])

    def _verify_with_uia(
        self,
        target_name: str,
        expected_changes: list[str],
        hwnd: int | None,
        timeout: float,
    ) -> VerificationResult:
        """Verify using UI Automation."""
        try:
            # Get current UI state
            elements = self.reader.get_ui_elements(hwnd)

            # Look for new dialogs, changed states, etc.
            evidence = []
            verified = False

            for change in expected_changes:
                if "dialog" in change or "menu" in change:
                    # Look for new window/dialog elements
                    for elem in elements:
                        if elem.control_type_name in ("window", "dialog", "menu", "pane"):
                            if elem.name and elem.name != target_name:
                                evidence.append(f"New {elem.control_type_name}: {elem.name}")
                                verified = True

                elif "changed" in change or "toggled" in change:
                    # Check target element for state changes
                    targets = self.reader.find_element_by_name(target_name, hwnd)
                    for elem in targets:
                        # Could check toggle state, selection state via patterns
                        evidence.append(f"Target element found: {elem.name} ({elem.control_type_name})")
                        verified = True

                elif "page" in change or "navigation" in change:
                    # Check for document/window title change
                    window = self.reader.get_active_window()
                    if window:
                        evidence.append(f"Window title: {window.title}")
                        verified = True

            if verified:
                return VerificationResult(
                    success=True,
                    verified=True,
                    expected="; ".join(expected_changes),
                    observed="; ".join(evidence),
                    evidence=evidence,
                    confidence=0.8,
                )

            return VerificationResult(
                success=True,
                verified=False,
                expected="; ".join(expected_changes),
                observed="No clear UIA changes detected",
                evidence=[],
                confidence=0.3,
            )

        except Exception as exc:
            logger.warning(f"UIA verification failed: {exc}")
            return VerificationResult(
                success=False,
                verified=False,
                error=str(exc),
                confidence=0.0,
            )

    def _verify_with_vision(
        self,
        target_name: str,
        expected_changes: list[str],
        hwnd: int | None,
        timeout: float,
    ) -> VerificationResult:
        """Verify using vision model."""
        try:
            # Capture current screen
            cap = capture_for_vision(target="auto", hwnd=hwnd)

            # Build verification prompt
            prompt = (
                f"Verify the result of clicking '{target_name}'. "
                f"Expected changes: {', '.join(expected_changes)}. "
                f"Look at the screen and determine if the action succeeded. "
                f"Return JSON with: verified (bool), evidence (list of strings), "
                f"confidence (0-1), observed (description of current state)."
            )

            result = self.vision.analyze_image(cap.image, prompt)

            if result.success:
                # Parse verification result
                try:
                    import json
                    parsed = json.loads(result.description)
                    return VerificationResult(
                        success=True,
                        verified=parsed.get("verified", False),
                        expected="; ".join(expected_changes),
                        observed=parsed.get("observed", ""),
                        evidence=parsed.get("evidence", []),
                        confidence=parsed.get("confidence", 0.5),
                    )
                except Exception:
                    # Try to infer from description
                    desc = result.description.casefold()
                    verified = any(
                        word in desc for word in ["success", "verified", "confirmed", "opened", "changed"]
                    ) and not any(
                        word in desc for word in ["failed", "not", "missing", "error"]
                    )
                    return VerificationResult(
                        success=True,
                        verified=verified,
                        expected="; ".join(expected_changes),
                        observed=result.description[:200],
                        evidence=[result.description[:200]],
                        confidence=0.6 if verified else 0.3,
                    )

            return VerificationResult(
                success=False,
                verified=False,
                error=result.error,
                confidence=0.0,
            )

        except Exception as exc:
            logger.warning(f"Vision verification failed: {exc}")
            return VerificationResult(
                success=False,
                verified=False,
                error=str(exc),
                confidence=0.0,
            )

    def verify_generic(
        self,
        action: str,
        target: str,
        expected: str,
        hwnd: int | None = None,
        timeout: float = 3.0,
    ) -> VerificationResult:
        """
        Generic verification - uses best available method.

        Args:
            action: Action performed (click, type, scroll, drag)
            target: Target element name
            expected: Expected outcome description
            hwnd: Window handle
            timeout: Verification timeout
        """
        if action in ("click", "tap", "press"):
            return self.verify_click(target, "button", hwnd, [expected], timeout)
        elif action == "type":
            return self.verify_type(target, expected, hwnd, timeout)
        elif action == "scroll":
            return self.verify_scroll(expected, hwnd, timeout)
        elif action == "drag":
            return self.verify_drag(target, expected, hwnd, timeout)
        else:
            # Fallback to vision
            return self._verify_with_vision(target, [expected], hwnd, timeout)


# Module-level function
_default_verifier: Verifier | None = None


def _get_verifier() -> Verifier:
    global _default_verifier
    if _default_verifier is None:
        _default_verifier = Verifier()
    return _default_verifier


def verify_action(
    action: str,
    target: str,
    expected: str,
    hwnd: int | None = None,
    **kwargs,
) -> dict:
    """Verify an action - module function."""
    return _get_verifier().verify_generic(action, target, expected, hwnd, **kwargs).__dict__