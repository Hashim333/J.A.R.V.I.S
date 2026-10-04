"""
screen/reader.py

Fast screen reading using Windows UI Automation (UIA).
This is the primary fast path - no screenshots, no OCR, no vision model.

UI Automation provides:
- Window titles, application names
- Control hierarchy (tree)
- Element names, roles/types (button, edit, combo, etc.)
- Bounding rectangles (screen coordinates)
- Enabled/disabled, selected/checked states
- Visible text where available (ValuePattern, TextPattern)

Only falls back to screenshot/vision when:
- Target not exposed through UIA
- Custom/canvas-rendered application
- User asks about visual content (images, charts, video)
- Layout/position matters for visual identification
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# UIA interfaces - prefer uiautomation (modern wrapper)
try:
    import uiautomation as auto
    UIA_AVAILABLE = True
except ImportError:
    UIA_AVAILABLE = False
    logger.warning("uiautomation not available - UI Automation disabled")

# UIA Constants
UIA_ElementControlTypeProperty = 30003
UIA_NameProperty = 30005
UIA_AutomationIdProperty = 30011
UIA_BoundingRectangleProperty = 30001
UIA_IsEnabledProperty = 30012
UIA_IsKeyboardFocusableProperty = 30008
UIA_HasKeyboardFocusProperty = 30009
UIA_IsControlElementProperty = 30010
UIA_IsContentElementProperty = 30011
UIA_LocalizedControlTypeProperty = 30004
UIA_ClassNameProperty = 30012
UIA_HelpTextProperty = 30013
UIA_IsOffscreenProperty = 30022
UIA_OrientationProperty = 30023
UIA_FrameworkIdProperty = 30024
UIA_IsRequiredForFormProperty = 30025
UIA_ItemStatusProperty = 30026
UIA_ItemTypeProperty = 30027
UIA_LabeledByProperty = 30028
UIA_NativeWindowHandleProperty = 30020

UIA_ControlType_Button = 50000
UIA_ControlType_Calendar = 50001
UIA_ControlType_CheckBox = 50002
UIA_ControlType_ComboBox = 50003
UIA_ControlType_Edit = 50004
UIA_ControlType_Hyperlink = 50005
UIA_ControlType_Image = 50006
UIA_ControlType_ListItem = 50007
UIA_ControlType_List = 50008
UIA_ControlType_Menu = 50009
UIA_ControlType_MenuBar = 50010
UIA_ControlType_MenuItem = 50011
UIA_ControlType_ProgressBar = 50012
UIA_ControlType_RadioButton = 50013
UIA_ControlType_ScrollBar = 50014
UIA_ControlType_Slider = 50015
UIA_ControlType_Spinner = 50016
UIA_ControlType_StatusBar = 50017
UIA_ControlType_Tab = 50017
UIA_ControlType_TabItem = 50018
UIA_ControlType_Text = 50020
UIA_ControlType_ToolBar = 50021
UIA_ControlType_ToolTip = 50022
UIA_ControlType_Tree = 50023
UIA_ControlType_TreeItem = 50024
UIA_ControlType_Custom = 50025
UIA_ControlType_Group = 50026
UIA_ControlType_Thumb = 50027
UIA_ControlType_DataGrid = 50028
UIA_ControlType_DataItem = 50029
UIA_ControlType_Document = 50030
UIA_ControlType_SplitButton = 50031
UIA_ControlType_Window = 50032
UIA_ControlType_Pane = 50033
UIA_ControlType_Header = 50034
UIA_ControlType_HeaderItem = 50035
UIA_ControlType_Table = 50036
UIA_ControlType_TitleBar = 50037
UIA_ControlType_Separator = 50038

CONTROL_TYPE_NAMES = {
    UIA_ControlType_Button: "button",
    UIA_ControlType_CheckBox: "checkbox",
    UIA_ControlType_ComboBox: "combobox",
    UIA_ControlType_Edit: "edit",
    UIA_ControlType_Hyperlink: "link",
    UIA_ControlType_Image: "image",
    UIA_ControlType_ListItem: "listitem",
    UIA_ControlType_List: "list",
    UIA_ControlType_Menu: "menu",
    UIA_ControlType_MenuBar: "menubar",
    UIA_ControlType_MenuItem: "menuitem",
    UIA_ControlType_ProgressBar: "progressbar",
    UIA_ControlType_RadioButton: "radiobutton",
    UIA_ControlType_ScrollBar: "scrollbar",
    UIA_ControlType_Slider: "slider",
    UIA_ControlType_Spinner: "spinner",
    UIA_ControlType_StatusBar: "statusbar",
    UIA_ControlType_Tab: "tab",
    UIA_ControlType_TabItem: "tabitem",
    UIA_ControlType_Text: "text",
    UIA_ControlType_ToolBar: "toolbar",
    UIA_ControlType_ToolTip: "tooltip",
    UIA_ControlType_Tree: "tree",
    UIA_ControlType_TreeItem: "treeitem",
    UIA_ControlType_Custom: "custom",
    UIA_ControlType_Group: "group",
    UIA_ControlType_Thumb: "thumb",
    UIA_ControlType_DataGrid: "datagrid",
    UIA_ControlType_DataItem: "dataitem",
    UIA_ControlType_Document: "document",
    UIA_ControlType_SplitButton: "splitbutton",
    UIA_ControlType_Window: "window",
    UIA_ControlType_Pane: "pane",
    UIA_ControlType_Header: "header",
    UIA_ControlType_HeaderItem: "headeritem",
    UIA_ControlType_Table: "table",
    UIA_ControlType_TitleBar: "titlebar",
    UIA_ControlType_Separator: "separator",
}


@dataclass
class UIElement:
    """Represents a UI Automation element with key properties."""
    automation_id: str = ""
    name: str = ""
    control_type: int = 0
    control_type_name: str = ""
    class_name: str = ""
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)  # left, top, right, bottom
    is_enabled: bool = True
    is_offscreen: bool = False
    has_focus: bool = False
    is_control_element: bool = True
    is_content_element: bool = True
    framework_id: str = ""
    children: list["UIElement"] = field(default_factory=list)
    parent: "UIElement | None" = None
    _raw_element: Any = None  # Raw IUIAutomationElement

    @property
    def center(self) -> tuple[int, int]:
        l, t, r, b = self.rect
        return ((l + r) // 2, (t + b) // 2)

    @property
    def width(self) -> int:
        l, t, r, b = self.rect
        return r - l

    @property
    def height(self) -> int:
        l, t, r, b = self.rect
        return b - t

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """Return (x, y, w, h) format."""
        l, t, r, b = self.rect
        return (l, t, r - l, b - t)

    def to_dict(self, include_children: bool = False) -> dict:
        d = {
            "automation_id": self.automation_id,
            "name": self.name,
            "control_type": self.control_type_name or "unknown",
            "class_name": self.class_name,
            "rect": self.rect,
            "bounds": self.bounds,
            "center": self.center,
            "is_enabled": self.is_enabled,
            "is_offscreen": self.is_offscreen,
            "has_focus": self.has_focus,
            "framework_id": self.framework_id,
        }
        if include_children:
            d["children"] = [c.to_dict(include_children=True) for c in self.children]
        return d


@dataclass
class WindowInfo:
    """Information about the active/foreground window."""
    hwnd: int = 0
    title: str = ""
    class_name: str = ""
    process_id: int = 0
    process_name: str = ""
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)
    monitor_index: int = 0
    is_maximized: bool = False
    is_minimized: bool = False


class ScreenReader:
    """
    High-level screen reader using Windows UI Automation.

    Usage:
        reader = ScreenReader()
        window = reader.get_active_window()
        elements = reader.get_ui_elements(window.hwnd)
        target = reader.find_element(elements, "Settings")
    """

    def __init__(self, cache_ttl: float = 0.5):
        self._cache_ttl = cache_ttl
        self._cached_tree: tuple[float, UIElement | None] = (0.0, None)
        self._cached_window: tuple[float, WindowInfo | None] = (0.0, None)
        self._automation = None
        self._init_uia()

    def _init_uia(self) -> None:
        """Initialize UI Automation using uiautomation."""
        if not UIA_AVAILABLE:
            return
        try:
            import uiautomation as auto
            self._automation = auto
            logger.info("UI Automation initialized successfully (uiautomation)")
        except Exception as exc:
            logger.warning(f"UI Automation init failed: {exc}")
            self._automation = None

    def is_available(self) -> bool:
        return self._automation is not None

    def get_active_window(self) -> WindowInfo | None:
        """Get info about the currently active (foreground) window."""
        # Check cache
        now = time.monotonic()
        if self._cached_window[0] + self._cache_ttl > now and self._cached_window[1]:
            return self._cached_window[1]

        if not UIA_AVAILABLE:
            return self._get_active_window_fallback()

        try:
            import win32gui
            import win32process

            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None

            # Get window title
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)

            # Get process info
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            process_name = ""
            try:
                import psutil
                process_name = psutil.Process(pid).name()
            except Exception:
                pass

            # Get window rect
            rect = win32gui.GetWindowRect(hwnd)
            left, top, right, bottom = rect

            # Check if maximized/minimized
            placement = win32gui.GetWindowPlacement(hwnd)
            is_maximized = placement[1] == 3  # SW_SHOWMAXIMIZED
            is_minimized = placement[1] == 2  # SW_SHOWMINIMIZED

            # Determine monitor
            monitor_index = self._get_monitor_for_rect(rect)

            info = WindowInfo(
                hwnd=hwnd,
                title=title,
                class_name=class_name,
                process_id=pid,
                process_name=process_name,
                rect=rect,
                monitor_index=monitor_index,
                is_maximized=is_maximized,
                is_minimized=is_minimized,
            )

            self._cached_window = (now, info)
            return info

        except Exception as exc:
            logger.warning(f"get_active_window failed: {exc}")
            return self._get_active_window_fallback()

    def _get_active_window_fallback(self) -> WindowInfo | None:
        """Fallback using pygetwindow if available."""
        try:
            import pygetwindow as gw
            win = gw.getActiveWindow()
            if win:
                return WindowInfo(
                    hwnd=win._hWnd,
                    title=win.title,
                    class_name="",
                    process_id=0,
                    process_name="",
                    rect=(win.left, win.top, win.right, win.bottom),
                    monitor_index=0,
                    is_maximized=win.isMaximized,
                    is_minimized=win.isMinimized,
                )
        except Exception:
            pass
        return None

    def _get_monitor_for_rect(self, rect: tuple[int, int, int, int]) -> int:
        """Determine which monitor a rect is primarily on."""
        try:
            from screen.capture import get_monitor_info
            monitors = get_monitor_info()
            left, top, right, bottom = rect
            cx, cy = (left + right) // 2, (top + bottom) // 2
            for i, m in enumerate(monitors):
                mx, my, mw, mh = m["left"], m["top"], m["width"], m["height"]
                if mx <= cx < mx + mw and my <= cy < my + mh:
                    return i
        except Exception:
            pass
        return 0

    def get_ui_tree(self, hwnd: int, max_depth: int = 10) -> UIElement | None:
        """
        Build UI element tree for a window using UI Automation.

        This is the FAST path - no screenshots, no OCR.
        Returns root element with children populated.
        """
        if not self.is_available():
            return None

        # Check cache
        now = time.monotonic()
        if self._cached_tree[0] + self._cache_ttl > now and self._cached_tree[1]:
            # Verify same window
            if self._cached_tree[1] and getattr(self._cached_tree[1], "_cached_hwnd", None) == hwnd:
                return self._cached_tree[1]

        try:
            import uiautomation as auto

            # Get element from window handle
            element = auto.ControlFromHandle(hwnd)
            if not element:
                return None

            # Build tree recursively
            root = self._build_element_tree(element, max_depth=max_depth)
            root._cached_hwnd = hwnd  # type: ignore

            self._cached_tree = (now, root)
            return root

        except Exception as exc:
            logger.warning(f"get_ui_tree failed: {exc}")
            return None

    def _build_element_tree(
        self,
        element,
        max_depth: int,
        depth: int = 0,
        parent: UIElement | None = None,
    ) -> UIElement | None:
        """Recursively build UI element tree using uiautomation."""
        if depth > max_depth:
            return None

        try:
            # Get properties from uiautomation element
            control_type = element.ControlType
            control_type_name = CONTROL_TYPE_NAMES.get(control_type, "unknown")

            # Get bounding rectangle
            rect = element.BoundingRectangle
            if rect:
                rect_tuple = (rect.left, rect.top, rect.right, rect.bottom)
            else:
                rect_tuple = (0, 0, 0, 0)

            ui_elem = UIElement(
                automation_id=str(element.AutomationId or ""),
                name=str(element.Name or ""),
                control_type=control_type,
                control_type_name=control_type_name,
                class_name=str(element.ClassName or ""),
                rect=rect_tuple,
                is_enabled=element.IsEnabled,
                is_offscreen=element.IsOffscreen,
                has_focus=element.HasKeyboardFocus,
                is_control_element=True,  # uiautomation doesn't expose this directly
                is_content_element=True,
                framework_id=str(element.FrameworkId or ""),
                parent=parent,
                _raw_element=element,
            )

            # Build children
            if depth < max_depth:
                try:
                    children = element.GetChildren()
                    for child in children:
                        child_elem = self._build_element_tree(child, max_depth, depth + 1, ui_elem)
                        if child_elem:
                            ui_elem.children.append(child_elem)
                except Exception:
                    pass

            return ui_elem

        except Exception as exc:
            logger.debug(f"Failed to build element: {exc}")
            return None

    def get_ui_elements(self, hwnd: int | None = None) -> list[UIElement]:
        """Get flat list of all UI elements in window."""
        if hwnd is None:
            window = self.get_active_window()
            if not window:
                return []
            hwnd = window.hwnd

        root = self.get_ui_tree(hwnd)
        if not root:
            return []

        elements = []
        def collect(elem):
            elements.append(elem)
            for child in elem.children:
                collect(child)
        collect(root)
        return elements

    def find_element_by_name(
        self,
        name: str,
        hwnd: int | None = None,
        exact: bool = False,
    ) -> list[UIElement]:
        """Find elements by name (accessible name)."""
        elements = self.get_ui_elements(hwnd)
        results = []
        target = name.casefold()
        for elem in elements:
            elem_name = elem.name.casefold()
            if exact:
                if elem_name == target:
                    results.append(elem)
            else:
                if target in elem_name:
                    results.append(elem)
        return results

    def find_element_by_role(
        self,
        role: str,
        hwnd: int | None = None,
    ) -> list[UIElement]:
        """Find elements by control type/role."""
        elements = self.get_ui_elements(hwnd)
        target = role.casefold()
        results = []
        for elem in elements:
            if target in elem.control_type_name.casefold():
                results.append(elem)
        return results

    def find_element(
        self,
        name: str = "",
        role: str = "",
        hwnd: int | None = None,
    ) -> list[UIElement]:
        """Find elements by name and/or role."""
        elements = self.get_ui_elements(hwnd)
        results = []
        name_target = name.casefold() if name else ""
        role_target = role.casefold() if role else ""

        for elem in elements:
            match = True
            if name_target:
                if name_target not in elem.name.casefold():
                    match = False
            if role_target:
                if role_target not in elem.control_type_name.casefold():
                    match = False
            if match:
                results.append(elem)

        return results

    def get_focused_element(self, hwnd: int | None = None) -> UIElement | None:
        """Get the currently focused element."""
        elements = self.get_ui_elements(hwnd)
        for elem in elements:
            if elem.has_focus:
                return elem
        return None

    def read_screen_fast(self, hwnd: int | None = None) -> dict[str, Any]:
        """
        Fast screen reading using UI Automation only.

        Returns structured text representation of the screen without OCR.
        """
        if hwnd is None:
            window = self.get_active_window()
            if not window:
                return {"success": False, "error": "No active window"}
            hwnd = window.hwnd

        root = self.get_ui_tree(hwnd)
        if not root:
            return {"success": False, "error": "UI Automation not available or failed"}

        # Collect readable text from elements
        lines = []
        interactive_elements = []

        def collect_text(elem: UIElement, indent: int = 0):
            # Skip purely layout elements unless they have names
            is_interactive = elem.control_type_name in (
                "button", "checkbox", "combobox", "edit", "hyperlink",
                "listitem", "menuitem", "radiobutton", "slider", "spinner",
                "splitbutton", "tabitem", "treeitem",
            )
            has_name = bool(elem.name.strip())
            has_value = False  # Would need ValuePattern to get actual value

            if has_name or is_interactive:
                prefix = "  " * indent
                role = elem.control_type_name
                state = ""
                if not elem.is_enabled:
                    state += " [disabled]"
                if elem.has_focus:
                    state += " [focused]"
                if elem.is_offscreen:
                    state += " [offscreen]"

                line = f"{prefix}{role}: {elem.name}" if has_name else f"{prefix}{role}{state}"
                lines.append(line)

                if is_interactive:
                    interactive_elements.append({
                        "name": elem.name,
                        "role": role,
                        "bounds": elem.bounds,
                        "center": elem.center,
                        "enabled": elem.is_enabled,
                        "focused": elem.has_focus,
                    })

            for child in elem.children:
                collect_text(child, indent + 1)

        collect_text(root)

        return {
            "success": True,
            "text": "\n".join(lines),
            "elements": interactive_elements,
            "element_count": len(interactive_elements),
            "window_title": getattr(root, "_cached_hwnd", "unknown"),
        }


# Module-level functions for backward compatibility
_default_reader: ScreenReader | None = None


def _get_reader() -> ScreenReader:
    global _default_reader
    if _default_reader is None:
        _default_reader = ScreenReader()
    return _default_reader


def get_active_window_info() -> dict[str, Any]:
    """Get active window info as dict."""
    reader = _get_reader()
    window = reader.get_active_window()
    if not window:
        return {"success": False, "error": "No active window"}
    return {
        "success": True,
        "hwnd": window.hwnd,
        "title": window.title,
        "class_name": window.class_name,
        "process_id": window.process_id,
        "process_name": window.process_name,
        "rect": window.rect,
        "monitor": window.monitor_index,
        "maximized": window.is_maximized,
        "minimized": window.is_minimized,
    }


def read_screen_fast(hwnd: int | None = None) -> dict[str, Any]:
    """Fast screen read using UI Automation."""
    return _get_reader().read_screen_fast(hwnd)


def get_ui_elements(hwnd: int | None = None) -> list[dict]:
    """Get all UI elements as dicts."""
    reader = _get_reader()
    elements = reader.get_ui_elements(hwnd)
    return [e.to_dict() for e in elements]


def find_element_by_name(name: str, hwnd: int | None = None, exact: bool = False) -> list[dict]:
    """Find elements by accessible name."""
    reader = _get_reader()
    results = reader.find_element_by_name(name, hwnd, exact)
    return [e.to_dict() for e in results]


def find_element_by_role(role: str, hwnd: int | None = None) -> list[dict]:
    """Find elements by control type/role."""
    reader = _get_reader()
    results = reader.find_element_by_role(role, hwnd)
    return [e.to_dict() for e in results]