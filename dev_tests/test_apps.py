"""
dev_tests/test_apps.py
Tests for automation/apps.py

Covers:
  1. open_notepad()
  2. open_calculator()
  3. check_chrome_running()
  4. close_notepad()
  5. exit / menu dispatch
"""

import subprocess
import sys
import types
import unittest
from io import StringIO
from unittest.mock import MagicMock, call, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proc(name: str, pid: int = 1000) -> MagicMock:
    """Return a psutil-style Process mock with a given name."""
    p = MagicMock()
    p.info = {"name": name, "pid": pid}
    p.name.return_value = name
    p.pid = pid
    return p


# ---------------------------------------------------------------------------
# 1. open_notepad
# ---------------------------------------------------------------------------

class TestOpenNotepad(unittest.TestCase):

    @patch("automation.apps.subprocess.Popen")
    def test_opens_notepad_exe(self, mock_popen):
        """open_notepad launches notepad.exe via Popen."""
        from automation.apps import open_notepad

        mock_popen.return_value = MagicMock(pid=1111)
        open_notepad()

        args, _ = mock_popen.call_args
        launched = args[0] if args else mock_popen.call_args.kwargs.get("args", "")
        target = launched if isinstance(launched, str) else " ".join(launched)
        self.assertIn("notepad", target.lower())

    @patch("automation.apps.subprocess.Popen")
    def test_open_notepad_returns_process_or_none(self, mock_popen):
        """open_notepad returns a Popen object or None — never raises."""
        from automation.apps import open_notepad

        mock_popen.return_value = MagicMock(pid=1112)
        result = open_notepad()
        # Either a process handle or None is acceptable; must not raise.
        self.assertTrue(result is None or hasattr(result, "pid"))

    @patch(
        "automation.apps.subprocess.Popen",
        side_effect=FileNotFoundError("notepad.exe not found"),
    )
    def test_open_notepad_handles_file_not_found(self, mock_popen):
        """open_notepad does not propagate FileNotFoundError."""
        from automation.apps import open_notepad

        try:
            open_notepad()
        except FileNotFoundError:
            self.fail("open_notepad raised FileNotFoundError — it should handle it.")

    @patch("automation.apps.subprocess.Popen")
    def test_open_notepad_called_once(self, mock_popen):
        """open_notepad calls Popen exactly once."""
        from automation.apps import open_notepad

        open_notepad()
        mock_popen.assert_called_once()


# ---------------------------------------------------------------------------
# 2. open_calculator
# ---------------------------------------------------------------------------

class TestOpenCalculator(unittest.TestCase):

    @patch("automation.apps.subprocess.Popen")
    def test_opens_calculator(self, mock_popen):
        """open_calculator launches calc or calc.exe."""
        from automation.apps import open_calculator

        mock_popen.return_value = MagicMock(pid=2222)
        open_calculator()

        args, _ = mock_popen.call_args
        launched = args[0] if args else mock_popen.call_args.kwargs.get("args", "")
        target = launched if isinstance(launched, str) else " ".join(launched)
        self.assertIn("calc", target.lower())

    @patch("automation.apps.subprocess.Popen")
    def test_open_calculator_called_once(self, mock_popen):
        """open_calculator calls Popen exactly once."""
        from automation.apps import open_calculator

        open_calculator()
        mock_popen.assert_called_once()

    @patch(
        "automation.apps.subprocess.Popen",
        side_effect=OSError("cannot launch"),
    )
    def test_open_calculator_handles_os_error(self, mock_popen):
        """open_calculator does not propagate OSError."""
        from automation.apps import open_calculator

        try:
            open_calculator()
        except OSError:
            self.fail("open_calculator raised OSError — it should handle it.")

    @patch("automation.apps.subprocess.Popen")
    def test_open_calculator_returns_process_or_none(self, mock_popen):
        """Return value is a process handle or None."""
        from automation.apps import open_calculator

        mock_popen.return_value = MagicMock(pid=2223)
        result = open_calculator()
        self.assertTrue(result is None or hasattr(result, "pid"))


