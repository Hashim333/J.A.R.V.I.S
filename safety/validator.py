"""
safety/validator.py

Validation functions for file paths, application existence, and
parameter safety.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Paths that should never be deleted / moved / renamed
_PROTECTED_PATHS = frozenset({
    p.lower()
    for p in [
        os.environ.get("WINDIR", r"C:\Windows"),
        os.environ.get("SYSTEMROOT", r"C:\Windows"),
        os.path.expandvars(r"%PROGRAMFILES%"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%"),
    ]
    if p
})

# Dangerous patterns that should never be executed
_DANGEROUS_COMMANDS = frozenset({
    "format", "fdisk", "diskpart", "del /f", "rmdir /s",
    "rd /s", "rm -rf", ":(){ :|:& };:", "dd if=",
})

# Characters that shouldn't appear in safe file paths
_PATH_TRAVERSAL = re.compile(r"(?:\.\./|\.\\)")


def validate_file_path(path: str, action: str = "") -> dict[str, Any]:
    """Validate a file path for safety and existence.

    Returns dict with ``valid`` (bool), ``exists`` (bool),
    ``resolved`` (str), and ``message`` (str).
    """
    if not path or not path.strip():
        return {"valid": False, "exists": False, "resolved": "", "message": "Path is empty"}

    try:
        resolved = str(Path(path).resolve())
    except (OSError, ValueError) as exc:
        return {"valid": False, "exists": False, "resolved": "", "message": f"Cannot resolve path: {exc}"}

    # Check for path traversal
    if _PATH_TRAVERSAL.search(path):
        return {"valid": False, "exists": False, "resolved": resolved, "message": "Path traversal detected"}

    # Check against protected system paths
    resolved_lower = resolved.lower()
    for protected in _PROTECTED_PATHS:
        if protected and resolved_lower.startswith(protected):
            return {"valid": False, "exists": False, "resolved": resolved, "message": f"Path is in a protected system location: {protected}"}

    exists = os.path.isfile(resolved) or os.path.isdir(resolved)
    return {"valid": True, "exists": exists, "resolved": resolved, "message": ""}


def validate_app_exists(app_name: str) -> dict[str, Any]:
    """Check whether an application name is likely to exist on the system.

    Uses the ApplicationRegistry lookup; returns dict with
    ``valid`` (bool), ``exists`` (bool), and ``message`` (str).
    """
    if not app_name or not app_name.strip():
        return {"valid": False, "exists": False, "message": "App name is empty"}

    try:
        from automation.application_registry import ApplicationRegistry
        registry = ApplicationRegistry()
        info = registry.lookup(app_name)
        exe_path = getattr(info, "executable", None) or getattr(info, "path", None)
        if info is not None and exe_path and os.path.isfile(exe_path):
            return {"valid": True, "exists": True, "message": f"Found at {exe_path}"}
        return {"valid": True, "exists": False, "message": f"No installation found for {app_name!r}"}
    except Exception as exc:
        logger.warning("App validation failed for %r: %s", app_name, exc)
        return {"valid": True, "exists": True, "message": "Unable to verify; allowing execution"}


def validate_url(url: str) -> dict[str, Any]:
    """Validate a URL string for safety and well-formedness.

    Returns dict with ``valid`` (bool) and ``message`` (str).
    """
    if not url or not url.strip():
        return {"valid": False, "message": "URL is empty"}

    from urllib.parse import urlparse

    url = url.strip()

    # Must start with http:// or https://
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"valid": False, "message": "URL must start with http:// or https://"}

    try:
        parsed = urlparse(url)
    except Exception as exc:
        return {"valid": False, "message": f"Cannot parse URL: {exc}"}

    if not parsed.netloc:
        return {"valid": False, "message": "URL has no host component"}

    # Reject IP-based URLs for safety (prevent SSRF-like scenarios)
    import re
    ip_pattern = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")
    if ip_pattern.match(parsed.hostname or ""):
        return {"valid": False, "message": "IP-based URLs are not allowed for safety"}

    return {"valid": True, "message": ""}


def validate_parameters(action: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Sanitize and validate parameters for dangerous content."""
    dangerous = []
    for key, value in parameters.items():
        if isinstance(value, str):
            value_lower = value.casefold()
            for cmd in _DANGEROUS_COMMANDS:
                if cmd in value_lower:
                    dangerous.append(f"Parameter {key!r} contains dangerous command pattern: {cmd!r}")
    if dangerous:
        return {"valid": False, "issues": dangerous, "message": "; ".join(dangerous)}
    return {"valid": True, "issues": [], "message": ""}
