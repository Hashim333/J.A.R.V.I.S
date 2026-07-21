"""
automation/ui_detector.py

Visual UI detection layer using OCR and screen capture.

Detects buttons, profile cards, dialog windows, lists, and selection menus
based on what is visible on screen — never assumes fixed pixel positions.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Callable

import pyautogui
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UIElement:
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2

    @property
    def center(self) -> tuple[int, int]:
        return (self.center_x, self.center_y)


def capture_screen(region: tuple[int, int, int, int] | None = None) -> Image.Image:
    """Capture the screen (or a region) and return a PIL Image."""
    if region:
        return pyautogui.screenshot(region=region)
    return pyautogui.screenshot()


def get_screen_text(region: tuple[int, int, int, int] | None = None) -> str:
    """OCR the screen (or region) and return all detected text."""
    img = capture_screen(region)
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    lines: list[str] = []
    current_line = ""
    current_block = -1
    for i, text in enumerate(data["text"]):
        text = text.strip()
        if not text:
            continue
        block = data["block_num"][i]
        if block != current_block:
            if current_line:
                lines.append(current_line.strip())
            current_line = ""
            current_block = block
        current_line += text + " "
    if current_line:
        lines.append(current_line.strip())
    return "\n".join(lines)


def find_text_on_screen(
    search_text: str,
    region: tuple[int, int, int, int] | None = None,
    threshold: float = 0.6,
) -> list[UIElement]:
    """Find all UI elements containing the given text.

    Uses OCR to detect text, then fuzzy-matches against search_text.
    Returns elements sorted by confidence descending.
    """
    img = capture_screen(region)
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    results: list[UIElement] = []

    search_lower = search_text.casefold().strip()

    for i, text in enumerate(data["text"]):
        text = text.strip()
        if not text:
            continue
        conf = int(data["conf"][i]) if data["conf"][i] != "-1" else 0
        if conf < 30:
            continue

        text_lower = text.casefold()
        # Exact substring match
        if search_lower in text_lower or text_lower in search_lower:
            x = data["left"][i]
            y = data["top"][i]
            w = data["width"][i]
            h = data["height"][i]
            confidence = conf / 100.0
            # Boost exact matches
            if search_lower == text_lower:
                confidence = min(1.0, confidence + 0.3)
            elif search_lower in text_lower:
                confidence = min(1.0, confidence + 0.1)
            if confidence >= threshold:
                results.append(UIElement(
                    text=text, x=x, y=y, width=w, height=h, confidence=confidence,
                ))

    # Deduplicate overlapping elements (keep highest confidence)
    deduped: list[UIElement] = []
    results.sort(key=lambda e: -e.confidence)
    for elem in results:
        overlap = False
        for existing in deduped:
            # Check if bounding boxes overlap significantly
            ix = max(elem.x, existing.x)
            iy = max(elem.y, existing.y)
            ix2 = min(elem.x + elem.width, existing.x + existing.width)
            iy2 = min(elem.y + elem.height, existing.y + existing.height)
            if ix < ix2 and iy < iy2:
                overlap = True
                break
        if not overlap:
            deduped.append(elem)

    return sorted(deduped, key=lambda e: -e.confidence)


def find_elements_by_regex(
    pattern: str,
    region: tuple[int, int, int, int] | None = None,
    threshold: float = 0.5,
) -> list[UIElement]:
    """Find UI elements whose text matches a regex pattern."""
    img = capture_screen(region)
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    results: list[UIElement] = []
    compiled = re.compile(pattern, re.IGNORECASE)

    current_block = -1
    block_text = ""
    block_indices: list[int] = []

    for i, text in enumerate(data["text"]):
        text = text.strip()
        block = data["block_num"][i]
        if block != current_block:
            if block_text and block_indices:
                m = compiled.search(block_text)
                if m:
                    # Use first word's position as representative
                    first = block_indices[0]
                    last = block_indices[-1]
                    x = data["left"][first]
                    y = data["top"][first]
                    w = (data["left"][last] + data["width"][last]) - x
                    h = (data["top"][last] + data["height"][last]) - y
                    results.append(UIElement(
                        text=block_text.strip(),
                        x=x, y=y, width=w, height=h,
                        confidence=0.8,
                    ))
            block_text = ""
            block_indices = []
            current_block = block

        if text:
            block_text += text + " "
            block_indices.append(i)

    # Process last block
    if block_text and block_indices:
        m = compiled.search(block_text)
        if m:
            first = block_indices[0]
            last = block_indices[-1]
            x = data["left"][first]
            y = data["top"][first]
            w = (data["left"][last] + data["width"][last]) - x
            h = (data["top"][last] + data["height"][last]) - y
            results.append(UIElement(
                text=block_text.strip(),
                x=x, y=y, width=w, height=h,
                confidence=0.8,
            ))

    return results


def click_element(element: UIElement, duration: float = 0.3) -> bool:
    """Click the center of a UI element."""
    cx, cy = element.center
    logger.info("UI_CLICK location=(%d, %d) text=%r", cx, cy, element.text)
    pyautogui.click(cx, cy, duration=duration)
    logger.info("UI_CLICK result=success")
    return True


def click_text(
    text: str,
    region: tuple[int, int, int, int] | None = None,
) -> bool:
    """Find text on screen and click it. Returns True if found and clicked."""
    elements = find_text_on_screen(text, region=region, threshold=0.6)
    if not elements:
        logger.info("UI_CLICK text=%r result=not_found", text)
        return False
    click_element(elements[0])
    return True


def wait_for_text(
    text: str,
    timeout: float = 5.0,
    interval: float = 0.3,
    region: tuple[int, int, int, int] | None = None,
) -> UIElement | None:
    """Wait for text to appear on screen. Returns the element or None."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        elements = find_text_on_screen(text, region=region, threshold=0.6)
        if elements:
            logger.info("UI_WAIT text=%r result=found", text)
            return elements[0]
        time.sleep(interval)
    logger.info("UI_WAIT text=%r result=timeout(%.1fs)", text, timeout)
    return None


