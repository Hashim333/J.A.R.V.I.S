"""
system_awareness/answers.py — instant natural-language answers.

The brain can answer system questions *without searching* by asking this
module to render the current ``SystemAwarenessSnapshot`` into a short
natural-language reply.  Every handler is deterministic and returns a string
or ``None`` (no confident answer).  The reasoner layer can also consume
``describe()`` as grounding context.

All answers are honest: when a domain has no data, the handler says so
instead of inventing a value.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from system_awareness.model import SystemAwarenessSnapshot


def _fmt_bytes_per_sec(bps: float) -> str:
    if bps <= 0:
        return "0 B/s"
    if bps >= 1024 ** 3:
        return f"{bps / (1024 ** 3):.2f} GB/s"
    if bps >= 1024 ** 2:
        return f"{bps / (1024 ** 2):.1f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps:.0f} B/s"


def _fmt_seconds(seconds: float) -> str:
    if seconds <= 0:
        return ""
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"about {minutes} min"
    return f"about {minutes // 60}h {minutes % 60}m"


# ── Handlers: each takes a snapshot and returns str | None ────────────


def _answer_battery(snap: SystemAwarenessSnapshot) -> str | None:
    b = snap.battery
    if b is None or not b.present:
        return "There's no battery detected on this system."
    parts = [f"Battery is at {b.percent:.0f}%"]
    parts.append("and charging" if b.charging else "on battery")
    remaining = _fmt_seconds(b.time_remaining_seconds)
    if remaining:
        parts.append(f"({remaining} remaining)")
    if b.health_percent is not None:
        parts.append(f"health {b.health_percent:.0f}%")
    return " ".join(parts) + "."


def _answer_top_ram(snap: SystemAwarenessSnapshot) -> str | None:
    proc = snap.top_ram_process()
    if proc is None or proc.memory_mb <= 0:
        return "I don't have process memory data right now."
    return (
        f"{proc.name} is using the most RAM at {proc.memory_mb:.0f} MB "
        f"({proc.memory_percent:.1f}% of system memory)."
    )


def _answer_top_cpu(snap: SystemAwarenessSnapshot) -> str | None:
    proc = snap.top_cpu_process()
    if proc is None:
        return "I don't have process CPU data right now."
    return f"{proc.name} is using the most CPU at {proc.cpu_percent:.0f}%."


def _answer_tabs(snap: SystemAwarenessSnapshot) -> str | None:
    if not snap.windows:
        return "I can't see any browser windows right now."
    browsers: dict[str, int] = {}
    for name in ("chrome", "edge", "firefox", "brave", "opera", "vivaldi"):
        count = snap.browser_tab_count(name)
        if count:
            browsers[name.title()] = count
    if not browsers:
        return "No open browser windows found."
    total = sum(browsers.values())
    desc = ", ".join(f"{name}: {n}" for name, n in browsers.items())
    return f"You have {total} open browser window{'s' if total != 1 else ''} ({desc})."


def _answer_downloads(snap: SystemAwarenessSnapshot) -> str | None:
    if snap.system is None:
        return "I don't have download info right now."
    files = getattr(snap.system, "files", None)
    if files is None:
        return "I don't have download info right now."
    downloads = getattr(files, "downloads_in_progress", [])
    if not downloads:
        return "Nothing is downloading right now."
    names = ", ".join(d.split("\\")[-1] for d in downloads)
    return f"Currently downloading: {names}."


def _answer_network(snap: SystemAwarenessSnapshot) -> str | None:
    net = snap.network
    if net is None:
        return "I don't have network info right now."
    if not net.connected:
        return "There's no active network connection right now."
    parts = ["Connected to the network"]
    if net.wifi_ssid:
        sig = f" (signal {net.wifi_signal_percent:.0f}%)" if net.wifi_signal_percent is not None else ""
        parts.append(f"via Wi-Fi '{net.wifi_ssid}'{sig}")
    down = _fmt_bytes_per_sec(net.download_bytes_per_sec)
    up = _fmt_bytes_per_sec(net.upload_bytes_per_sec)
    parts.append(f"down {down}, up {up}")
    return " ".join(parts) + "."


def _answer_storage(snap: SystemAwarenessSnapshot) -> str | None:
    if not snap.storage:
        return "I don't have storage info right now."
    lines = []
    for drive in snap.storage:
        lines.append(
            f"{drive.drive}: {drive.free_gb:.0f} GB free of {drive.total_gb:.0f} GB "
            f"({drive.percent:.0f}% used)"
        )
    return " ".join(lines) + "."


def _answer_cpu(snap: SystemAwarenessSnapshot) -> str | None:
    sys_info = snap.system
    if sys_info is None:
        return "I don't have CPU usage data right now."
    cpu = getattr(sys_info, "cpu_percent", None)
    if cpu is None:
        return "I don't have CPU usage data right now."
    return f"CPU usage is at {cpu:.0f}% right now."


def _answer_ram(snap: SystemAwarenessSnapshot) -> str | None:
    sys_info = snap.system
    if sys_info is None:
        return "I don't have memory usage data right now."
    ram = getattr(sys_info, "ram_percent", None)
    if ram is None:
        return "I don't have memory usage data right now."
    return f"RAM usage is at {ram:.0f}% right now."


def _answer_gpu(snap: SystemAwarenessSnapshot) -> str | None:
    sys_info = snap.system
    if sys_info is None:
        return "I don't have GPU usage data right now."
    gpu = getattr(sys_info, "gpu_percent", None)
    if gpu is None:
        return "I don't have GPU usage data right now."
    return f"GPU usage is at {gpu:.0f}% right now."


def _answer_media(snap: SystemAwarenessSnapshot) -> str | None:
    media = snap.media
    if media is None or not getattr(media, "title", None):
        return "Nothing is playing right now."
    title = media.title
    artist = media.artist
    if artist:
        return f"Now playing {title} by {artist}."
    return f"Now playing {title}."


def _answer_volume(snap: SystemAwarenessSnapshot) -> str | None:
    media = snap.media
    if media is None:
        return "I don't have volume info right now."
    volume = getattr(media, "volume", None)
    if volume is None:
        return "I don't have volume info right now."
    return f"Volume is at {volume * 100:.0f}%."


def _answer_mic(snap: SystemAwarenessSnapshot) -> str | None:
    media = snap.media
    if media is None:
        return "I don't have microphone info right now."
    mic = getattr(media, "mic_active", False)
    return "The microphone is currently active." if mic else "The microphone is not active."


def _answer_focused(snap: SystemAwarenessSnapshot) -> str | None:
    focused = snap.focused_window
    if not focused:
        return "No window appears focused right now."
    return f"The focused window is '{focused}'."


def _answer_started_today(snap: SystemAwarenessSnapshot) -> str | None:
    procs = snap.processes_started_today
    if not procs:
        return "I don't see any programs that started today."
    names = sorted({p.name for p in procs if p.name})[:10]
    if not names:
        return "I don't see any programs that started today."
    return "Programs started today: " + ", ".join(names) + "."


def _answer_bluetooth(snap: SystemAwarenessSnapshot) -> str | None:
    bt = snap.bluetooth
    if bt is None:
        return "I don't have Bluetooth info right now."
    if not bt.enabled:
        return "Bluetooth is off."
    if not bt.devices:
        return "Bluetooth is on, with no paired devices detected."
    return "Bluetooth is on. Devices: " + ", ".join(bt.devices[:8]) + "."


def _answer_usb(snap: SystemAwarenessSnapshot) -> str | None:
    if not snap.usb_devices:
        return "No USB devices detected."
    names = sorted({d.name for d in snap.usb_devices})[:10]
    return "USB devices: " + ", ".join(names) + "."


def _answer_printers(snap: SystemAwarenessSnapshot) -> str | None:
    if not snap.printers:
        return "No printers detected."
    lines = []
    for p in snap.printers:
        state = "online" if p.is_online else "offline"
        suffix = " (default)" if p.is_default else ""
        lines.append(f"{p.name} ({state}){suffix}")
    return "Printers: " + "; ".join(lines) + "."


def _answer_camera(snap: SystemAwarenessSnapshot) -> str | None:
    cam = snap.camera
    if cam is None:
        return "I don't have camera info right now."
    if not cam.present:
        return "No camera detected."
    state = "in use" if cam.in_use else "not in use"
    return f"Camera detected and {state}."


def _answer_services(snap: SystemAwarenessSnapshot) -> str | None:
    running = [s for s in snap.services if s.status.upper() == "RUNNING"]
    if not running:
        return "No running services found."
    names = sorted({s.name for s in running})[:10]
    return f"{len(running)} services are running. Examples: " + ", ".join(names) + "."


def _answer_recycle_bin(snap: SystemAwarenessSnapshot) -> str | None:
    rb = snap.recycle_bin
    if rb is None:
        return "I don't have recycle bin info right now."
    return (
        f"The recycle bin has {rb.item_count} item{'s' if rb.item_count != 1 else ''} "
        f"({rb.size_mb:.1f} MB)."
    )


def _answer_displays(snap: SystemAwarenessSnapshot) -> str | None:
    if not snap.displays:
        return "I don't have display info right now."
    desc = []
    for d in snap.displays:
        hz = f" @ {d.refresh_hz}Hz" if d.refresh_hz else ""
        primary = " (primary)" if d.is_primary else ""
        desc.append(f"{d.width}x{d.height}{hz}{primary}")
    return "Displays: " + ", ".join(desc) + "."


def _answer_notifications(snap: SystemAwarenessSnapshot) -> str | None:
    if not snap.notifications:
        return "No recent notifications."
    bodies = [n.body for n in snap.notifications[:5] if n.body]
    if not bodies:
        return "No recent notifications."
    return "Recent notifications: " + " | ".join(bodies) + "."


def _answer_media_sessions(snap: SystemAwarenessSnapshot) -> str | None:
    playing = [s for s in snap.media_sessions if s.is_playing]
    if not playing:
        return "No media sessions are actively playing."
    names = []
    for s in playing:
        label = s.title or s.app_name or "a media session"
        names.append(label)
    return "Active media: " + ", ".join(names) + "."


# ── Pattern → handler table ───────────────────────────────────────────

_RULES: list[tuple[str, Callable[[SystemAwarenessSnapshot], str | None]]] = [
    (r"battery|charge|power level", _answer_battery),
    (r"tab[s]?\b", _answer_tabs),
    (r"download", _answer_downloads),
    (r"wifi|wi-?fi|network|internet connection", _answer_network),
    (r"storage|disk space|free space|drive", _answer_storage),
    (r"cpu usage|cpu at|cpu%|processor usage", _answer_cpu),
    (r"ram usage|memory usage|ram at|memory at", _answer_ram),
    (r"which app.*(ram|memory)|most ram|most memory|top (ram|memory)|uses? the most (ram|memory)", _answer_top_ram),
    (r"which app.*cpu|most cpu|top cpu|uses? the most cpu", _answer_top_cpu),
    (r"gpu", _answer_gpu),
    (r"what.*playing|now playing|current song|what song", _answer_media),
    (r"volume|sound level", _answer_volume),
    (r"microphone|mic\b", _answer_mic),
    (r"which window|active window|focused window|what window is", _answer_focused),
    (r"started today|programs started|opened today|launched today", _answer_started_today),
    (r"bluetooth", _answer_bluetooth),
    (r"usb", _answer_usb),
    (r"printer", _answer_printers),
    (r"camera|webcam", _answer_camera),
    (r"service(s)? running|running service", _answer_services),
    (r"recycle bin|deleted items", _answer_recycle_bin),
    (r"display|monitor|screen resolution", _answer_displays),
    (r"notification", _answer_notifications),
    (r"media session|what.*media", _answer_media_sessions),
]

# Direct current-tab browser commands ("open current tab", "use current
# tab", "in the current tab", ...) are ACTIONS on the active tab, not
# questions about window counts. They must fall through to the browser
# handler, so they are excluded here before any rule can match.
_CURRENT_TAB_ACTION = re.compile(
    r"\b(use\s+current|current\s+tab|this\s+tab|current\s+page)\b",
    re.IGNORECASE,
)

# Question stems that must co-occur to avoid answering a plain action command.
_QUESTION_HINTS = re.compile(
    r"(what|how|which|how many|is there|are there|do you|can you|show me|"
    r"tell me|check|what's|whats|is |are |current|right now|status|%|left|"
    r"running|open|using|playing|detected|connected|at)\b",
    re.IGNORECASE,
)


def answer(snapshot: SystemAwarenessSnapshot, text: str) -> str | None:
    """Return an instant answer for ``text``, or ``None`` when unsure.

    Only answers questions (must contain a question hint) that map to a
    known awareness domain.  Plain action commands like "open chrome"
    return ``None`` so the normal pipeline handles them.
    """
    if snapshot is None or not text or not text.strip():
        return None
    lowered = text.casefold().strip()
    # A direct current-tab command ("open current tab", "use current tab",
    # "in the current tab", ...) operates on the active browser tab — it is
    # never a request for a browser-window count.
    if _CURRENT_TAB_ACTION.search(lowered):
        return None
    if not _QUESTION_HINTS.search(lowered):
        return None

    best: str | None = None
    for pattern, handler in _RULES:
        if re.search(pattern, lowered):
            result = handler(snapshot)
            if result is not None:
                best = result
    return best


def describe(snapshot: SystemAwarenessSnapshot, max_lines: int = 12) -> str:
    """Render a compact human-readable summary for LLM grounding."""
    if snapshot is None:
        return "(no system awareness data)"
    lines: list[str] = []
    if snapshot.focused_window:
        lines.append(f"focused window: {snapshot.focused_window}")
    if snapshot.network:
        net = snapshot.network
        if net.connected:
            lines.append(
                f"network: connected{f' (Wi-Fi {net.wifi_ssid})' if net.wifi_ssid else ''}"
            )
        else:
            lines.append("network: disconnected")
    if snapshot.battery and snapshot.battery.present:
        b = snapshot.battery
        lines.append(f"battery: {b.percent:.0f}%{' charging' if b.charging else ''}")
    if snapshot.system is not None:
        sys_info = snapshot.system
        cpu = getattr(sys_info, "cpu_percent", None)
        ram = getattr(sys_info, "ram_percent", None)
        if cpu is not None:
            lines.append(f"cpu: {cpu:.0f}%")
        if ram is not None:
            lines.append(f"ram: {ram:.0f}%")
    top = snapshot.top_ram_process()
    if top is not None and top.memory_mb > 0:
        lines.append(f"top RAM: {top.name} ({top.memory_mb:.0f} MB)")
    if snapshot.processes_started_today:
        names = sorted({p.name for p in snapshot.processes_started_today if p.name})
        lines.append("started today: " + ", ".join(names[:8]))
    if snapshot.storage:
        lines.append("storage: " + "; ".join(
            f"{s.drive} {s.free_gb:.0f}G free" for s in snapshot.storage
        ))
    if not lines:
        return "(no system awareness data)"
    return "\n".join(lines[:max_lines])
