"""
screen/capture.py

Efficient screen capture for vision fallback.
Captures only what's needed - region, window, or monitor.
Supports multi-monitor, DPI scaling, and downscaled capture for fast analysis.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import mss
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class ScreenCapture:
    """Screen capture with metadata."""
    image: Image.Image
    monitor: dict[str, int]  # left, top, width, height
    timestamp: float = field(default_factory=time.time)
    source: str = "monitor"  # "monitor", "window", "region"
    dpi_scale: float = 1.0

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    def to_bytes(self, format: str = "PNG", quality: int = 85) -> bytes:
        """Convert to bytes for vision model."""
        import io
        buf = io.BytesIO()
        if format == "JPEG":
            self.image.save(buf, format=format, quality=quality)
        else:
            self.image.save(buf, format=format)
        return buf.getvalue()

    def crop(self, left: int, top: int, right: int, bottom: int) -> "ScreenCapture":
        """Crop to region (relative to this capture)."""
        cropped = self.image.crop((left, top, right, bottom))
        return ScreenCapture(
            image=cropped,
            monitor={
                "left": self.monitor["left"] + left,
                "top": self.monitor["top"] + top,
                "width": right - left,
                "height": bottom - top,
            },
            timestamp=time.time(),
            source=self.source,
            dpi_scale=self.dpi_scale,
        )


def get_monitor_info() -> list[dict]:
    """Get info for all monitors."""
    with mss.mss() as sct:
        monitors = []
        for i, m in enumerate(sct.monitors[1:], 1):  # Skip index 0 (all monitors combined)
            monitors.append({
                "index": i,
                "left": m["left"],
                "top": m["top"],
                "width": m["width"],
                "height": m["height"],
            })
        return monitors


def get_primary_monitor() -> dict:
    """Get primary monitor info."""
    monitors = get_monitor_info()
    return monitors[0] if monitors else {"left": 0, "top": 0, "width": 1920, "height": 1080}


def capture_monitor(monitor_index: int = 1, scale: float = 1.0) -> ScreenCapture:
    """
    Capture a specific monitor.

    Args:
        monitor_index: 1-based monitor index (1 = primary)
        scale: Downscale factor (1.0 = native, 0.5 = half resolution)

    Returns:
        ScreenCapture with full monitor image.
    """
    with mss.mss() as sct:
        if monitor_index >= len(sct.monitors):
            monitor_index = 1
        monitor = sct.monitors[monitor_index]
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        if scale != 1.0:
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        return ScreenCapture(
            image=img,
            monitor=dict(monitor),
            source="monitor",
            dpi_scale=scale,
        )


def capture_all_monitors(scale: float = 1.0) -> ScreenCapture:
    """Capture all monitors combined (virtual screen)."""
    with mss.mss() as sct:
        monitor = sct.monitors[0]  # Virtual screen covering all monitors
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        if scale != 1.0:
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        return ScreenCapture(
            image=img,
            monitor=dict(monitor),
            source="all_monitors",
            dpi_scale=scale,
        )


def capture_window(hwnd: int, scale: float = 1.0) -> ScreenCapture | None:
    """
    Capture a specific window by handle.

    Uses mss with window rect. Handles DPI scaling.
    """
    try:
        import win32gui

        # Get window rect
        rect = win32gui.GetWindowRect(hwnd)
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top

        if width <= 0 or height <= 0:
            return None

        # Capture the window region
        with mss.mss() as sct:
            monitor = {"left": left, "top": top, "width": width, "height": height}
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

            if scale != 1.0:
                new_size = (int(img.width * scale), int(img.height * scale))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            return ScreenCapture(
                image=img,
                monitor=monitor,
                source="window",
                dpi_scale=scale,
            )
    except Exception as exc:
        logger.warning(f"capture_window failed: {exc}")
        return None


def capture_region(
    left: int,
    top: int,
    width: int,
    height: int,
    scale: float = 1.0,
) -> ScreenCapture:
    """
    Capture a specific screen region.

    Args:
        left, top: Top-left corner (screen coordinates)
        width, height: Region dimensions
        scale: Downscale factor

    Returns:
        ScreenCapture of the region.
    """
    with mss.mss() as sct:
        monitor = {"left": left, "top": top, "width": width, "height": height}
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        if scale != 1.0:
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        return ScreenCapture(
            image=img,
            monitor=monitor,
            source="region",
            dpi_scale=scale,
        )


def capture_element_bounds(
    bounds: tuple[int, int, int, int],
    scale: float = 1.0,
    padding: int = 0,
) -> ScreenCapture:
    """
    Capture region around element bounds.

    Args:
        bounds: (x, y, w, h) - element bounding box
        scale: Downscale factor
        padding: Extra pixels around element

    Returns:
        ScreenCapture of the element region.
    """
    x, y, w, h = bounds
    left = x - padding
    top = y - padding
    width = w + 2 * padding
    height = h + 2 * padding
    return capture_region(left, top, width, height, scale)


def capture_active_window(scale: float = 1.0) -> ScreenCapture | None:
    """Capture the currently active window."""
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            return capture_window(hwnd, scale)
    except Exception:
        pass
    return None


def capture_foreground_region(scale: float = 1.0) -> ScreenCapture:
    """Capture the foreground window, or primary monitor if no window."""
    win_cap = capture_active_window(scale)
    if win_cap:
        return win_cap
    return capture_monitor(1, scale)


def downscale_image(image: Image.Image, max_dimension: int = 1024) -> Image.Image:
    """
    Downscale image to max dimension while preserving aspect ratio.
    Useful for vision model input limits.
    """
    if max(image.width, image.height) <= max_dimension:
        return image

    ratio = max_dimension / max(image.width, image.height)
    new_size = (int(image.width * ratio), int(image.height * ratio))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def image_to_base64(image: Image.Image, format: str = "PNG", quality: int = 85) -> str:
    """Convert PIL Image to base64 string."""
    import base64
    import io
    buf = io.BytesIO()
    if format == "JPEG":
        image.save(buf, format=format, quality=quality)
    else:
        image.save(buf, format=format)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def capture_for_vision(
    target: str = "auto",
    hwnd: int | None = None,
    bounds: tuple[int, int, int, int] | None = None,
    max_dimension: int = 1024,
) -> ScreenCapture:
    """
    Smart capture for vision model - chooses best capture method.

    Args:
        target: "auto" | "window" | "monitor" | "region" | "element"
        hwnd: Window handle (for "window" or "auto")
        bounds: Element bounds (for "element" or "auto" with bounds)
        max_dimension: Max dimension for vision model

    Returns:
        ScreenCapture optimized for vision analysis.
    """
    if target == "element" and bounds:
        cap = capture_element_bounds(bounds, padding=20)
    elif target == "window" and hwnd:
        cap = capture_window(hwnd)
        if not cap:
            cap = capture_monitor(1)
    elif target == "window" or target == "auto":
        # Try active window first
        cap = capture_active_window()
        if not cap:
            cap = capture_monitor(1)
    elif target == "monitor":
        cap = capture_monitor(1)
    else:
        cap = capture_monitor(1)

    # Downscale for vision if needed
    if max(cap.width, cap.height) > max_dimension:
        cap.image = downscale_image(cap.image, max_dimension)
        cap.dpi_scale = max_dimension / max(cap.width, cap.height)

    return cap