def wait_for_text_to_disappear(
    text: str,
    timeout: float = 5.0,
    interval: float = 0.3,
) -> bool:
    """Wait for text to disappear from screen. Returns True once gone."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        elements = find_text_on_screen(text, threshold=0.6)
        if not elements:
            logger.info("UI_WAIT_GONE text=%r result=gone", text)
            return True
        time.sleep(interval)
    logger.info("UI_WAIT_GONE text=%r result=timeout(%.1fs)", text, timeout)
    return False


def wait_for_any_text(
    texts: list[str],
    timeout: float = 5.0,
    interval: float = 0.3,
    region: tuple[int, int, int, int] | None = None,
) -> tuple[str, UIElement] | None:
    """Wait for any of the given texts to appear. Returns (matched_text, element)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for t in texts:
            elements = find_text_on_screen(t, region=region, threshold=0.6)
            if elements:
                logger.info("UI_WAIT_ANY text=%r result=found", t)
                return (t, elements[0])
        time.sleep(interval)
    logger.info("UI_WAIT_ANY texts=%r result=timeout(%.1fs)", texts, timeout)
    return None


def find_profile_cards(
    region: tuple[int, int, int, int] | None = None,
) -> list[UIElement]:
    """Detect Chrome profile selection cards.

    Chrome's profile picker shows profile names centered in clickable cards.
    We look for text blocks that look like profile names (2-30 chars, title case).
    """
    screen_text = get_screen_text(region)

    # Check if this looks like a Chrome profile picker
    if "choose a profile" not in screen_text.casefold():
        return []

    # Find all text elements in the center area (where profiles appear)
    # Profiles are typically 3-20 characters, on separate lines
    profiles: list[UIElement] = []
    seen_texts: set[str] = set()

    img = capture_screen(region)
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    for i, text in enumerate(data["text"]):
        text = text.strip()
        if not text:
            continue
        conf = int(data["conf"][i]) if data["conf"][i] != "-1" else 0
        if conf < 40:
            continue

        text_lower = text.casefold()
        # Filter out non-profile text
        if len(text) < 2 or len(text) > 30:
            continue
        if text_lower in ("choose a profile", "sign in", "guest", "close",
                          "add profile", "manage profiles", "settings",
                          "people", "other profiles", "profile"):
            continue

        if text_lower not in seen_texts:
            seen_texts.add(text_lower)
            x = data["left"][i]
            y = data["top"][i]
            w = data["width"][i]
            h = data["height"][i]
            profiles.append(UIElement(
                text=text, x=x, y=y, width=w, height=h, confidence=conf / 100.0,
            ))

    # Expand each profile's bbox to cover the likely clickable card area
    expanded: list[UIElement] = []
    for p in profiles:
        card_x = max(0, p.x - 20)
        card_y = max(0, p.y - 10)
        card_w = p.width + 40
        card_h = p.height + 40
        expanded.append(UIElement(
            text=p.text, x=card_x, y=card_y,
            width=card_w, height=card_h,
            confidence=p.confidence,
        ))

    logger.info("UI_PROFILES count=%d names=%s", len(expanded),
                [p.text for p in expanded])
    return expanded


def find_launcher_dialog(
    dialog_texts: list[str] | None = None,
    region: tuple[int, int, int, int] | None = None,
) -> list[UIElement]:
    """Detect a launcher/dialog window by looking for known text patterns.

    Returns dialog elements found. If dialog_texts is provided, waits for
    any of those texts to appear and returns them.
    """
    if dialog_texts:
        result = wait_for_any_text(dialog_texts, timeout=3.0, region=region)
        if result:
            return [result[1]]
    return []


def detect_window_by_title(title_substring: str) -> dict | None:
    """Find a window whose title contains the given substring."""
    import pygetwindow as gw
    try:
        windows = gw.getWindowsWithTitle(title_substring)
        for win in windows:
            if title_substring.casefold() in win.title.casefold():
                return {
                    "title": win.title,
                    "left": win.left, "top": win.top,
                    "width": win.width, "height": win.height,
                    "hwnd": win._hWnd,
                }
    except Exception:
        pass
    return None


def get_active_window_region() -> tuple[int, int, int, int] | None:
    """Get the bounding box of the active window, or None."""
    import pygetwindow as gw
    try:
        active = gw.getActiveWindow()
        if active and active.width > 0 and active.height > 0:
            return (active.left, active.top, active.width, active.height)
    except Exception:
        pass
    return None
