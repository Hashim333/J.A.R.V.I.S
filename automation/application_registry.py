"""
automation/application_registry.py

Dynamic Windows application discovery registry.

Scans multiple sources to discover installed applications, builds a
searchable index with fuzzy matching, and provides lookup/search APIs.

Sources:
  - Start Menu shortcuts (%APPDATA%, %PROGRAMDATA%)
  - Desktop shortcuts (%USERPROFILE%, %PUBLIC%)
  - Program Files (x64, x86)
  - WindowsApps
  - Registry App Paths (HKLM)
  - PATH directories
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
import winreg
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ApplicationInfo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApplicationInfo:
    """Canonical representation of an installed application."""

    canonical_name: str
    aliases: frozenset[str]
    executable: str
    install_path: str
    launch_method: str
    icon_path: str | None = None
    _process_name: str | None = field(default=None, repr=False)

    @property
    def process_name(self) -> str:
        if self._process_name is not None:
            return self._process_name
        return os.path.basename(self.executable)


# ---------------------------------------------------------------------------
# Alias generator
# ---------------------------------------------------------------------------

_ACRONYM_SPLIT = re.compile(r"[^a-zA-Z0-9]")


def _generate_aliases(display_name: str, executable: str) -> frozenset[str]:
    """Generate a set of searchable aliases from a display name + executable.

    Strategies:
      1. Lowercased display name
      2. Each token of the display name
      3. Acronym (first letter of each token)
      4. Executable filename stem
      5. Display name with common suffixes stripped (".exe", ".lnk")
    """
    aliases: set[str] = set()

    name = display_name.strip()
    if not name:
        name = Path(executable).stem

    # Lowercased full name
    lower = name.casefold()
    aliases.add(lower)

    # Remove file extensions if present
    for ext in (".exe", ".lnk"):
        if lower.endswith(ext):
            no_ext = lower[: -len(ext)]
            aliases.add(no_ext)
            break

    # Tokens
    tokens = [t for t in _ACRONYM_SPLIT.split(lower) if t]
    for t in tokens:
        if len(t) > 1:
            aliases.add(t)

    # Acronym
    if len(tokens) > 1:
        acronym = "".join(t[0] for t in tokens if t)
        if acronym:
            aliases.add(acronym)

    # Executable stem
    exe_stem = Path(executable).stem.casefold()
    aliases.add(exe_stem)

    return frozenset(aliases)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> set[str]:
    return set(_ACRONYM_SPLIT.split(text.casefold())) - {""}


def _score_match(query: str, info: ApplicationInfo) -> float:
    """Return a similarity score in [0.0, 1.0] between query and app.

    Scoring (before source boost):
      1.0  – Exact match on canonical name or any alias
      0.9  – All query tokens appear as complete tokens in the app
      0.7  – Query string is a prefix of the canonical name
      0.6  – Query string is a substring of an alias
      0.5  – One query token matches a complete app token
      0.3  – Query is a prefix of an app token
      0.0  – No meaningful match
    """
    q = query.strip().casefold()
    if not q or not info.canonical_name:
        return 0.0

    # -- Exact matches --
    if q == info.canonical_name.casefold() or q in info.aliases:
        return 1.0

    query_tokens = _tokenize(q)
    name_tokens = _tokenize(info.canonical_name)

    # Build a set of all tokens from all aliases
    all_alias_tokens: set[str] = set()
    for a in info.aliases:
        all_alias_tokens |= _tokenize(a)

    if not query_tokens or (not name_tokens and not all_alias_tokens):
        return 0.0

    # -- All query tokens appear as complete tokens in name or aliases --
    all_tokens = name_tokens | all_alias_tokens
    if query_tokens <= all_tokens:
        return _boost_by_source(0.9, info.launch_method)

    # -- Query is a prefix of the canonical name --
    if len(q) >= 3 and info.canonical_name.casefold().startswith(q):
        return _boost_by_source(0.7, info.launch_method)

    # -- Substring match against any alias --
    for alias in info.aliases:
        if alias in q or q in alias:
            if len(alias) < 4:
                continue
            return _boost_by_source(0.6, info.launch_method)

    # -- Each query token that matches a complete app token --
    overlap = query_tokens & all_tokens
    if overlap:
        ratio = len(overlap) / len(query_tokens)
        return _boost_by_source(0.5 * ratio, info.launch_method)

    # -- Query is a prefix of any complete app token --
    for qt in query_tokens:
        if len(qt) < 4:
            continue
        for at in all_tokens:
            if len(at) < 4:
                continue
            if at.startswith(qt) or qt.startswith(at):
                return _boost_by_source(0.3, info.launch_method)

    return 0.0


_SOURCE_PRIORITY: dict[str, float] = {
    "shell:start_menu": 0.10,
    "shell:desktop": 0.05,
    "registry": 0.03,
    "program_files": 0.02,
    "windows_apps": 0.01,
    "path": 0.0,
}


def _boost_by_source(score: float, source: str) -> float:
    """Apply a small boost based on discovery source authority."""
    boost = _SOURCE_PRIORITY.get(source, 0.0)
    return min(1.0, score + boost)





# ---------------------------------------------------------------------------
# Well-known generic aliases (small set, not app-specific)
# ---------------------------------------------------------------------------

_GENERIC_ALIASES: dict[str, str] = {
    "browser": "google chrome",
    "my browser": "google chrome",
    "web browser": "google chrome",
    "terminal": "windows terminal",
    "shell": "windows terminal",
    "editor": "notepad",
    "text editor": "notepad",
}

# Well-known app abbreviations that cannot be algorithmically derived from
# the canonical display name.  This small set (~20 entries) covers the most
# common user queries for popular applications.  It is NOT a comprehensive
# app list — the dynamic discovery provides that.
_WELL_KNOWN_ALIASES: dict[str, str] = {
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "code editor": "Visual Studio Code",
    "outlook": "Microsoft Outlook",
    "steam": "Steam",
    "discord": "Discord",
    "spotify": "Spotify",
    "slack": "Slack",
    "zoom": "Zoom",
    "obsidian": "Obsidian",
    "notepad++": "Notepad++",
    "vlc": "VLC media player",
    "winrar": "WinRAR",
    "7zip": "7-Zip",
    "seven zip": "7-Zip",
    "telegram": "Telegram Desktop",
    "whatsapp": "WhatsApp",
    "thunderbird": "Mozilla Thunderbird",
    "libreoffice": "LibreOffice",
    "gimp": "GIMP",
    "blender": "Blender",
    "unity": "Unity Hub",
    "docker": "Docker Desktop",
    "postman": "Postman",
    "figma": "Figma",
    "google chrome": "chrome",
    "chrome browser": "chrome",
    "microsoft edge": "msedge",
    "edge browser": "msedge",
    "internet explorer": "iexplore",
    "microsoft word": "Word",
    "microsoft excel": "Excel",
    "microsoft powerpoint": "PowerPoint",
    "microsoft outlook": "Outlook",
    # Security / pentest tools
    "nmap": "Nmap",
    "zenmap": "Zenmap",
    "wireshark": "Wireshark",
    "tshark": "TShark",
    "burp": "Burp Suite",
    "burpsuite": "Burp Suite",
    "metasploit": "Metasploit",
    "msfconsole": "Metasploit",
    "nessus": "Nessus",
    "openvas": "OpenVAS",
    "nikto": "Nikto",
    "gobuster": "GoBuster",
    "ffuf": "FFUF",
    "sqlmap": "sqlmap",
    "hydra": "Hydra",
    "john": "John the Ripper",
    "johnny": "Johnny",
    "aircrack": "Aircrack-ng",
    "aircrack ng": "Aircrack-ng",
    "netcat": "Netcat",
    "nc": "Netcat",
    "ncat": "Ncat",
    "masscan": "Masscan",
    "dirb": "DIRB",
    "dirbuster": "DirBuster",
    "zap": "ZAP",
    "owasp zap": "ZAP",
    "beef": "BeEF",
    "bettercap": "BetterCap",
    "responder": "Responder",
    "impacket": "Impacket",
    "bloodhound": "BloodHound",
    "crackmapexec": "CrackMapExec",
    "netexec": "NetExec",
    "nxc": "NetExec",
    "proxychains": "Proxychains",
    "weevely": "Weevely",
    "pwncat": "PwnCat",
    "ligolo": "Ligolo-ng",
    "chisel": "Chisel",
    "socat": "Socat",
    "mimikatz": "Mimikatz",
    "evil winrm": "Evil-WinRM",
    "evilwinrm": "Evil-WinRM",
    "certipy": "Certipy",
    "enum4linux": "Enum4linux",
    "smbclient": "SMBClient",
    "smbmap": "SMBMap",
    "ldapdomaindump": "LDAPDomainDump",
    "ldapsearch": "LDAPSearch",
}

# System applications that are included with Windows and may not appear
# in Start Menu / Program Files / Registry scans.
_SYSTEM_APPS: dict[str, dict[str, str]] = {
    "notepad": {
        "executable": "notepad.exe",
        "process_name": "notepad.exe",
    },
    "calculator": {
        "executable": "calc.exe",
        "process_name": "CalculatorApp.exe",
    },
    "calc": {
        "executable": "calc.exe",
        "process_name": "CalculatorApp.exe",
    },
    "paint": {
        "executable": "mspaint.exe",
        "process_name": "mspaint.exe",
    },
    "cmd": {
        "executable": "cmd.exe",
        "process_name": "cmd.exe",
    },
    "command prompt": {
        "executable": "cmd.exe",
        "process_name": "cmd.exe",
    },
    "powershell": {
        "executable": "powershell.exe",
        "process_name": "powershell.exe",
    },
    "terminal": {
        "executable": "powershell.exe",
        "process_name": "powershell.exe",
    },
    "file explorer": {
        "executable": "explorer.exe",
        "process_name": "explorer.exe",
    },
    "explorer": {
        "executable": "explorer.exe",
        "process_name": "explorer.exe",
    },
    "snipping tool": {
        "executable": "SnippingTool.exe",
        "process_name": "SnippingTool.exe",
    },
    "wordpad": {
        "executable": "write.exe",
        "process_name": "write.exe",
    },
    # Security / pentest tools (common install paths)
    "nmap": {
        "executable": "nmap.exe",
        "process_name": "nmap.exe",
    },
    "wireshark": {
        "executable": "wireshark.exe",
        "process_name": "wireshark.exe",
    },
    "burp suite": {
        "executable": "burpsuite.exe",
        "process_name": "burpsuite.exe",
    },
    "metasploit": {
        "executable": "msfconsole.bat",
        "process_name": "msfconsole.bat",
    },
}


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def _resolve_lnks_batch(lnk_paths: list[Path]) -> dict[str, str]:
    """Resolve multiple .lnk files to their targets using PowerShell.

    Uses a temp file to hold the script to avoid Windows command line
    length limits (~32767 chars).

    Returns a dict mapping display name -> target executable.
    """
    if not lnk_paths:
        return {}

    ps_script_lines = [
        "$shell = New-Object -ComObject WScript.Shell",
    ]
    for lnk in lnk_paths:
        escaped = str(lnk).replace("'", "''")
        ps_script_lines.append(
            f"try {{ $target = $shell.CreateShortcut('{escaped}').TargetPath; "
            f"if ($target -and (Test-Path $target)) {{ "
            f"Write-Output \"{escaped}|$target\" }} }} catch {{ }}"
        )

    script = "; ".join(ps_script_lines)

    # Write script to a temp file to avoid command-line length limits
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False)
    try:
        tmp.write(script)
        tmp.close()
        result = subprocess.run(
            ["powershell", "-NoProfile", "-File", tmp.name],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception:
        return {}
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    mapping: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if "|" in line:
            lnk_path, target = line.split("|", 1)
            target = target.strip()
            if target and os.path.isfile(target) and target.casefold().endswith(".exe"):
                name = Path(lnk_path).stem
                mapping[name] = target
    return mapping


def _scan_start_menu() -> dict[str, ApplicationInfo]:
    """Scan Start Menu shortcuts for installed applications."""
    apps: dict[str, ApplicationInfo] = {}
    apdata = os.environ.get("APPDATA")
    progdata = os.environ.get("PROGRAMDATA")

    roots: list[Path] = []
    if apdata:
        roots.append(Path(apdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if progdata:
        roots.append(Path(progdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")

    all_lnks: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for lnk in root.rglob("*.lnk"):
                all_lnks.append(lnk)
        except Exception:
            continue

    if not all_lnks:
        return apps

    resolved = _resolve_lnks_batch(all_lnks)
    for name, target in resolved.items():
        _register_from_exe(name, target, "shell:start_menu", apps)

    return apps


def _scan_desktop() -> dict[str, ApplicationInfo]:
    """Scan Desktop shortcuts."""
    apps: dict[str, ApplicationInfo] = {}
    user_home = Path.home()
    public = Path(os.environ.get("PUBLIC", ""))

    roots: list[Path] = []
    desktop = user_home / "Desktop"
    if desktop.is_dir():
        roots.append(desktop)
    if public:
        pub_desktop = public / "Desktop"
        if pub_desktop.is_dir():
            roots.append(pub_desktop)

    all_lnks: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for lnk in root.glob("*.lnk"):
                all_lnks.append(lnk)
        except Exception:
            continue

    if not all_lnks:
        return apps

    resolved = _resolve_lnks_batch(all_lnks)
    for name, target in resolved.items():
        _register_from_exe(name, target, "shell:desktop", apps)

    return apps


def _scan_program_files() -> dict[str, ApplicationInfo]:
    """Scan Program Files directories for top-level executables."""
    apps: dict[str, ApplicationInfo] = {}
    roots: list[Path] = []

    pf = os.environ.get("ProgramFiles")
    if pf:
        roots.append(Path(pf))
    pf86 = os.environ.get("ProgramFiles(x86)")
    if pf86:
        roots.append(Path(pf86))

    for root in roots:
        if not root.is_dir():
            continue
        try:
            for vendor_dir in root.iterdir():
                if not vendor_dir.is_dir():
                    continue
                # Look for main executables at depth 2 (vendor/app.exe)
                for exe in vendor_dir.glob("*.exe"):
                    _register_from_exe(exe.stem, str(exe), "program_files", apps)
                # Also check one subdirectory level (vendor/app/app.exe)
                for sub in vendor_dir.iterdir():
                    if sub.is_dir():
                        for exe in sub.glob("*.exe"):
                            _register_from_exe(exe.stem, str(exe), "program_files", apps)
        except Exception:
            continue

    return apps


def _scan_windows_apps() -> dict[str, ApplicationInfo]:
    """Scan WindowsApps directory for packaged applications."""
    apps: dict[str, ApplicationInfo] = {}
    windows_apps = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "WindowsApps"

    if not windows_apps.is_dir():
        return apps

    try:
        for app_dir in windows_apps.iterdir():
            if not app_dir.is_dir():
                continue
            # Look for appx manifests or main executables
            for exe in app_dir.glob("*.exe"):
                _register_from_exe(exe.stem, str(exe), "windows_apps", apps)
    except Exception:
        pass

    return apps


def _scan_registry() -> dict[str, ApplicationInfo]:
    """Scan HKLM Software\Microsoft\Windows\CurrentVersion\App Paths."""
    apps: dict[str, ApplicationInfo] = {}
    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as base_key:
            i = 0
            while True:
                try:
                    sub_key_name = winreg.EnumKey(base_key, i)
                    i += 1
                except OSError:
                    break

                exe_name = sub_key_name
                sub_key_path = f"{key_path}\\{sub_key_name}"
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub_key_path) as sk:
                        try:
                            default_value, _ = winreg.QueryValueEx(sk, "")
                            if default_value and os.path.isfile(default_value):
                                stem = Path(exe_name).stem
                                _register_from_exe(stem, default_value, "registry", apps)
                        except OSError:
                            pass
                except Exception:
                    continue
    except Exception:
        pass

    return apps


def _is_valid_app_stem(stem: str) -> bool:
    """Check if a PATH executable stem looks like a real application name.

    Filters out:
      - Very short names (< 3 chars)
      - Names with underscores (likely dev tools or auto-generated)
      - Names containing numbers mixed with lowercase (build artifacts)
      - Known system utilities
    """
    if len(stem) < 3:
        return False
    if stem in _SKIP_EXES:
        return False
    # Skip names with underscores (internal dev utilities)
    if "_" in stem:
        return False
    # Skip names that are purely hex or numeric
    if all(c in "0123456789abcdef-" for c in stem):
        return False
    return True


def _scan_path() -> dict[str, ApplicationInfo]:
    """Scan PATH directories for .exe files."""
    apps: dict[str, ApplicationInfo] = {}
    path_dirs = os.environ.get("PATH", "").split(";")

    for path_dir in path_dirs:
        p = Path(path_dir)
        if not p.is_dir():
            continue
        try:
            for exe in p.glob("*.exe"):
                stem = exe.stem.casefold()
                if not _is_valid_app_stem(stem):
                    continue
                _register_from_exe(exe.stem, str(exe), "path", apps)
        except Exception:
            continue

    return apps


# Executable names to skip in PATH scan (system utilities, not end-user apps)
_SKIP_EXES: frozenset[str] = frozenset(
    {
        "find", "findstr", "sort", "more", "tree", "where", "which",
        "xcopy", "robocopy", "attrib", "cacls", "icacls",
        "reg", "regedit", "msconfig", "taskmgr", "tasklist", "taskkill",
        "schtasks", "shutdown", "logoff", "tsdiscon",
        "ping", "tracert", "pathping", "nslookup", "netstat", "nbtstat",
        "ipconfig", "getmac", "hostname", "systeminfo",
        "sfc", "chkdsk", "diskpart", "diskmgmt", "cleanmgr", "defrag",
        "notepad", "calc", "mspaint", "cmd", "powershell",
        "explorer", "msedge", "winword", "excel", "powerpnt", "outlook",
        "control", "msra", "mstsc", "winver", "eudcedit",
        "magnify", "narrator", "osk", "snippingtool", "stepsrecorder",
        "write", "wordpad", "paint", "paintdotnet",
    }
)


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------


def _register_from_exe(
    display_name: str,
    executable: str,
    source: str,
    registry: dict[str, ApplicationInfo],
) -> None:
    """Register an executable as an ApplicationInfo if not already present."""
    if not executable or not os.path.isfile(executable):
        return
    exe_lower = executable.casefold()
    # Deduplicate by executable path
    for existing in registry.values():
        if existing.executable.casefold() == exe_lower:
            return

    install_path = os.path.dirname(executable)
    aliases = _generate_aliases(display_name, executable)

    info = ApplicationInfo(
        canonical_name=display_name,
        aliases=aliases,
        executable=executable,
        install_path=install_path,
        launch_method=source,
    )

    # Use canonical name as key, deduplicating
    key = display_name.casefold()
    # If we already have an entry with a different executable, prefer the
    # one from a more authoritative source
    existing = registry.get(key)
    if existing:
        priority = {"shell:start_menu": 5, "shell:desktop": 4, "registry": 3,
                     "program_files": 2, "windows_apps": 1, "path": 0}
        if priority.get(source, 0) > priority.get(existing.launch_method, 0):
            registry[key] = info
    else:
        registry[key] = info


# ---------------------------------------------------------------------------
# ApplicationRegistry
# ---------------------------------------------------------------------------


class ApplicationRegistry:
    """
    Discovers, caches, and searches installed Windows applications.

    Usage:
        reg = ApplicationRegistry()  # discovers on init
        app = reg.lookup("chrome")
        apps = reg.search("code")
        reg.refresh()
    """

    def __init__(self, auto_discover: bool = True) -> None:
        self._apps: dict[str, ApplicationInfo] = {}
        self._canonical_names: list[str] = []
        self._discovered_at: float | None = None
        if auto_discover:
            self.discover()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover(self) -> int:
        """Scan all sources and rebuild the application index.

        Returns the number of unique applications discovered.
        """
        t0 = time.monotonic()
        combined: dict[str, ApplicationInfo] = {}

        scanners = [
            ("Start Menu", _scan_start_menu),
            ("Desktop", _scan_desktop),
            ("Program Files", _scan_program_files),
            ("WindowsApps", _scan_windows_apps),
            ("Registry", _scan_registry),
            ("PATH", _scan_path),
        ]

        for label, scanner in scanners:
            t1 = time.monotonic()
            try:
                found = scanner()
                elapsed = time.monotonic() - t1
                logger.info("ApplicationRegistry: %s scan found %d apps in %.2fs",
                            label, len(found), elapsed)
                for key, info in found.items():
                    if key not in combined:
                        combined[key] = info
            except Exception as exc:
                logger.warning("ApplicationRegistry: %s scan failed: %s", label, exc)

        self._apps = combined
        self._canonical_names = sorted(combined.keys())
        self._discovered_at = time.monotonic()

        # Seed well-known apps that weren't discovered
        self._seed_well_known(combined)

        self._apps = combined
        self._canonical_names = sorted(combined.keys())
        self._discovered_at = time.monotonic()

        elapsed = time.monotonic() - t0
        count = len(combined)
        logger.info("ApplicationRegistry: discovered %d apps in %.2fs", count, elapsed)
        return count

    @staticmethod
    def _seed_well_known(combined: dict[str, ApplicationInfo]) -> None:
        """Add well-known apps that were not found by scanning."""
        for alias_key, canonical_name in _WELL_KNOWN_ALIASES.items():
            ckey = canonical_name.casefold()
            if ckey in combined:
                continue
            # Check if any existing alias covers it
            already_covered = False
            for info in combined.values():
                if canonical_name.casefold() in info.aliases:
                    already_covered = True
                    break
            if already_covered:
                continue
            # Try to find executable via PATH
            exe_name = alias_key
            executable = shutil.which(exe_name) or shutil.which(f"{exe_name}.exe") or ""
            if not executable:
                # Try common patterns
                for pat in (canonical_name, alias_key):
                    pat_exe = shutil.which(pat) or shutil.which(f"{pat}.exe")
                    if pat_exe:
                        executable = pat_exe
                        break
            install_path = os.path.dirname(executable) if executable else ""
            aliases = _generate_aliases(canonical_name, executable or alias_key)
            info = ApplicationInfo(
                canonical_name=canonical_name,
                aliases=aliases,
                executable=executable,
                install_path=install_path,
                launch_method="well_known" if executable else "well_known_stub",
            )
            combined[ckey] = info

    def refresh(self) -> int:
        """Force a full re-scan.  Returns the number of apps discovered."""
        return self.discover()

    def lookup(self, name: str) -> ApplicationInfo | None:
        """Find the best match for a user-provided application name.

        Priority order:
          1. Exact canonical name match in discovered apps
          2. Exact alias match in discovered apps
          3. System app (notepad, calculator, etc.)
          4. Well-known alias (vscode → Visual Studio Code)
          5. Generic role alias (browser → Google Chrome)
          6. Fuzzy match in discovered apps (score >= 0.5)
          7. None
        """
        key = name.strip().casefold()
        if not key:
            return None

        # 1. Exact canonical name match
        for info in self._apps.values():
            if info.canonical_name.casefold() == key:
                return info

        # 2. Generic role alias (browser → google chrome, terminal → windows terminal)
        #    Checked before system/alias matches so "browser" opens Chrome not DB Browser.
        generic_canonical = _GENERIC_ALIASES.get(key)
        if generic_canonical:
            for info in self._apps.values():
                if info.canonical_name.casefold() == generic_canonical.casefold():
                    return info
            # Recurse with resolved name — may hit well-known alias or exact match
            recursive = self.lookup(generic_canonical)
            if recursive is not None:
                return recursive

        # 3. System apps (notepad, calculator, paint) — checked before
        #    alias matches so that "notepad" returns system Notepad
        #    rather than "Notepad++".
        if key in _SYSTEM_APPS:
            return self._system_app_info(key)

        # 4. Exact alias match — checked after generic/system so
        #    "browser" (alias of DB Browser) returns generic Google Chrome instead.
        for info in self._apps.values():
            if key in info.aliases:
                return info

        # 5. Well-known alias (vscode, vs code, etc.)
        well_known_canonical = _WELL_KNOWN_ALIASES.get(key)
        if well_known_canonical:
            for info in self._apps.values():
                if info.canonical_name.casefold() == well_known_canonical.casefold():
                    return info
            # Not discovered — try as system app
            wk_key = well_known_canonical.casefold()
            if wk_key in _SYSTEM_APPS:
                return self._system_app_info(wk_key)
            # Create a stub
            return self._system_app_info(key)

        # 6. Fuzzy match in discovered apps
        matches = self.search(key, threshold=0.5)
        if len(matches) == 1:
            return matches[0][0]
        if len(matches) >= 2:
            best_score = matches[0][1]
            second_score = matches[1][1]
            # If the top match is clearly better, return it
            if best_score - second_score >= 0.2:
                return matches[0][0]
            return None  # ambiguous

        return None

    def _system_app_info(self, key: str) -> ApplicationInfo | None:
        """Create an ApplicationInfo for a system app (notepad, calc, etc.)."""
        info = _SYSTEM_APPS.get(key)
        if not info:
            return None
        exe = shutil.which(info["executable"])
        if not exe:
            exe = info["executable"]
        # Some system apps (e.g. Calculator on Win10+) are UWP/MSIX packaged.
        # The launch executable (e.g. calc.exe) is a stub that exits after
        # spawning the actual process (e.g. CalculatorApp.exe).  Allow an
        # explicit process_name override so close/focus operations match
        # the real running process.
        process_name_override = info.get("process_name")
        return ApplicationInfo(
            canonical_name=key.title(),
            aliases=frozenset({key, (process_name_override or os.path.basename(exe)).replace(".exe", "")}),
            executable=exe,
            install_path=os.path.dirname(exe) if exe else "",
            launch_method="system",
            _process_name=process_name_override,
        )

    def search(self, name: str, threshold: float = 0.0) -> list[tuple[ApplicationInfo, float]]:
        """Search for all applications matching a name, sorted by score descending.

        Returns list of (ApplicationInfo, score) tuples.
        """
        if not name or not name.strip():
            return []

        scored: list[tuple[ApplicationInfo, float]] = []
        for info in self._apps.values():
            score = _score_match(name, info)
            if score >= threshold:
                scored.append((info, score))

        scored.sort(key=lambda x: (-x[1], x[0].canonical_name))
        return scored

    def list_applications(self) -> list[ApplicationInfo]:
        """Return all discovered applications sorted by canonical name."""
        return sorted(self._apps.values(), key=lambda a: a.canonical_name.casefold())

    def get_by_executable(self, executable: str) -> ApplicationInfo | None:
        """Find an application by its executable path."""
        exe_lower = executable.strip().casefold()
        for info in self._apps.values():
            if info.executable.casefold() == exe_lower:
                return info
        return None

    def get_by_canonical_name(self, name: str) -> ApplicationInfo | None:
        """Find an application by its exact canonical name (case-insensitive)."""
        key = name.strip().casefold()
        return self._apps.get(key)

    @property
    def discovered_at(self) -> float | None:
        return self._discovered_at

    @property
    def count(self) -> int:
        return len(self._apps)