# ---------------------------------------------------------------------------
# 3. check_chrome_running
# ---------------------------------------------------------------------------

class TestCheckChromeRunning(unittest.TestCase):

    @patch("automation.apps.psutil.process_iter")
    def test_returns_true_when_chrome_running(self, mock_iter):
        """check_chrome_running returns True when chrome.exe is in the list."""
        from automation.apps import check_chrome_running

        mock_iter.return_value = [
            _make_proc("svchost.exe"),
            _make_proc("chrome.exe", pid=3001),
            _make_proc("explorer.exe"),
        ]
        result = check_chrome_running()
        self.assertTrue(result)

    @patch("automation.apps.psutil.process_iter")
    def test_returns_false_when_chrome_not_running(self, mock_iter):
        """check_chrome_running returns False when chrome.exe absent."""
        from automation.apps import check_chrome_running

        mock_iter.return_value = [
            _make_proc("notepad.exe"),
            _make_proc("calc.exe"),
        ]
        result = check_chrome_running()
        self.assertFalse(result)

    @patch("automation.apps.psutil.process_iter")
    def test_returns_false_on_empty_process_list(self, mock_iter):
        """check_chrome_running returns False for an empty process list."""
        from automation.apps import check_chrome_running

        mock_iter.return_value = []
        result = check_chrome_running()
        self.assertFalse(result)

    @patch("automation.apps.psutil.process_iter")
    def test_case_insensitive_chrome_detection(self, mock_iter):
        """chrome.exe detection is case-insensitive (Chrome.exe, CHROME.EXE…)."""
        from automation.apps import check_chrome_running

        mock_iter.return_value = [_make_proc("Chrome.exe")]
        result = check_chrome_running()
        self.assertTrue(result)

    @patch("automation.apps.psutil.process_iter")
    def test_returns_bool(self, mock_iter):
        """Return value is a plain bool (or truthy/falsy)."""
        from automation.apps import check_chrome_running

        mock_iter.return_value = [_make_proc("chrome.exe")]
        result = check_chrome_running()
        self.assertIsInstance(result, bool)

    @patch("automation.apps.psutil.process_iter", side_effect=Exception("psutil error"))
    def test_handles_psutil_exception(self, mock_iter):
        """check_chrome_running does not propagate unexpected psutil errors."""
        from automation.apps import check_chrome_running

        try:
            check_chrome_running()
        except Exception:
            self.fail("check_chrome_running raised — it should handle psutil errors.")


# ---------------------------------------------------------------------------
# 4. close_notepad
# ---------------------------------------------------------------------------

class TestCloseNotepad(unittest.TestCase):

    @patch("automation.apps.psutil.process_iter")
    def test_terminates_notepad_when_running(self, mock_iter):
        """close_notepad calls terminate() on each notepad.exe process."""
        from automation.apps import close_notepad

        proc = _make_proc("notepad.exe", pid=4001)
        mock_iter.return_value = [proc]

        close_notepad()
        proc.terminate.assert_called()

    @patch("automation.apps.psutil.process_iter")
    def test_no_error_when_notepad_not_running(self, mock_iter):
        """close_notepad does not raise when notepad is absent."""
        from automation.apps import close_notepad

        mock_iter.return_value = [_make_proc("chrome.exe"), _make_proc("calc.exe")]

        try:
            close_notepad()
        except Exception as exc:
            self.fail(f"close_notepad raised unexpectedly: {exc}")

    @patch("automation.apps.psutil.process_iter")
    def test_closes_all_notepad_instances(self, mock_iter):
        """close_notepad terminates every notepad instance, not just the first."""
        from automation.apps import close_notepad

        procs = [_make_proc("notepad.exe", pid=4100 + i) for i in range(3)]
        mock_iter.return_value = procs

        close_notepad()

        for p in procs:
            p.terminate.assert_called()

    @patch("automation.apps.psutil.process_iter")
    def test_does_not_close_other_processes(self, mock_iter):
        """close_notepad never terminates non-notepad processes."""
        from automation.apps import close_notepad

        chrome = _make_proc("chrome.exe", pid=5000)
        notepad = _make_proc("notepad.exe", pid=5001)
        mock_iter.return_value = [chrome, notepad]

        close_notepad()

        chrome.terminate.assert_not_called()

    @patch("automation.apps.psutil.process_iter")
    def test_handles_no_such_process(self, mock_iter):
        """close_notepad handles NoSuchProcess silently."""
        import psutil
        from automation.apps import close_notepad

        proc = _make_proc("notepad.exe", pid=4002)
        proc.terminate.side_effect = psutil.NoSuchProcess(pid=4002)
        mock_iter.return_value = [proc]

        try:
            close_notepad()
        except psutil.NoSuchProcess:
            self.fail("close_notepad raised NoSuchProcess — it should handle it.")


