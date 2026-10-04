"""
screen/ - JARVIS Screen Reading & Interaction Module

Provides general desktop "see and act" capability using Windows UI Automation
as the fast path, with screenshot/vision fallback for custom-rendered apps.

Flow:
    USER REQUEST -> AGENT/BRAIN -> SCREEN TOOL -> OBSERVE -> FIND TARGET
    -> ACT -> OBSERVE AGAIN -> VERIFY -> REPORT RESULT

Key components:
- reader.py: UI Automation based fast screen reading
- ui_tree.py: UI element tree extraction and navigation
- capture.py: Efficient screen capture (region/window/monitor)
- vision.py: Vision model integration for visual understanding
- input.py: Safe desktop input actions (click, drag, scroll, type)
- target_finder.py: Natural language -> UI element mapping
- verifier.py: Post-action verification
"""

from __future__ import annotations

from screen.reader import (
    get_active_window_info,
    read_screen_fast,
    get_ui_elements,
    find_element_by_name,
    find_element_by_role,
    ScreenReader,
)
from screen.capture import (
    capture_region,
    capture_window,
    capture_monitor,
    ScreenCapture,
)
from screen.target_finder import (
    find_target,
    find_target_one,
    TargetFinder,
)
from screen.input import (
    click_at,
    double_click_at,
    right_click_at,
    drag_from_to,
    scroll_at,
    type_text,
    send_hotkey,
    InputController,
)
from screen.verifier import (
    verify_action,
    Verifier,
)

__all__ = [
    # Reader
    "get_active_window_info",
    "read_screen_fast",
    "get_ui_elements",
    "find_element_by_name",
    "find_element_by_role",
    "ScreenReader",
    # Capture
    "capture_region",
    "capture_window",
    "capture_monitor",
    "ScreenCapture",
    # Target finding
    "find_target",
    "find_target_one",
    "TargetFinder",
    # Input
    "click_at",
    "double_click_at",
    "right_click_at",
    "drag_from_to",
    "scroll_at",
    "type_text",
    "send_hotkey",
    "InputController",
    # Verification
    "verify_action",
    "Verifier",
]

__version__ = "1.0.0"