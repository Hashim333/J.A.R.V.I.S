"""
automation/file_ops.py

Core file operations: search, open, copy, move, rename, delete,
and open containing folder.  All functions return a result dict with
at least "success" and "message" keys.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Search folders (ordered by relevance)
# ---------------------------------------------------------------------------

_COMMON_SEARCH_FOLDERS: list[str] | None = None


def _get_known_folders() -> dict[str, str]:
    """Return a mapping of well-known CSIDL folder names to their paths."""
    import ctypes.wintypes

    # CSIDL constants
    CSIDL_PERSONAL = 0x0005       # Documents
    CSIDL_DOWNLOADS = 0x0020
    CSIDL_DESKTOP = 0x0010
    CSIDL_MYPICTURES = 0x0027
    CSIDL_MYVIDEO = 0x000E
    CSIDL_MYMUSIC = 0x000D
    CSIDL_APPDATA = 0x001A
    CSIDL_LOCAL_APPDATA = 0x001C
    CSIDL_PROGRAM_FILES = 0x0026
    CSIDL_PROGRAM_FILES_COMMON = 0x002B

    def _get_folder(csidl: int) -> str:
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
        return buf.value

    return {
        "desktop": _get_folder(CSIDL_DESKTOP),
        "documents": _get_folder(CSIDL_PERSONAL),
        "downloads": _get_folder(CSIDL_DOWNLOADS),
        "pictures": _get_folder(CSIDL_MYPICTURES),
        "videos": _get_folder(CSIDL_MYVIDEO),
        "music": _get_folder(CSIDL_MYMUSIC),
        "appdata": _get_folder(CSIDL_APPDATA),
        "localappdata": _get_folder(CSIDL_LOCAL_APPDATA),
    }


def get_common_search_folders() -> list[str]:
    """Return list of common user folders to search for files."""
    global _COMMON_SEARCH_FOLDERS
    if _COMMON_SEARCH_FOLDERS is not None:
        return _COMMON_SEARCH_FOLDERS

    known = _get_known_folders()
    folders: list[str] = []
    for key in ("desktop", "documents", "downloads", "pictures", "videos", "music"):
        if key in known and os.path.isdir(known[key]):
            folders.append(known[key])
    _COMMON_SEARCH_FOLDERS = folders
    logger.info("Common search folders: %s", folders)
    return folders


# ---------------------------------------------------------------------------
# File search
# ---------------------------------------------------------------------------

_FILE_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".rtf", ".csv",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".mp4", ".avi", ".mkv", ".mov", ".wmv",
    ".mp3", ".wav", ".flac", ".aac",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".html", ".htm", ".css", ".js", ".py", ".json", ".xml",
    ".exe", ".msi",
}


def find_file(
    query: str,
    max_results: int = 5,
    search_folders: list[str] | None = None,
    use_memory_boost: bool = True,
) -> list[dict[str, Any]]:
    """Search for files matching *query* across common folders.

    Returns a list of dicts with keys:
        path, name, size, modified, is_dir
    Sorted by relevance (name match > path match, recency).
    """
    if search_folders is None:
        search_folders = get_common_search_folders()

    query_lower = query.casefold()
    query_tokens = query_lower.split()
    results: list[dict[str, Any]] = []

    for folder in search_folders:
        if not os.path.isdir(folder):
            continue
        try:
            for entry in os.scandir(folder):
                try:
                    score = _score_file_match(entry, query, query_lower, query_tokens)
                    if score > 0:
                        stat = entry.stat()
                        results.append({
                            "path": entry.path,
                            "name": entry.name,
                            "size": stat.st_size,
                            "modified": stat.st_mtime,
                            "is_dir": entry.is_dir(),
                            "_score": score,
                            "_folder": folder,
                        })
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            continue

    results.sort(key=lambda r: (-r["_score"], -r["modified"]))
    top = results[:max_results]
    for r in top:
        del r["_score"]
        del r["_folder"]
    return top


def _score_file_match(
    entry: os.DirEntry,
    query: str,
    query_lower: str,
    query_tokens: list[str],
) -> float:
    """Score a single file entry against the query.

    Returns 0.0 for no match, higher values for better matches.
    """
    name_lower = entry.name.casefold()

    # Exact match (ignoring extension)
    name_no_ext = Path(entry.name).stem.casefold()
    if name_no_ext == query_lower:
        return 100.0

    # Exact substring match
    if query_lower in name_lower:
        return 80.0

    # All query tokens present in name (in any order)
    if all(token in name_lower for token in query_tokens):
        return 60.0

    # Extension-specific: query ends with an extension
    for ext in _FILE_EXTENSIONS:
        if query_lower.endswith(ext):
            stem = query_lower[: -len(ext)].strip()
            if stem and stem in name_lower:
                return 50.0

    # Any token matches
    for token in query_tokens:
        if len(token) >= 3 and token in name_lower:
            return 30.0

    return 0.0


# ---------------------------------------------------------------------------
# Open file
# ---------------------------------------------------------------------------

def open_file(file_path: str) -> dict:
    """Open a file with its default application.

    Accepts a full path or a relative path.  If the file does not exist,
    returns an error dict with ``needs_search=True`` so the caller can
    attempt a search fallback.
    """
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return {
            "success": False,
            "message": f"File not found: {file_path}",
            "needs_search": True,
            "query": path.stem,
        }

    try:
        os.startfile(str(path))
        logger.info("Opened file: %s", path)
        return {
            "success": True,
            "message": f"Opened {path.name}.",
            "details": {"path": str(path)},
        }
    except Exception as exc:
        logger.error("Failed to open %s: %s", path, exc)
        return {
            "success": False,
            "message": f"Could not open {path.name}: {exc}",
        }


# ---------------------------------------------------------------------------
# Open containing folder
# ---------------------------------------------------------------------------

def open_containing_folder(file_path: str) -> dict:
    """Open the parent folder of *file_path* in Windows Explorer."""
    path = Path(file_path).expanduser().resolve()
    parent = path.parent
    if not parent.exists():
        return {
            "success": False,
            "message": f"Folder not found: {parent}",
        }

    try:
        subprocess.Popen(["explorer", "/select,", str(path)])
        logger.info("Opened folder containing: %s", path)
        return {
            "success": True,
            "message": f"Opened folder containing {path.name}.",
            "details": {"path": str(parent), "file": str(path)},
        }
    except Exception as exc:
        logger.error("Failed to open folder for %s: %s", path, exc)
        return {
            "success": False,
            "message": f"Could not open folder: {exc}",
        }


# ---------------------------------------------------------------------------
# Copy / Move / Rename / Delete
# ---------------------------------------------------------------------------

def copy_file(source: str, dest_dir: str) -> dict:
    """Copy a file to *dest_dir*, preserving the filename."""
    src = Path(source).expanduser().resolve()
    if not src.exists():
        return {"success": False, "message": f"Source not found: {source}"}

    dst = Path(dest_dir).expanduser().resolve()
    if not dst.exists():
        try:
            dst.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"success": False, "message": f"Could not create destination: {exc}"}
    if not dst.is_dir():
        return {"success": False, "message": f"Destination is not a directory: {dest_dir}"}

    dest_path = dst / src.name
    try:
        shutil.copy2(str(src), str(dest_path))
        logger.info("Copied %s -> %s", src, dest_path)
        return {
            "success": True,
            "message": f"Copied {src.name} to {dst.name}.",
            "details": {"source": str(src), "destination": str(dest_path)},
        }
    except Exception as exc:
        logger.error("Copy failed %s -> %s: %s", src, dest_path, exc)
        return {"success": False, "message": f"Could not copy file: {exc}"}


def move_file(source: str, dest_dir: str) -> dict:
    """Move a file to *dest_dir*."""
    src = Path(source).expanduser().resolve()
    if not src.exists():
        return {"success": False, "message": f"Source not found: {source}"}

    dst = Path(dest_dir).expanduser().resolve()
    if not dst.exists():
        try:
            dst.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"success": False, "message": f"Could not create destination: {exc}"}
    if not dst.is_dir():
        return {"success": False, "message": f"Destination is not a directory: {dest_dir}"}

    dest_path = dst / src.name
    try:
        shutil.move(str(src), str(dest_path))
        logger.info("Moved %s -> %s", src, dest_path)
        return {
            "success": True,
            "message": f"Moved {src.name} to {dst.name}.",
            "details": {"source": str(src), "destination": str(dest_path)},
        }
    except Exception as exc:
        logger.error("Move failed %s -> %s: %s", src, dest_path, exc)
        return {"success": False, "message": f"Could not move file: {exc}"}


def rename_file(source: str, new_name: str) -> dict:
    """Rename *source* to *new_name* (name only or full path)."""
    src = Path(source).expanduser().resolve()
    if not src.exists():
        return {"success": False, "message": f"File not found: {source}"}

    dst = src.parent / new_name
    try:
        src.rename(dst)
        logger.info("Renamed %s -> %s", src, dst)
        return {
            "success": True,
            "message": f"Renamed {src.name} to {dst.name}.",
            "details": {"source": str(src), "destination": str(dst)},
        }
    except Exception as exc:
        logger.error("Rename failed %s -> %s: %s", src, dst, exc)
        return {"success": False, "message": f"Could not rename file: {exc}"}


def delete_file(file_path: str, confirmed: bool = False) -> dict:
    """Delete a file, sending it to the Recycle Bin.

    When *confirmed* is False the function returns a dict with
    ``needs_confirmation=True`` so the caller can ask the user before
    proceeding.
    """
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return {"success": False, "message": f"File not found: {file_path}"}

    if not confirmed:
        return {
            "success": False,
            "needs_confirmation": True,
            "message": f"Are you sure you want to delete {path.name}?",
            "details": {"path": str(path)},
        }

    try:
        # Use shell32.SHFileOperationW to send to Recycle Bin
        import ctypes
        from ctypes import wintypes

        class _SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", wintypes.WORD),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", wintypes.LPVOID),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        FO_DELETE = 3
        FOF_ALLOWUNDO = 0x0040
        FOF_NOCONFIRMATION = 0x0010
        FOF_SILENT = 0x0004

        flags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
        pFrom = str(path) + "\0"

        op = _SHFILEOPSTRUCTW(
            hwnd=None,
            wFunc=FO_DELETE,
            pFrom=pFrom,
            pTo=None,
            fFlags=flags,
            fAnyOperationsAborted=False,
            hNameMappings=None,
            lpszProgressTitle=None,
        )

        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if result != 0:
            raise ctypes.WinError(result)

        logger.info("Deleted file: %s", path)
        return {
            "success": True,
            "message": f"Deleted {path.name}.",
            "details": {"path": str(path)},
        }
    except Exception as exc:
        logger.error("Delete failed %s: %s", path, exc)
        return {"success": False, "message": f"Could not delete {path.name}: {exc}"}
