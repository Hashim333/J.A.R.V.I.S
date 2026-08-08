from __future__ import annotations

from unittest.mock import MagicMock, patch

from automation.handlers import KeyboardHandler
from models.execution_plan import Step


class TestKeyboardReliability:
    def test_hotkey_reports_failure_details(self) -> None:
        handler = KeyboardHandler()
        step = Step(action="hotkey", target="", parameters={"keys": "ctrl+n"})

        with patch("automation.handlers.KeyboardController") as controller_cls:
            controller = MagicMock()
            controller.hotkey.return_value = False
            controller_cls.return_value = controller

            result = handler.run(step)

        assert result["success"] is False
        assert "Ctrl+N" in result["message"]
        assert result["details"]["attempt"] == 2
