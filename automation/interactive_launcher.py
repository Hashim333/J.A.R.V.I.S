"""
automation/interactive_launcher.py

Handles interactive application launching scenarios:

- Chrome profile picker detection and selection
- Multi-version application selection (e.g., Premiere Pro)
- Launcher dialog detection and waiting (e.g., Adobe Creative Cloud)
- Generic multi-choice UI interaction
"""

from __future__ import annotations

import logging
import time
from typing import Callable

import automation.ui_detector as ui
import automation.apps as apps

logger = logging.getLogger(__name__)


def handle_interactive_launch(
    app_name: str,
    process_name: str,
    voice_input: Callable[[], str | None] | None,
    profile: str | None = None,
) -> dict | None:
    """After launching an app, check for interactive dialogs.

    Returns a result dict if interaction was handled, or None if no
    interactive dialog was detected (app opened normally).
    """
    # Give the app a moment to start
    time.sleep(0.5)

    # Determine the interaction type based on the app
    app_lower = app_name.casefold()

    if "chrome" in app_lower or "google chrome" in app_lower or "chromium" in app_lower:
        return _handle_chrome_picker(process_name, voice_input, profile)

    if "premiere" in app_lower or "premiere pro" in app_lower:
        return _handle_premiere_launch(process_name, voice_input)

    # No generic fallback — unknown apps return None (app opened normally).
    return None


def _handle_chrome_picker(
    process_name: str,
    voice_input: Callable[[], str | None] | None,
    profile: str | None = None,
) -> dict | None:
    """Handle Chrome profile picker if it appears after launching Chrome.

    If a profile was already specified, we look for an existing Chrome window
    with that profile — the picker shouldn't appear in that case.
    If no profile was specified and the picker appears, list profiles and ask.
    """
    logger.info("INTERACTIVE_LAUNCH chrome profile=%s", profile)

    # Wait briefly for the profile picker to appear
    time.sleep(1.0)

    # Check if Chrome's profile picker window is showing
    picker_window = ui.detect_window_by_title("Chrome")
    if not picker_window:
        # Chrome might have opened directly
        return None

    # Look for the "Choose a profile" text
    profile_cards = ui.find_profile_cards()
    if not profile_cards:
        # No profile picker detected, Chrome opened normally
        logger.info("INTERACTIVE_LAUNCH chrome result=no_picker")
        return None

    logger.info("INTERACTIVE_LAUNCH chrome profiles=%s",
                [p.text for p in profile_cards])

    names = [p.text for p in profile_cards]

    if profile:
        # User specified a profile — find and click it
        selected = _find_profile_by_name(names, profile)
        if selected:
            profile_text = names[selected]
            logger.info("INTERACTIVE_LAUNCH chrome profile_selected=%s", profile_text)
            ui.click_element(profile_cards[selected])
            _wait_for_chrome_ready(process_name)
            return {
                "success": True,
                "message": f"Opened Chrome with {profile_text} profile.",
                "details": {"action": "profile_selected", "profile": profile_text},
            }
        else:
            return {
                "success": False,
                "message": f"I couldn't find a profile named '{profile}'.",
                "details": {"available_profiles": names},
            }

    # No profile specified — ask the user
    if len(names) == 1:
        # Only one profile, select it automatically
        logger.info("INTERACTIVE_LAUNCH chrome auto_select=%s", names[0])
        ui.click_element(profile_cards[0])
        _wait_for_chrome_ready(process_name)
        return {
            "success": True,
            "message": f"Opened Chrome with {names[0]} profile.",
            "details": {"action": "auto_selected", "profile": names[0]},
        }

    # Multiple profiles — ask user
    _speak_choices("I found multiple Chrome profiles.", names, voice_input)
    selected_name = _ask_choice(names, voice_input)

    if selected_name is None:
        return {
            "success": False,
            "message": "Cancelled Chrome profile selection.",
            "details": {"action": "cancelled"},
        }

    selected_idx = _find_profile_by_name(names, selected_name)
    if selected_idx is None:
        return {
            "success": False,
            "message": f"I couldn't find a profile named '{selected_name}'.",
            "details": {"available_profiles": names},
        }

    logger.info("INTERACTIVE_LAUNCH chrome user_selected=%s", selected_name)
    ui.click_element(profile_cards[selected_idx])
    _wait_for_chrome_ready(process_name)
    return {
        "success": True,
        "message": f"Opened Chrome with {selected_name} profile.",
        "details": {"action": "user_selected", "profile": selected_name},
    }


def _handle_premiere_launch(
    process_name: str,
    voice_input: Callable[[], str | None] | None,
) -> dict | None:
    """Handle Premiere Pro launch — detect Creative Cloud and multi-version."""
    logger.info("INTERACTIVE_LAUNCH premiere_pro")

    # Check if Creative Cloud launcher appears
    cc_detected = ui.wait_for_any_text(
        ["creative cloud", "adobe creative cloud", "loading", "please wait"],
        timeout=8.0, interval=0.5,
    )

    if cc_detected:
        logger.info("INTERACTIVE_LAUNCH premiere_pro cc_launcher_detected")
        # Wait for Creative Cloud to finish loading
        ui.wait_for_text_to_disappear("loading", timeout=20.0, interval=0.5)

    # After launch, wait for Premiere Pro window to appear
    premiere_window = ui.wait_for_any_text(
        ["premiere pro", "adobe premiere pro"],
        timeout=15.0, interval=0.5,
    )

    if premiere_window:
        logger.info("INTERACTIVE_LAUNCH premiere_pro window_detected")
        return None  # App opened successfully

    logger.info("INTERACTIVE_LAUNCH premiere_pro result=no_window_detected")
    return None


