from __future__ import annotations

from models.response import Response
from response.manager import ResponseManager


def test_console_success_defaults_to_done() -> None:
    response = Response(success=True, message="All steps executed.")

    assert ResponseManager().console_text(response) == "Done."


def test_console_unknown_command_message() -> None:
    response = Response(success=True, message="Execution plan had no steps to run.")

    assert (
        ResponseManager().console_text(response)
        == 'I didn\'t understand that command.\nType "help" for available commands.'
    )


def test_console_active_window_result() -> None:
    response = Response(
        success=True,
        message="All steps executed.",
        data={"intent": "active_window", "results": [{"result": "Chrome"}]},
    )

    assert ResponseManager().console_text(response) == "Active window: Chrome"


def test_console_list_windows_result() -> None:
    response = Response(
        success=True,
        message="All steps executed.",
        data={"intent": "list_windows", "results": [{"result": ["Chrome", "Code"]}]},
    )

    assert ResponseManager().console_text(response) == "Open windows:\n  Chrome\n  Code"


def test_debug_error_details_are_opt_in() -> None:
    response = Response(
        success=False,
        message="Step failed.",
        error="RuntimeError: details",
    )

    assert ResponseManager().console_text(response) == "Step failed."
    assert (
        ResponseManager(debug=True).console_text(response)
        == "Step failed.\nDetails: RuntimeError: details"
    )


def test_voice_and_notification_are_single_line() -> None:
    response = Response(
        success=True,
        message="All steps executed.",
        data={"intent": "list_windows", "results": [{"result": ["Chrome", "Code"]}]},
    )
    manager = ResponseManager()

    assert manager.voice_text(response) == "Open windows: Chrome Code"
    assert manager.notification_text(response) == "Open windows: Chrome Code"
