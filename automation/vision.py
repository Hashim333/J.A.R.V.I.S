"""
automation/vision.py

Screen understanding, OCR, UI element detection, click/interaction,
PDF reading, and form filling.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mss
import numpy as np
import pyautogui
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)

# Locate Tesseract on common Windows paths
_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]
for _tess_path in _TESSERACT_PATHS:
    if os.path.isfile(_tess_path):
        pytesseract.pytesseract.tesseract_cmd = _tess_path
        break

# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class TextRegion:
    text: str
    x: int
    y: int
    w: int
    h: int
    confidence: float = 0.0

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    @property
    def area(self) -> int:
        return self.w * self.h


@dataclass
class ScreenCapture:
    image: Image.Image
    monitor: dict[str, int]
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Screen capture
# ---------------------------------------------------------------------------

def capture_screen(monitor_index: int = 1) -> ScreenCapture:
    """Capture the specified monitor using ``mss``."""
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return ScreenCapture(image=img, monitor=monitor)


def _to_pil(image: Any) -> Image.Image:
    if isinstance(image, ScreenCapture):
        return image.image
    if isinstance(image, Image.Image):
        return image
    if isinstance(image, str):
        return Image.open(image)
    if isinstance(image, np.ndarray):
        return Image.fromarray(image)
    raise TypeError(f"Cannot convert {type(image).__name__} to PIL Image")


# ---------------------------------------------------------------------------
# OCR helpers
# ---------------------------------------------------------------------------

def _ocr_data(
    image: Image.Image,
    lang: str = "eng",
    psm: int = 3,
) -> list[TextRegion]:
    """Run Tesseract OCR and return structured ``TextRegion`` list."""
    data = pytesseract.image_to_data(
        image, lang=lang, output_type=pytesseract.Output.DICT,
        config=f"--psm {psm}",
    )
    regions: list[TextRegion] = []
    for i in range(len(data["text"])):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = 0.0
        regions.append(TextRegion(
            text=text,
            x=data["left"][i],
            y=data["top"][i],
            w=data["width"][i],
            h=data["height"][i],
            confidence=conf / 100.0,
        ))
    return regions


def _ocr_text(image: Image.Image, lang: str = "eng", psm: int = 3) -> str:
    return pytesseract.image_to_string(image, lang=lang, config=f"--psm {psm}")


# ---------------------------------------------------------------------------
# Public API – screen reading
# ---------------------------------------------------------------------------

def read_screen_text(
    monitor_index: int = 1,
    lang: str = "eng",
) -> dict[str, Any]:
    """Read all visible text from the screen.

    Returns
    -------
    dict with keys: ``success``, ``text`` (full OCR output),
    ``regions`` (list of ``TextRegion`` dicts), ``word_count``.
    """
    try:
        sc = capture_screen(monitor_index)
        raw_text = _ocr_text(sc.image, lang=lang)
        regions = _ocr_data(sc.image, lang=lang)
        return {
            "success": True,
            "text": raw_text.strip(),
            "regions": [r.__dict__ for r in regions],
            "word_count": len(raw_text.split()),
        }
    except Exception as exc:
        logger.exception("read_screen_text failed")
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Element location
# ---------------------------------------------------------------------------

def find_text_on_screen(
    text: str,
    monitor_index: int = 1,
    lang: str = "eng",
    case_sensitive: bool = False,
) -> dict[str, Any]:
    """Find *text* on screen via OCR and return its location.

    Returns dict with ``success``, ``x``, ``y`` (centre), ``region``
    (bounding box), and ``matches`` (all matching regions).
    """
    try:
        sc = capture_screen(monitor_index)
        regions = _ocr_data(sc.image, lang=lang)
        target = text if case_sensitive else text.casefold()

        matches: list[dict] = []
        for r in regions:
            candidate = r.text if case_sensitive else r.text.casefold()
            if target in candidate:
                matches.append(r.__dict__)

        if not matches:
            return {
                "success": False,
                "error": f"Could not find {text!r} on screen",
                "matches": [],
            }

        best = max(matches, key=lambda m: m["confidence"] * m["area"])
        return {
            "success": True,
            "x": best["x"] + best["w"] // 2,
            "y": best["y"] + best["h"] // 2,
            "region": best,
            "matches": matches,
        }
    except Exception as exc:
        logger.exception("find_text_on_screen failed")
        return {"success": False, "error": str(exc), "matches": []}


def find_all_text_on_screen(
    monitor_index: int = 1,
    lang: str = "eng",
) -> dict[str, Any]:
    """Return every text region found on screen."""
    try:
        sc = capture_screen(monitor_index)
        regions = _ocr_data(sc.image, lang=lang)
        return {
            "success": True,
            "count": len(regions),
            "regions": [r.__dict__ for r in regions],
        }
    except Exception as exc:
        logger.exception("find_all_text_on_screen failed")
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Click / interact
# ---------------------------------------------------------------------------

def click_text(
    text: str,
    monitor_index: int = 1,
    lang: str = "eng",
    case_sensitive: bool = False,
    button: str = "left",
) -> dict[str, Any]:
    """Find *text* on screen and click it.

    Returns dict with ``success``, ``x``, ``y`` of the click, and the
    underlying ``find_result``.
    """
    find_result = find_text_on_screen(text, monitor_index, lang, case_sensitive)
    if not find_result["success"]:
        return {"success": False, "error": find_result["error"], "find_result": find_result}

    x, y = find_result["x"], find_result["y"]
    try:
        pyautogui.click(x, y, button=button)
        return {"success": True, "x": x, "y": y, "find_result": find_result}
    except Exception as exc:
        logger.exception("click_text failed")
        return {"success": False, "error": str(exc), "find_result": find_result}


def click_coordinates(x: int, y: int, button: str = "left") -> dict[str, Any]:
    """Click at pixel coordinates."""
    try:
        pyautogui.click(x, y, button=button)
        return {"success": True, "x": x, "y": y}
    except Exception as exc:
        logger.exception("click_coordinates failed")
        return {"success": False, "error": str(exc)}


def double_click_text(
    text: str,
    monitor_index: int = 1,
    lang: str = "eng",
) -> dict[str, Any]:
    """Double-click text on screen."""
    find_result = find_text_on_screen(text, monitor_index, lang)
    if not find_result["success"]:
        return {"success": False, "error": find_result["error"]}
    try:
        pyautogui.doubleClick(find_result["x"], find_result["y"])
        return {"success": True, "x": find_result["x"], "y": find_result["y"]}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def right_click_text(
    text: str,
    monitor_index: int = 1,
    lang: str = "eng",
) -> dict[str, Any]:
    """Right-click text on screen."""
    return click_text(text, monitor_index, lang, button="right")


def move_to_text(
    text: str,
    monitor_index: int = 1,
    lang: str = "eng",
) -> dict[str, Any]:
    """Move mouse to the centre of *text* without clicking."""
    find_result = find_text_on_screen(text, monitor_index, lang)
    if not find_result["success"]:
        return {"success": False, "error": find_result["error"]}
    try:
        pyautogui.moveTo(find_result["x"], find_result["y"])
        return {"success": True, "x": find_result["x"], "y": find_result["y"]}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Form filling
# ---------------------------------------------------------------------------

def fill_form_field(
    field_label: str,
    value: str,
    monitor_index: int = 1,
    lang: str = "eng",
) -> dict[str, Any]:
    """Find a form field labelled *field_label*, click it, and type *value*.

    Heuristic: after locating the label we offset a few pixels to the right
    (or below) to reach the input area. Falls back to adding an offset.
    """
    find_result = find_text_on_screen(field_label, monitor_index, lang)
    if not find_result["success"]:
        return {"success": False, "error": find_result["error"]}

    try:
        region = find_result["region"]
        input_x = region["x"] + region["w"] + 8
        input_y = region["y"] + region["h"] // 2
        pyautogui.click(input_x, input_y)
        time.sleep(0.15)
        pyautogui.write(value, interval=0.02)
        return {"success": True, "field": field_label, "value": value}
    except Exception as exc:
        logger.exception("fill_form_field failed")
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# PDF reading
# ---------------------------------------------------------------------------

def read_pdf(filepath: str, lang: str = "eng") -> dict[str, Any]:
    """Extract text from a PDF.

    For text-based PDFs uses PyMuPDF directly; for scanned/image-only PDFs
    renders each page and runs OCR.
    """
    filepath = str(Path(filepath).resolve())
    if not os.path.isfile(filepath):
        return {"success": False, "error": f"File not found: {filepath}"}

    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {"success": False, "error": "PyMuPDF (fitz) is not installed"}

    try:
        doc = fitz.open(filepath)
        pages_text: list[str] = []
        total_chars = 0

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text().strip()

            if len(text) > 50:
                pages_text.append(f"--- Page {page_num + 1} ---\n{text}")
                total_chars += len(text)
            else:
                pix = page.get_pixmap(dpi=200)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                ocr_text = _ocr_text(img, lang=lang).strip()
                if ocr_text:
                    pages_text.append(f"--- Page {page_num + 1} (OCR) ---\n{ocr_text}")
                    total_chars += len(ocr_text)

        page_count = len(doc)
        doc.close()
        full_text = "\n\n".join(pages_text)
        return {
            "success": True,
            "text": full_text,
            "page_count": page_count,
            "total_chars": total_chars,
        }
    except Exception as exc:
        logger.exception("read_pdf failed")
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Image OCR
# ---------------------------------------------------------------------------

def ocr_image(filepath: str, lang: str = "eng") -> dict[str, Any]:
    """Read text from an image file."""
    filepath = str(Path(filepath).resolve())
    if not os.path.isfile(filepath):
        return {"success": False, "error": f"File not found: {filepath}"}

    try:
        img = Image.open(filepath)
        text = _ocr_text(img, lang=lang)
        regions = _ocr_data(img, lang=lang)
        return {
            "success": True,
            "text": text.strip(),
            "regions": [r.__dict__ for r in regions],
            "word_count": len(text.split()),
        }
    except Exception as exc:
        logger.exception("ocr_image failed")
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Error / dialog reading
# ---------------------------------------------------------------------------

def read_error_dialog(monitor_index: int = 1, lang: str = "eng") -> dict[str, Any]:
    """Read potential error dialog content from the screen.

    Strategy: capture the centre region of the screen (where dialogs
    normally appear) and OCR it. Also checks for common error keywords.
    """
    try:
        sc = capture_screen(monitor_index)
        w, h = sc.image.size
        cx, cy = w // 2, h // 2

        dialog_region = sc.image.crop((
            max(0, cx - 300),
            max(0, cy - 200),
            min(w, cx + 300),
            min(h, cy + 200),
        ))

        text = _ocr_text(dialog_region, lang=lang)
        has_error_keywords = any(
            kw in text.casefold()
            for kw in ("error", "warning", "failed", "exception",
                       "denied", "access", "permission",
                       "try again", "cancel", "retry")
        )
        return {
            "success": True,
            "text": text.strip(),
            "has_error_keywords": has_error_keywords,
        }
    except Exception as exc:
        logger.exception("read_error_dialog failed")
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Screen description
# ---------------------------------------------------------------------------

def describe_screen(monitor_index: int = 1, lang: str = "eng") -> dict[str, Any]:
    """Provide a structured description of what is on the screen.

    Uses OCR to find all text and groups it by vertical position to
    identify probable headers, body text, buttons, and dialogs.
    """
    try:
        sc = capture_screen(monitor_index)
        w, h = sc.image.size
        regions = _ocr_data(sc.image, lang=lang)

        lines = []
        top_region, body_region, bottom_region = [], [], []
        for r in regions:
            if r.y < h * 0.25:
                top_region.append(r)
            elif r.y > h * 0.75:
                bottom_region.append(r)
            else:
                body_region.append(r)

        parts = []
        if top_region:
            top_text = " ".join(r.text for r in top_region)
            parts.append(f"Top: {top_text[:200]}")
        if body_region:
            body_text = " ".join(r.text for r in body_region)
            parts.append(f"Centre: {body_text[:500]}")
        if bottom_region:
            bottom_text = " ".join(r.text for r in bottom_region)
            parts.append(f"Bottom: {bottom_text[:200]}")

        return {
            "success": True,
            "description": " | ".join(parts),
            "resolution": f"{w}x{h}",
            "text_regions_found": len(regions),
        }
    except Exception as exc:
        logger.exception("describe_screen failed")
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# UI element detection (OpenCV-based)
# ---------------------------------------------------------------------------

def detect_buttons(monitor_index: int = 1) -> dict[str, Any]:
    """Detect probable button-like rectangles on screen using OpenCV.

    Returns bounding boxes of rectangular contours that could be buttons.
    """
    try:
        import cv2

        sc = capture_screen(monitor_index)
        img = np.array(sc.image.convert("L"))
        _, thresh = cv2.threshold(img, 200, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)

        buttons: list[dict[str, int]] = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            if 200 < area < 50000 and 1.5 < w / h < 10:
                buttons.append({"x": x, "y": y, "w": w, "h": h,
                                "cx": x + w // 2, "cy": y + h // 2})

        return {"success": True, "count": len(buttons), "buttons": buttons}
    except ImportError:
        return {"success": False, "error": "OpenCV (cv2) is not installed"}
    except Exception as exc:
        logger.exception("detect_buttons failed")
        return {"success": False, "error": str(exc)}


def detect_text_fields(monitor_index: int = 1) -> dict[str, Any]:
    """Detect probable text input fields using OpenCV.

    Looks for rectangular regions that are white/light-filled (common
    for input boxes).
    """
    try:
        import cv2

        sc = capture_screen(monitor_index)
        img = np.array(sc.image.convert("L"))
        _, thresh = cv2.threshold(img, 220, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)

        fields: list[dict[str, int]] = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            if 300 < area < 80000 and 2 < w / h < 20:
                fields.append({"x": x, "y": y, "w": w, "h": h,
                               "cx": x + w // 2, "cy": y + h // 2})

        return {"success": True, "count": len(fields), "fields": fields}
    except ImportError:
        return {"success": False, "error": "OpenCV (cv2) is not installed"}
    except Exception as exc:
        logger.exception("detect_text_fields failed")
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# OpenAI Vision integration (optional)
# ---------------------------------------------------------------------------

def describe_screen_with_ai(monitor_index: int = 1) -> dict[str, Any]:
    """Use OpenAI GPT-4o Vision to describe the screen contents.

    Requires ``OPENAI_API_KEY`` to be set.
    """
    try:
        import base64
        import io

        from openai import OpenAI

        sc = capture_screen(monitor_index)
        buf = io.BytesIO()
        sc.image.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Describe everything visible on this screen "
                                    "in detail. List all UI elements, text, "
                                    "buttons, and dialogs.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
            max_tokens=1024,
        )
        description = response.choices[0].message.content or ""
        return {
            "success": True,
            "description": description,
            "model": "gpt-4o",
        }
    except Exception as exc:
        logger.exception("describe_screen_with_ai failed")
        return {"success": False, "error": str(exc)}