def _handle_generic_dialog(
    process_name: str,
    voice_input: Callable[[], str | None] | None,
) -> dict | None:
    """Generic handler for any app dialog that might appear after launch.

    Detects dialogs with "Choose", "Select", "Open with", "Which" titles
    and offers the user choices.
    """
    time.sleep(1.0)

    # Look for a dialog window
    dialog_texts = ["choose", "select", "which", "open with", "pick"]
    detected = ui.wait_for_any_text(dialog_texts, timeout=2.0, interval=0.3)
    if not detected:
        return None

    # Try to extract options from the dialog
    options = _extract_dialog_options()
    if len(options) >= 2:
        _speak_choices("I found multiple options.", options, voice_input)
        selected = _ask_choice(options, voice_input)
        if selected:
            _click_option(selected, options)
        return {
            "success": True,
            "message": f"Selected {selected}.",
            "details": {"selected": selected},
        }

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_profile_by_name(names: list[str], search: str) -> int | None:
    """Find a profile index by name (case-insensitive, partial match)."""
    search_lower = search.strip().casefold()
    if not search_lower:
        return None
    for i, name in enumerate(names):
        if name.casefold() == search_lower:
            return i
    # Partial match
    for i, name in enumerate(names):
        if search_lower in name.casefold() or name.casefold().startswith(search_lower):
            return i
    return None


def _speak_choices(
    header: str,
    choices: list[str],
    voice_input: Callable[[], str | None] | None,
) -> None:
    """Print and optionally speak available choices."""
    print(f"\n{header}")
    for i, choice in enumerate(choices, 1):
        print(f"  {i}. {choice}")
    print()

    # If we have voice, use TTS to speak the choices
    try:
        from voice.speaker import speak
        msg = f"{header}."
        if choices:
            msg += " " + ", ".join(choices) + "."
            msg += " Which one would you like?"
        speak(msg)
    except Exception:
        logger.warning("INTERACTIVE_LAUNCH TTS unavailable")


def _ask_choice(
    choices: list[str],
    voice_input: Callable[[], str | None] | None,
    retries: int = 2,
) -> str | None:
    """Ask the user to pick from a list of choices.

    Returns the selected choice text, or None if cancelled.
    """
    for attempt in range(retries):
        if voice_input is not None:
            print("Listening for your choice...")
            raw = voice_input()
            if raw is None:
                reply = input("Enter your choice: ").strip()
            else:
                reply = raw.strip()
        else:
            reply = input("Enter your choice: ").strip()

        if not reply:
            if attempt < retries - 1:
                print("Sorry, I didn't catch that. Please try again.")
                continue
            return None

        reply_lower = reply.casefold()

        # Check by number
        if reply_lower.isdigit():
            idx = int(reply_lower) - 1
            if 0 <= idx < len(choices):
                return choices[idx]

        # Check by name (exact match)
        for c in choices:
            if c.casefold() == reply_lower:
                return c

        # Check by partial match
        matches = [c for c in choices if reply_lower in c.casefold()]
        if len(matches) == 1:
            return matches[0]

        if len(matches) > 1:
            print(f"Did you mean {', '.join(matches)}?")
            continue

        print(f"I couldn't find '{reply}'. Available: {', '.join(choices)}")
        if attempt < retries - 1:
            print("Please try again.")

    return None


def _extract_dialog_options() -> list[str]:
    """Extract selectable options from a dialog window.

    Looks for text blocks that are likely clickable options (lists, buttons).
    """
    screen_text = ui.get_screen_text()
    lines = [l.strip() for l in screen_text.split("\n") if l.strip()]

    # Filter out common dialog elements
    skip_words = {"close", "cancel", "ok", "apply", "yes", "no", "x"}
    options: list[str] = []
    for line in lines:
        words = line.split()
        if len(words) > 3:
            continue  # Skip long sentences
        if len(words) == 1 and len(words[0]) > 20:
            continue  # Single very long word is unlikely an option
        lower = line.casefold()
        if lower in skip_words or any(s in lower for s in skip_words):
            continue
        if len(line) >= 2 and len(line) <= 30:
            options.append(line)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for o in options:
        if o.casefold() not in seen:
            seen.add(o.casefold())
            unique.append(o)

    return unique


def _click_option(selected: str, all_options: list[str]) -> bool:
    """Find and click a UI element matching the selected option."""
    elements = ui.find_text_on_screen(selected, threshold=0.6)
    if elements:
        ui.click_element(elements[0])
        return True
    logger.warning("INTERACTIVE_LAUNCH click_option text=%s result=not_found", selected)
    return False


def _wait_for_chrome_ready(process_name: str, timeout: float = 15.0) -> bool:
    """Wait for Chrome to finish opening (picker dismissed, browser window appears)."""
    logger.info("INTERACTIVE_LAUNCH wait_for_chrome timeout=%.1fs", timeout)

    # Wait for the profile picker to disappear
    ui.wait_for_text_to_disappear("choose a profile", timeout=timeout)

    # Wait for Chrome process to have a visible window
    import pygetwindow as gw
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            chrome_windows = gw.getWindowsWithTitle("Chrome")
            for win in chrome_windows:
                title_lower = win.title.casefold()
                if "chrome" in title_lower and win.width > 200:
                    logger.info("INTERACTIVE_LAUNCH chrome_ready title=%s", win.title)
                    return True
        except Exception:
            pass
        time.sleep(0.5)

    logger.warning("INTERACTIVE_LAUNCH chrome_ready timeout exceeded")
    return False