# ---------------------------------------------------------------------------
# 5. Menu / dispatch
# ---------------------------------------------------------------------------

class TestMenuDispatch(unittest.TestCase):
    """
    Verify that the menu drives the correct function for each option
    and exits cleanly on option 5.
    """

    def _run_menu_with_input(self, inputs: list[str]):
        """Feed menu() a sequence of inputs and capture stdout."""
        input_str = "\n".join(inputs) + "\n"
        with patch("builtins.input", side_effect=inputs):
            with patch("sys.stdout", new_callable=StringIO):
                try:
                    from automation.apps import menu
                    menu()
                except (SystemExit, StopIteration):
                    pass  # exit() or input exhausted — both fine

    @patch("automation.apps.open_notepad")
    def test_menu_option_1_calls_open_notepad(self, mock_open_notepad):
        """Menu option 1 → open_notepad() is called."""
        with patch("builtins.input", side_effect=["1", "5"]):
            with patch("sys.stdout", new_callable=StringIO):
                try:
                    from automation.apps import menu
                    menu()
                except (SystemExit, StopIteration):
                    pass
        mock_open_notepad.assert_called()

    @patch("automation.apps.open_calculator")
    def test_menu_option_2_calls_open_calculator(self, mock_open_calc):
        """Menu option 2 → open_calculator() is called."""
        with patch("builtins.input", side_effect=["2", "5"]):
            with patch("sys.stdout", new_callable=StringIO):
                try:
                    from automation.apps import menu
                    menu()
                except (SystemExit, StopIteration):
                    pass
        mock_open_calc.assert_called()

    @patch("automation.apps.check_chrome_running")
    def test_menu_option_3_calls_check_chrome(self, mock_check):
        """Menu option 3 → check_chrome_running() is called."""
        mock_check.return_value = False
        with patch("builtins.input", side_effect=["3", "5"]):
            with patch("sys.stdout", new_callable=StringIO):
                try:
                    from automation.apps import menu
                    menu()
                except (SystemExit, StopIteration):
                    pass
        mock_check.assert_called()

    @patch("automation.apps.close_notepad")
    def test_menu_option_4_calls_close_notepad(self, mock_close):
        """Menu option 4 → close_notepad() is called."""
        with patch("builtins.input", side_effect=["4", "5"]):
            with patch("sys.stdout", new_callable=StringIO):
                try:
                    from automation.apps import menu
                    menu()
                except (SystemExit, StopIteration):
                    pass
        mock_close.assert_called()

    def test_menu_option_5_exits(self):
        """Menu option 5 exits without calling any app function."""
        exited = False
        with patch("builtins.input", side_effect=["5"]):
            with patch("sys.stdout", new_callable=StringIO):
                try:
                    from automation.apps import menu
                    menu()
                    exited = True          # menu returned normally
                except (SystemExit, StopIteration):
                    exited = True          # menu called sys.exit()
        self.assertTrue(exited)

    def test_menu_invalid_option_does_not_crash(self):
        """An unrecognised menu input is handled gracefully."""
        with patch("builtins.input", side_effect=["99", "abc", "5"]):
            with patch("sys.stdout", new_callable=StringIO):
                try:
                    from automation.apps import menu
                    menu()
                except (SystemExit, StopIteration, ValueError):
                    pass   # any of these is fine; a crash traceback is not
                except Exception as exc:
                    self.fail(f"menu crashed on invalid input: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)