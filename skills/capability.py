"""
skills/capability.py

Data-driven capability catalog for the Skill Manager.

Each ``Capability`` describes something JARVIS can (or could) do:

  * ``implemented=True``  -> backed by the Parser/Planner/Executor today.
  * ``implemented=False`` -> acknowledged-but-not-yet-built.  The Skill
    Manager uses its ``keywords`` to recognise requests, records them in
    the Skill Registry, and replies with the closest available capability.

Adding a skill is a plugin action: append a new ``Capability`` entry to
``CATALOG`` (and, once it is really executable, set ``implemented=True``
and add the parser rules/handlers for its actions).  No core assistant
code has to change.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    """A single named capability of the assistant."""

    name: str  # slug, e.g. "email.send"
    label: str  # human label, e.g. "Send and read email"
    category: str  # grouping, e.g. "communication"
    actions: frozenset[str] = frozenset()  # intent/action strings it provides
    keywords: tuple[str, ...] = ()  # phrases that signal this request
    implemented: bool = True  # False -> recognised but not yet built
    missing: str = ""  # what is needed to build it (shown to the user)
    dependencies: tuple[str, ...] = ()  # prerequisites
    closest: str = ""  # label of the closest implemented capability


# Keywords that unambiguously identify a request on their own, even as a
# single word (e.g. "whatsapp my friend" is clearly a messaging request).
_STRONG_KEYWORDS: frozenset[str] = frozenset({
    "whatsapp", "telegram", "discord", "slack", "signal", "imessage",
    "gmail", "outlook", "mail", "inbox", "scrape", "scraping",
    "alarm", "lights", "thermostat", "remind", "siri", "alexa",
    "home assistant",
})


def keyword_weight(keyword: str) -> int:
    """Weight a keyword: multi-word phrases and unambiguous tokens are stronger."""
    if " " in keyword:
        return 2
    if keyword in _STRONG_KEYWORDS:
        return 2
    return 1


CATALOG: tuple[Capability, ...] = (
    # ------------------------------------------------------------------
    # Implemented capabilities (Parser/Planner/Executor today)
    # ------------------------------------------------------------------
    Capability(
        name="applications.control",
        label="open, close, focus and manage applications",
        category="applications",
        actions=frozenset({
            "open_app", "close_app", "focus_app", "restart_app",
            "minimize_app", "maximize_app", "restore_app", "close_all_apps",
        }),
        keywords=(
            "open", "launch", "start", "run", "close", "quit", "exit app",
            "focus", "switch to", "minimize", "maximize", "restore",
            "open app", "close app", "open application", "close application",
        ),
    ),
    Capability(
        name="websites.open",
        label="open websites in the browser",
        category="browser",
        actions=frozenset({"open_website"}),
        keywords=(
            "open website", "go to website", "open the website", "take me to",
        ),
    ),
    Capability(
        name="search.web",
        label="search the web",
        category="browser",
        actions=frozenset({"search"}),
        keywords=(
            "search", "search for", "google", "look up", "look up", "web search",
        ),
    ),
    Capability(
        name="media.control",
        label="control music and YouTube playback",
        category="media",
        actions=frozenset({
            "play_music", "media_pause", "media_resume", "media_next",
            "media_previous", "skip_ad", "like_video", "subscribe_channel",
            "continue_watching", "scroll_page",
        }),
        keywords=(
            "play", "play music", "pause", "resume", "next", "previous",
            "skip ad", "youtube", "music",
        ),
    ),
    Capability(
        name="volume.control",
        label="adjust the volume",
        category="media",
        actions=frozenset({
            "increase_volume", "decrease_volume", "set_volume",
            "mute_volume", "unmute_volume",
        }),
        keywords=("volume", "volume up", "volume down", "mute", "unmute"),
    ),
    Capability(
        name="files.manage",
        label="open, find, copy, move, rename and delete files",
        category="files",
        actions=frozenset({
            "open_file", "find_file", "open_file_location",
            "copy_file", "move_file", "rename_file", "delete_file",
            "open_special_folder",
        }),
        keywords=(
            "file", "folder", "copy", "move", "rename", "delete file",
            "find file", "open file", "downloads", "documents",
        ),
    ),
    Capability(
        name="system.control",
        label="control Windows: lock, shutdown, restart, brightness, WiFi, Bluetooth",
        category="system",
        actions=frozenset({
            "lock", "shutdown_windows", "restart", "sleep", "sign_out",
            "set_brightness", "wifi_on", "wifi_off", "bluetooth_on",
            "bluetooth_off", "airplane_mode_on", "airplane_mode_off",
            "system_status", "open_task_manager", "open_device_manager",
            "open_control_panel", "format_drive", "kill_process",
            "screenshot", "cancel_shutdown",
        }),
        keywords=(
            "shutdown", "restart", "reboot", "lock computer", "sleep",
            "brightness", "wifi", "bluetooth", "airplane mode", "battery",
            "screenshot", "task manager", "device manager", "kill process",
            "system status",
        ),
    ),
    Capability(
        name="vision.screen",
        label="read and understand the screen",
        category="vision",
        actions=frozenset({
            "read_screen", "describe_screen", "click_element",
            "find_element", "read_pdf", "ocr_image", "read_error", "fill_form",
        }),
        keywords=(
            "screen", "what do you see", "read screen", "describe screen",
            "ocr", "read pdf", "read error",
        ),
    ),
    Capability(
        name="security.pentest",
        label="security and pentest tooling",
        category="security",
        actions=frozenset({
            "create_pentest_report", "organize_scan_results",
            "summarize_scan_results", "create_pentest_project",
        }),
        keywords=(
            "pentest", "penetration test", "scan results", "pentest report",
            "pentest project",
        ),
    ),
    # ------------------------------------------------------------------
    # Acknowledged-but-unimplemented skills (Skill Registry entries)
    # ------------------------------------------------------------------
    Capability(
        name="email.send",
        label="send and read email",
        category="communication",
        implemented=False,
        missing="an email integration (an email provider API or mail client "
                "automation)",
        dependencies=("email API or mail-client automation",),
        closest="open your email in the browser, or search the web",
        keywords=(
            "email", "send an email", "send email", "draft email",
            "compose email", "open email", "open my email", "email my",
            "check email", "check my email", "read my email", "read my inbox",
            "my inbox", "email to", "email about", "reply to",
        ),
    ),
    Capability(
        name="messaging.send",
        label="send chat and text messages",
        category="communication",
        implemented=False,
        missing="a messaging-app automation layer (web automation or an "
                "official chat API)",
        dependencies=("messaging-app automation or API",),
        closest="open the chat app in your browser",
        keywords=(
            "message", "send a message", "send message", "send a text",
            "text message", "text someone", "text my", "message my",
            "message someone", "dm", "whatsapp", "telegram", "discord",
            "slack", "imessage",
        ),
    ),
    Capability(
        name="calendar.schedule",
        label="manage calendar events and reminders",
        category="productivity",
        implemented=False,
        missing="a calendar and reminders integration",
        dependencies=("calendar/reminders integration",),
        closest="open your calendar in the browser",
        keywords=(
            "reminder", "remind me", "set a reminder", "calendar",
            "schedule a meeting", "schedule an appointment", "appointment",
            "set an alarm", "alarm", "add to my calendar",
        ),
    ),
    Capability(
        name="productivity.documents",
        label="create and edit documents, spreadsheets and presentations",
        category="productivity",
        implemented=False,
        missing="a document-generation automation engine",
        dependencies=("document-generation automation",),
        closest="open the document app, or search the web",
        keywords=(
            "create a document", "write a document", "create a spreadsheet",
            "create a presentation", "word document", "powerpoint",
            "draft a", "compose a", "write a letter", "make a slide",
        ),
    ),
    Capability(
        name="browser.automation",
        label="automate multi-step browser workflows",
        category="browser",
        implemented=False,
        missing="a headless-browser automation engine for multi-step workflows",
        dependencies=("headless browser automation",),
        closest="navigate and search the web",
        keywords=(
            "automate", "web automation", "multi step", "workflow",
            "scrape", "scraping", "scrape data", "extract data from",
            "web scraping",
        ),
    ),
    Capability(
        name="home.automation",
        label="control smart-home devices",
        category="home",
        implemented=False,
        missing="a smart-home platform integration (e.g. Home Assistant or "
                "vendor apps)",
        dependencies=("smart-home platform integration",),
        closest="control system brightness and WiFi, or open the vendor app",
        keywords=(
            "smart home", "turn on the lights", "turn off the lights",
            "turn on the light", "turn off the light", "lights", "thermostat",
            "air conditioner", "smart plug", "garage", "home assistant",
        ),
    ),
)


def capability_by_name(name: str) -> Capability | None:
    """Return the catalog entry for *name* (or ``None``)."""
    for cap in CATALOG:
        if cap.name == name:
            return cap
    return None


def implemented_capabilities() -> list[Capability]:
    """Every capability that is available today, sorted by category."""
    return sorted(
        (c for c in CATALOG if c.implemented),
        key=lambda c: (c.category, c.name),
    )


def unimplemented_capabilities() -> list[Capability]:
    """Every acknowledged-but-unimplemented capability."""
    return sorted(
        (c for c in CATALOG if not c.implemented),
        key=lambda c: (c.category, c.name),
    )
