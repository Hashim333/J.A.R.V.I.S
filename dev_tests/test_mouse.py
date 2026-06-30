"""
dev_tests/test_mouse.py
-----------------------
Interactive manual tests for automation/mouse.py.

Menu
----
1  Move to (500, 500)
2  Left Click
3  Right Click
4  Double Click
5  Drag  (700, 300) -> (900, 500)
6  Scroll Down
7  Current Position
8  Exit

Run:
    python dev_tests/test_mouse.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Allow running from the project root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.mouse import MouseController

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MOVE_TARGET:        tuple[int, int] = (500, 500)
DRAG_START:         tuple[int, int] = (700, 300)
DRAG_END:           tuple[int, int] = (900, 500)
SCROLL_AMOUNT:      int             = -5   # negative = down
SETTLE_SECONDS:     float           = 0.3  # pause after each action

MENU = """
╔══════════════════════════════╗
║   MouseController  Tests     ║
╠══════════════════════════════╣
║  1  Move to (500, 500)       ║
║  2  Left Click               ║
║  3  Right Click              ║
║  4  Double Click             ║
║  5  Drag (700,300)→(900,500) ║
║  6  Scroll Down              ║
║  7  Current Position         ║
║  8  Exit                     ║
╚══════════════════════════════╝
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(result: bool) -> str:
    return "✓  OK" if result else "✗  FAILED"


def _pause() -> None:
    time.sleep(SETTLE_SECONDS)


# ---------------------------------------------------------------------------
# Test actions
# ---------------------------------------------------------------------------

def test_move(mouse: MouseController) -> None:
    x, y = MOVE_TARGET
    print(f"  Moving to ({x}, {y}) …")
    result = mouse.move_to(x, y)
    _pause()
    print(f"  {_ok(result)}")


def test_left_click(mouse: MouseController) -> None:
    print("  Left-clicking at current position …")
    result = mouse.left_click()
    _pause()
    print(f"  {_ok(result)}")


def test_right_click(mouse: MouseController) -> None:
    print("  Right-clicking at current position …")
    result = mouse.right_click()
    _pause()
    print(f"  {_ok(result)}")


def test_double_click(mouse: MouseController) -> None:
    print("  Double-clicking at current position …")
    result = mouse.double_click()
    _pause()
    print(f"  {_ok(result)}")


def test_drag(mouse: MouseController) -> None:
    sx, sy = DRAG_START
    ex, ey = DRAG_END
    print(f"  Moving to drag start ({sx}, {sy}) …")
    mouse.move_to(sx, sy)
    _pause()
    print(f"  Dragging to ({ex}, {ey}) …")
    result = mouse.drag_to(ex, ey, duration=0.6)
    _pause()
    print(f"  {_ok(result)}")


def test_scroll_down(mouse: MouseController) -> None:
    print(f"  Scrolling {abs(SCROLL_AMOUNT)} clicks down …")
    result = mouse.scroll(SCROLL_AMOUNT)
    _pause()
    print(f"  {_ok(result)}")


def test_get_position(mouse: MouseController) -> None:
    x, y = mouse.get_position()
    if (x, y) == (-1, -1):
        print("  ✗  FAILED — get_position returned (-1, -1)")
    else:
        print(f"  Current position : ({x}, {y})  ✓  OK")


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

ACTIONS: dict[str, tuple[str, object]] = {
    "1": ("Move to (500, 500)",          test_move),
    "2": ("Left Click",                  test_left_click),
    "3": ("Right Click",                 test_right_click),
    "4": ("Double Click",                test_double_click),
    "5": ("Drag (700,300) → (900,500)",  test_drag),
    "6": ("Scroll Down",                 test_scroll_down),
    "7": ("Current Position",            test_get_position),
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    mouse = MouseController()
    mouse.fail_safe(True)   # keep fail-safe on; move cursor to any corner to abort

    print(MENU)
    print("  Tip: move the cursor to any screen corner to abort immediately.\n")

    while True:
        try:
            choice = input("  Choice [1-8]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Interrupted — exiting.")
            break

        if choice == "8":
            print("  Exiting.")
            break

        if choice not in ACTIONS:
            print("  Invalid choice — enter a number from 1 to 8.")
            continue

        label, fn = ACTIONS[choice]
        print(f"\n  ── {label} ──")
        fn(mouse)
        print()


if __name__ == "__main__":
    main()