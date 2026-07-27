from __future__ import annotations

import logging
import time
from typing import Any

from context_manager.app_detector import AppDetector
from context_manager.browser_detector import BrowserDetector
from context_manager.clarification_engine import ClarificationType
from models.response import Response
from verification.dialog_detector import (
    DialogInfo,
    DialogType,
    detect_blocking_dialog,
)
from verification.profile_handler import ChromeProfileHandler

logger = logging.getLogger(__name__)


class TaskVerifier:
    def __init__(
        self,
        app_detector: AppDetector | None = None,
        browser_detector: BrowserDetector | None = None,
    ) -> None:
        self._app_detector = app_detector or AppDetector()
        self._browser_detector = browser_detector or BrowserDetector()
        self._profile_handler = ChromeProfileHandler(app_detector=self._app_detector)
        self._pending_verification: dict[str, Any] | None = None

    @property
    def has_pending(self) -> bool:
        return self._pending_verification is not None

    def get_pending_context(self) -> dict[str, Any]:
        return self._pending_verification or {}

    def verify(
        self,
        response: Response,
        intent: str,
        entities: dict[str, Any],
    ) -> Response:
        self._pending_verification = None

        if not response.success:
            return response

        if intent == "open_app":
            return self._verify_open_app(response, entities)

        return response

    def resolve(self, answer: str) -> Response | None:
        if not self._pending_verification:
            return None

        pending = self._pending_verification
        check_type = pending.get("check_type", "")

        if check_type == "chrome_profile":
            return self._profile_handler.resolve_profile(answer, pending)
        elif check_type == "dialog":
            dialog = pending.get("dialog_info")
            action = answer.strip().casefold()
            if action in ("yes", "ok", "dismiss", "close", "confirm"):
                return Response(
                    success=True,
                    message=f"{dialog.app_name} is open. You may need to complete the {dialog.dialog_type.name.lower().replace('_', ' ')} manually.",
                    data={"action": "acknowledged"},
                )
            return Response(
                success=True,
                message=f"Continuing with {dialog.app_name}.",
                data={"action": "continue"},
            )

        self._pending_verification = None
        return None

    def clear_pending(self) -> None:
        self._pending_verification = None

    # ------------------------------------------------------------------
    # App verification
    # ------------------------------------------------------------------

    def _verify_open_app(self, response: Response, entities: dict[str, Any]) -> Response:
        app_name = entities.get("app_name", "")
        process_name = entities.get("process_name", f"{app_name}.exe")
        display_name = entities.get("original_app", app_name)

        wait_for_window(app_name, process_name, timeout=3.0)

        dlg = detect_blocking_dialog(app_name, process_name)
        if dlg is None:
            return response

        if dlg.dialog_type == DialogType.PROFILE_PICKER and _is_chrome(process_name):
            return self._profile_handler.handle_chrome_picker(display_name, entities)

        self._pending_verification = {
            "check_type": "dialog",
            "dialog_info": dlg,
            "response": response,
            "entities": entities,
        }
        dlg_type_str = dlg.dialog_type.name.lower().replace("_", " ")
        question = f"{display_name} opened, but a {dlg_type_str} is waiting for your input. Please complete it and let me know when you're done."
        return Response(
            success=False,
            message=question,
            needs_clarification=True,
            clarification_question=question,
            data={"app_name": app_name, "dialog_type": dlg.dialog_type.name},
        )


def wait_for_window(app_name: str, process_name: str, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    import pygetwindow as gw
    while time.monotonic() < deadline:
        try:
            for window in gw.getAllWindows():
                title = window.title.strip().lower()
                if not title or not window.visible:
                    continue
                if app_name.lower() in title or process_name.lower().replace(".exe", "") in title:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _is_chrome(process_name: str) -> bool:
    pn = process_name.casefold()
    return "chrome" in pn or "msedge" in pn or "brave" in pn or "opera" in pn or "vivaldi" in pn
