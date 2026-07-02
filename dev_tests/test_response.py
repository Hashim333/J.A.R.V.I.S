from __future__ import annotations

import importlib
import io
from contextlib import redirect_stdout
from unittest.mock import patch

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


class FakeVoiceManager:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def speak(self, text: str) -> bool:
        self.spoken.append(text)
        return True


def test_voice_disabled_does_not_speak() -> None:
    response = Response(success=True, message="All steps executed.")
    voice = FakeVoiceManager()
    manager = ResponseManager(voice_enabled=False, voice_manager=voice)
    output = io.StringIO()

    with redirect_stdout(output):
        manager.present_console(response)

    assert output.getvalue() == "Done.\n"
    assert voice.spoken == []


def test_voice_enabled_speaks_voice_text_once() -> None:
    response = Response(
        success=True,
        message="All steps executed.",
        data={"intent": "active_window", "results": [{"result": "Chrome"}]},
    )
    voice = FakeVoiceManager()
    manager = ResponseManager(voice_enabled=True, voice_manager=voice)
    output = io.StringIO()

    with redirect_stdout(output):
        manager.present_console(response)

    assert output.getvalue() == "Active window: Chrome\n"
    assert voice.spoken == ["Active window: Chrome"]


def test_console_output_is_not_duplicated_when_voice_enabled() -> None:
    response = Response(success=True, message="All steps executed.")
    voice = FakeVoiceManager()
    manager = ResponseManager(voice_enabled=True, voice_manager=voice)
    output = io.StringIO()

    with redirect_stdout(output):
        manager.present_console(response)

    assert output.getvalue() == "Done.\n"
    assert voice.spoken == ["Done."]


def test_voice_enabled_configuration_loading() -> None:
    with patch.dict("os.environ", {"VOICE_ENABLED": "true"}):
        import config.settings as settings_module

        reloaded = importlib.reload(settings_module)

    assert reloaded.settings.voice_enabled is True
    assert reloaded.VOICE_ENABLED is True


def test_voice_disabled_configuration_loading() -> None:
    with patch.dict("os.environ", {"VOICE_ENABLED": "false"}):
        import config.settings as settings_module

        reloaded = importlib.reload(settings_module)

    assert reloaded.settings.voice_enabled is False
    assert reloaded.VOICE_ENABLED is False


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
