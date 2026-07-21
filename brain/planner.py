"""
brain/planner.py

Planner converts ParsedCommand into an ExecutionPlan with multi-step
reasoning. Every plan includes a reasoning trace in metadata so that
the system can explain its decisions.
"""

from __future__ import annotations

from typing import Any

from brain.execution_plan import ExecutionPlan, Step
from brain.parsed_command import ParsedCommand


class Planner:
    """Converts ParsedCommand -> ExecutionPlan with reasoning."""

    _DANGEROUS_INTENTS = {
        "shutdown",
        "restart",
        "sleep",
        "hibernate",
        "lock",
        "sign_out",
        "delete_file",
        "format_drive",
        "kill_process",
        "taskkill",
        "registry_modification",
        "firewall_modification",
        "network_scan",
        "service_stop",
        "powershell_script",
        "admin_command",
    }

    _CONFIRMATION_INTENTS = {
        "shutdown": "Shutting down the computer",
        "restart": "Restarting the computer",
        "sleep": "Putting the computer to sleep",
        "hibernate": "Hibernating the computer",
        "sign_out": "Signing out of the current session",
        "lock": "Locking the workstation",
        "delete_file": "Permanently deleting a file",
        "move_file": "Moving or renaming a file",
        "rename_file": "Renaming a file",
        "close_all_apps": "Closing all running applications",
        "close_all_tabs": "Closing all browser tabs",
        "format_drive": "Formatting a drive — all data will be permanently erased",
        "kill_process": "Forcefully terminating a process",
        "taskkill": "Forcefully terminating a process via taskkill",
        "registry_modification": "Modifying the Windows Registry",
        "firewall_modification": "Modifying Windows Firewall rules",
        "network_scan": "Scanning network targets",
        "service_stop": "Stopping a system service",
        "powershell_script": "Executing a PowerShell script",
        "admin_command": "Executing a command that requires administrator privileges",
    }

    def create_plan(self, parsed: ParsedCommand, confirmed: bool = False) -> ExecutionPlan:
        builder = self._BUILDERS.get(parsed.intent)
        if builder is None:
            steps = []
            reasoning = f"No builder registered for intent {parsed.intent!r}."
        else:
            steps = builder(self, parsed)
            reasoning = self._generate_reasoning(parsed)

        metadata: dict[str, Any] = {
            "raw_text": parsed.raw_text,
            "reasoning": reasoning,
        }

        if not confirmed:
            if parsed.intent in self._DANGEROUS_INTENTS:
                metadata["requires_confirmation"] = True
                reason = self._CONFIRMATION_INTENTS.get(
                    parsed.intent, f"Intent {parsed.intent!r} is potentially destructive."
                )
                metadata["confirmation_reason"] = reason

            elif parsed.intent in self._CONFIRMATION_INTENTS:
                metadata["requires_confirmation"] = True
                metadata["confirmation_reason"] = self._CONFIRMATION_INTENTS[parsed.intent]

        if confirmed:
            metadata["confirmed"] = True

        if parsed.intent == "ambiguous":
            metadata["question"] = parsed.entities.get("question", "")
            metadata["app_phrase"] = parsed.entities.get("app_phrase", "")

        return ExecutionPlan(
            raw_text=parsed.raw_text,
            intent=parsed.intent,
            confidence=parsed.confidence,
            steps=steps,
            metadata=metadata,
        )

    def _generate_reasoning(self, parsed: ParsedCommand) -> str:
        intent = parsed.intent
        raw = parsed.raw_text

        reasoning_map = {
            "open_app": lambda: (
                f"User said {raw!r}. Intent is to open an application. "
                f"Target: {parsed.entities.get('app_name', 'unknown')}. "
                f"Will find the executable, check if already running, "
                f"launch or focus, then verify success."
            ),
            "close_app": lambda: (
                f"User said {raw!r}. Intent is to close an application. "
                f"Target: {parsed.entities.get('app_name', 'unknown')}. "
                f"Will check if running, send close signal, "
                f"wait for graceful shutdown, force terminate if needed, "
                f"then verify the process has stopped."
            ),
            "focus_app": lambda: (
                f"User said {raw!r}. Intent is to focus an application window. "
                f"Target: {parsed.entities.get('app_name', 'unknown')}. "
                f"Will check if the app is running and bring its window to the foreground."
            ),
            "restart_app": lambda: (
                f"User said {raw!r}. Intent is to restart an application. "
                f"Target: {parsed.entities.get('app_name', 'unknown')}. "
                f"Will close the app, wait, and launch it again."
            ),
            "minimize_app": lambda: (
                f"User said {raw!r}. Intent is to minimize an application window. "
                f"Target: {parsed.entities.get('app_name', 'unknown')}."
            ),
            "maximize_app": lambda: (
                f"User said {raw!r}. Intent is to maximize an application window. "
                f"Target: {parsed.entities.get('app_name', 'unknown')}."
            ),
            "restore_app": lambda: (
                f"User said {raw!r}. Intent is to restore (un-minimize) an application window. "
                f"Target: {parsed.entities.get('app_name', 'unknown')}."
            ),
            "close_all_apps": lambda: (
                f"User said {raw!r}. Intent is to close all user applications. "
                f"Will close every user-facing process except protected system processes."
            ),
            "open_website": lambda: (
                f"User said {raw!r}. Intent is to open a website. "
                f"Target: {parsed.entities.get('website', 'unknown')}. "
                f"Will open {parsed.entities.get('url', '')} in the browser."
            ),
            "search": lambda: (
                f"User said {raw!r}. Intent is to search. "
                f"Query: {parsed.entities.get('query', '')}. "
                f"Provider: {parsed.entities.get('provider', 'google')}."
            ),
            "compound": lambda: {
                f"User said {raw!r}. Intent is compound with "
                f"{len(parsed.entities.get('commands', []))} sub-commands."
            },
            "open_special_folder": lambda: (
                f"User said {raw!r}. Intent is to open a system folder. "
                f"Target folder: {parsed.entities.get('folder', 'unknown')}. "
                f"Will open the folder in Windows Explorer."
            ),
            "open_settings": lambda: (
                f"User said {raw!r}. Intent is to open Windows Settings. "
                f"Target page: {parsed.entities.get('page', 'main')}. "
                f"Will launch ms-settings: URI."
            ),
            "increase_volume": lambda: (
                f"User said {raw!r}. Intent is to increase system volume."
            ),
            "decrease_volume": lambda: (
                f"User said {raw!r}. Intent is to decrease system volume."
            ),
            "set_volume": lambda: (
                f"User said {raw!r}. Intent is to set volume to "
                f"{parsed.entities.get('level')}%."
            ),
            "mute_volume": lambda: (
                f"User said {raw!r}. Intent is to mute system volume."
            ),
            "unmute_volume": lambda: (
                f"User said {raw!r}. Intent is to unmute system volume."
            ),
            "screenshot": lambda: (
                f"User said {raw!r}. Intent is to take a screenshot. "
                f"Will capture the screen and save to Desktop."
            ),
            "lock": lambda: (
                f"User said {raw!r}. Intent is to lock the workstation. "
                f"Will invoke Windows lock screen. This is destructive."
            ),
            "shutdown": lambda: (
                f"User said {raw!r}. Intent is to shut down the computer. "
                f"This is destructive and requires confirmation."
            ),
            "restart": lambda: (
                f"User said {raw!r}. Intent is to restart the computer. "
                f"This is destructive and requires confirmation."
            ),
            "sleep": lambda: (
                f"User said {raw!r}. Intent is to put the computer to sleep."
            ),
            "ambiguous": lambda: (
                f"User said {raw!r}. The target '{parsed.entities.get('app_phrase', '')}' "
                f"is ambiguous. Will ask for clarification."
            ),
            "open_file": lambda: (
                f"User said {raw!r}. Intent is to open a file. "
                f"Query: {parsed.entities.get('file_query', '')}. "
                f"Will search for the file and open it."
            ),
            "find_file": lambda: (
                f"User said {raw!r}. Intent is to find a file. "
                f"Query: {parsed.entities.get('file_query', '')}. "
                f"Will search common folders for matching files."
            ),
            "open_file_location": lambda: (
                f"User said {raw!r}. Intent is to open the containing folder. "
                f"File: {parsed.entities.get('file_query', '')}."
            ),
            "copy_file": lambda: (
                f"User said {raw!r}. Intent is to copy a file. "
                f"Source: {parsed.entities.get('source', '')}, "
                f"Destination: {parsed.entities.get('destination', '')}."
            ),
            "move_file": lambda: (
                f"User said {raw!r}. Intent is to move a file. "
                f"Source: {parsed.entities.get('source', '')}, "
                f"Destination: {parsed.entities.get('destination', '')}."
            ),
            "rename_file": lambda: (
                f"User said {raw!r}. Intent is to rename a file. "
                f"Source: {parsed.entities.get('source', '')}, "
                f"New name: {parsed.entities.get('new_name', '')}."
            ),
            "delete_file": lambda: (
                f"User said {raw!r}. Intent is to delete a file. "
                f"File: {parsed.entities.get('file_query', '')}. "
                f"This is destructive and requires confirmation."
            ),
            "set_brightness": lambda: (
                f"User said {raw!r}. Intent is to set brightness to "
                f"{parsed.entities.get('level', 50)}%."
            ),
            "wifi_on": lambda: (
                f"User said {raw!r}. Intent is to turn on WiFi."
            ),
            "wifi_off": lambda: (
                f"User said {raw!r}. Intent is to turn off WiFi."
            ),
            "bluetooth_on": lambda: (
                f"User said {raw!r}. Intent is to turn on Bluetooth."
            ),
            "bluetooth_off": lambda: (
                f"User said {raw!r}. Intent is to turn off Bluetooth."
            ),
            "airplane_mode_on": lambda: (
                f"User said {raw!r}. Intent is to turn on airplane mode."
            ),
            "airplane_mode_off": lambda: (
                f"User said {raw!r}. Intent is to turn off airplane mode."
            ),
            "system_status": lambda: (
                f"User said {raw!r}. Intent is to report system status. "
                f"Query: {parsed.entities.get('query', 'all')}."
            ),
            "sign_out": lambda: (
                f"User said {raw!r}. Intent is to sign out."
            ),
            "cancel_shutdown": lambda: (
                f"User said {raw!r}. Intent is to cancel scheduled shutdown."
            ),
            "open_task_manager": lambda: (
                f"User said {raw!r}. Intent is to open Task Manager."
            ),
            "open_device_manager": lambda: (
                f"User said {raw!r}. Intent is to open Device Manager."
            ),
            "open_control_panel": lambda: (
                f"User said {raw!r}. Intent is to open Control Panel."
            ),
            "create_pentest_report": lambda: (
                f"User said {raw!r}. Intent is to create a pentest report. "
                f"Client: {parsed.entities.get('client_name', '')}."
            ),
            "organize_scan_results": lambda: (
                f"User said {raw!r}. Intent is to organise scan results."
            ),
            "summarize_scan_results": lambda: (
                f"User said {raw!r}. Intent is to summarise scan results."
            ),
            "create_pentest_project": lambda: (
                f"User said {raw!r}. Intent is to create a pentest project. "
                f"Name: {parsed.entities.get('project_name', '')}."
            ),
            "read_screen": lambda: (
                f"User said {raw!r}. Intent is to read what is on the screen."
            ),
            "describe_screen": lambda: (
                f"User said {raw!r}. Intent is to describe the screen contents."
            ),
            "click_element": lambda: (
                f"User said {raw!r}. Intent is to click on "
                f"'{parsed.entities.get('target', '')}'."
            ),
            "find_element": lambda: (
                f"User said {raw!r}. Intent is to find "
                f"'{parsed.entities.get('target', '')}' on screen."
            ),
            "read_pdf": lambda: (
                f"User said {raw!r}. Intent is to read a PDF file: "
                f"{parsed.entities.get('file_path', '')}."
            ),
            "ocr_image": lambda: (
                f"User said {raw!r}. Intent is to OCR an image: "
                f"{parsed.entities.get('file_path', '')}."
            ),
            "read_error": lambda: (
                f"User said {raw!r}. Intent is to read the error dialog."
            ),
            "fill_form": lambda: (
                f"User said {raw!r}. Intent is to fill form field "
                f"'{parsed.entities.get('field', '')}' "
                f"with '{parsed.entities.get('value', '')}'."
            ),
            "format_drive": lambda: (
                f"User said {raw!r}. Intent is to format a drive. "
                f"Drive: {parsed.entities.get('drive', '')}. "
                f"This is destructive and requires confirmation."
            ),
            "kill_process": lambda: (
                f"User said {raw!r}. Intent is to kill a process. "
                f"Process: {parsed.entities.get('process', '')}. "
                f"This is destructive and requires confirmation."
            ),
            "unknown": lambda: (
                f"User said {raw!r}. Could not determine intent."
            ),
        }

        builder = reasoning_map.get(intent)
        if builder:
            return builder()
        return f"User said {raw!r}. Intent: {intent}."

    # ------------------------------------------------------------------
    # Builder methods
    # ------------------------------------------------------------------

    def _build_open_app(self, parsed: ParsedCommand) -> list[Step]:
        app_name = parsed.entities.get("app_name")
        params: dict[str, Any] = {"focus_if_running": True}
        profile = parsed.entities.get("profile")
        if profile:
            params["profile"] = profile
        desc = f"Open {app_name}."
        if profile:
            desc = f"Open {app_name} with profile '{profile}'."
        return [self._step("open_app", app_name, params, desc)]

    def _build_close_app(self, parsed: ParsedCommand) -> list[Step]:
        app = parsed.entities.get("app_name")
        return [self._step("close_app", app, {}, f"Close {app}.")]

    def _build_focus_app(self, parsed: ParsedCommand) -> list[Step]:
        app = parsed.entities.get("app_name")
        return [self._step("focus_app", app, {}, f"Focus {app}.")]

    def _build_restart_app(self, parsed: ParsedCommand) -> list[Step]:
        app = parsed.entities.get("app_name")
        return [self._step("restart_app", app, {}, f"Restart {app}.")]

    def _build_minimize_app(self, parsed: ParsedCommand) -> list[Step]:
        app = parsed.entities.get("app_name")
        return [self._step("minimize_app", app, {}, f"Minimize {app}.")]

    def _build_maximize_app(self, parsed: ParsedCommand) -> list[Step]:
        app = parsed.entities.get("app_name", parsed.entities.get("original_app", ""))
        return [self._step("maximize_app", app, {}, f"Maximize {app}.")]

    def _build_restore_app(self, parsed: ParsedCommand) -> list[Step]:
        app = parsed.entities.get("app_name", parsed.entities.get("original_app", ""))
        return [self._step("restore_app", app, {}, f"Restore {app}.")]

    def _build_close_all_apps(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("close_all_apps", None, {}, "Close all user applications.")]

    def _build_open_website(self, parsed: ParsedCommand) -> list[Step]:
        website = parsed.entities.get("website")
        url = parsed.entities.get("url", "")
        params: dict[str, Any] = {"url": url}
        profile = parsed.entities.get("profile")
        if profile:
            params["profile"] = profile
        return [self._step("open_website", website, params, f"Open {website} ({url}).")]

    def _build_search(self, parsed: ParsedCommand) -> list[Step]:
        query = parsed.entities.get("query", "")
        provider = parsed.entities.get("provider", "google")
        return [self._step(
            "search", None,
            {"query": query, "provider": provider},
            f"Search {provider} for '{query}'.",
        )]

    def _build_compound(self, parsed: ParsedCommand) -> list[Step]:
        commands = parsed.entities.get("commands", [])
        steps: list[Step] = []
        for i, cmd in enumerate(commands):
            builder = self._BUILDERS.get(cmd.intent)
            if builder:
                sub_steps = builder(self, cmd)
                steps.extend(sub_steps)
            else:
                steps.append(self._step(
                    cmd.intent, None, dict(cmd.entities),
                    f"Sub-command {i}: {cmd.raw_text}",
                ))
        return steps

    def _build_open_special_folder(self, parsed: ParsedCommand) -> list[Step]:
        folder = parsed.entities.get("folder")
        return [self._step("open_special_folder", folder, {}, f"Open {folder} folder.")]

    def _build_open_settings(self, parsed: ParsedCommand) -> list[Step]:
        page = parsed.entities.get("page", "")
        return [self._step("open_settings", page, {"page": page}, f"Open {page or 'main'} settings.")]

    def _build_increase_volume(self, parsed: ParsedCommand) -> list[Step]:
        amount = parsed.entities.get("amount", 10)
        return [self._step("increase_volume", None, {"amount": amount}, f"Increase volume by {amount}%.")]

    def _build_decrease_volume(self, parsed: ParsedCommand) -> list[Step]:
        amount = parsed.entities.get("amount", 10)
        return [self._step("decrease_volume", None, {"amount": amount}, f"Decrease volume by {amount}%.")]

    def _build_set_volume(self, parsed: ParsedCommand) -> list[Step]:
        level = parsed.entities.get("level", 50)
        return [self._step("set_volume", None, {"level": level}, f"Set volume to {level}%.")]

    def _build_mute_volume(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("mute_volume", None, {}, "Mute volume.")]

    def _build_unmute_volume(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("unmute_volume", None, {}, "Unmute volume.")]

    def _build_screenshot(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("screenshot", None, {}, "Take a screenshot.")]

    def _build_lock(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("lock", None, {}, "Lock workstation.")]

    def _build_shutdown(self, parsed: ParsedCommand) -> list[Step]:
        params: dict[str, Any] = {}
        delay = parsed.entities.get("delay_seconds")
        if delay:
            params["delay_seconds"] = delay
        desc = f"Shut down computer{' in ' + str(delay // 60) + ' minutes' if delay else ''}."
        return [self._step("shutdown", None, params, desc)]

    def _build_restart(self, parsed: ParsedCommand) -> list[Step]:
        params: dict[str, Any] = {}
        delay = parsed.entities.get("delay_seconds")
        if delay:
            params["delay_seconds"] = delay
        desc = f"Restart computer{' in ' + str(delay // 60) + ' minutes' if delay else ''}."
        return [self._step("restart", None, params, desc)]

    def _build_sleep(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("sleep", None, {}, "Sleep computer.")]

    def _build_ambiguous(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("ambiguous", None, dict(parsed.entities), "Ask for clarification.")]

    def _build_unknown(self, parsed: ParsedCommand) -> list[Step]:
        return []

    # ------------------------------------------------------------------
    # File operation builders
    # ------------------------------------------------------------------

    def _build_open_file(self, parsed: ParsedCommand) -> list[Step]:
        file_query = parsed.entities.get("file_query", "")
        return [self._step(
            "open_file", file_query,
            {"file_query": file_query},
            f"Open file: {file_query}.",
        )]

    def _build_find_file(self, parsed: ParsedCommand) -> list[Step]:
        file_query = parsed.entities.get("file_query", "")
        return [self._step(
            "find_file", file_query,
            {"file_query": file_query},
            f"Find file: {file_query}.",
        )]

    def _build_open_file_location(self, parsed: ParsedCommand) -> list[Step]:
        file_query = parsed.entities.get("file_query", "")
        return [self._step(
            "open_file_location", file_query or None,
            {"file_query": file_query},
            f"Open folder containing: {file_query}." if file_query else "Open file location.",
        )]

    def _build_copy_file(self, parsed: ParsedCommand) -> list[Step]:
        source = parsed.entities.get("source", "")
        destination = parsed.entities.get("destination", "")
        return [self._step(
            "copy_file", source,
            {"source": source, "destination": destination},
            f"Copy {source} to {destination}.",
        )]

    def _build_move_file(self, parsed: ParsedCommand) -> list[Step]:
        source = parsed.entities.get("source", "")
        destination = parsed.entities.get("destination", "")
        return [self._step(
            "move_file", source,
            {"source": source, "destination": destination},
            f"Move {source} to {destination}.",
        )]

    def _build_rename_file(self, parsed: ParsedCommand) -> list[Step]:
        source = parsed.entities.get("source", "")
        new_name = parsed.entities.get("new_name", "")
        return [self._step(
            "rename_file", source,
            {"source": source, "new_name": new_name},
            f"Rename {source} to {new_name}.",
        )]

    def _build_delete_file(self, parsed: ParsedCommand) -> list[Step]:
        file_query = parsed.entities.get("file_query", "")
        return [self._step(
            "delete_file", file_query,
            {"file_query": file_query},
            f"Delete file: {file_query}.",
        )]

    # ------------------------------------------------------------------
    # System operation builders
    # ------------------------------------------------------------------

    def _build_set_brightness(self, parsed: ParsedCommand) -> list[Step]:
        level = parsed.entities.get("level", 50)
        return [self._step("set_brightness", None, {"level": level}, f"Set brightness to {level}%.")]

    def _build_wifi_on(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("wifi_on", None, {}, "Turn on WiFi.")]

    def _build_wifi_off(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("wifi_off", None, {}, "Turn off WiFi.")]

    def _build_bluetooth_on(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("bluetooth_on", None, {}, "Turn on Bluetooth.")]

    def _build_bluetooth_off(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("bluetooth_off", None, {}, "Turn off Bluetooth.")]

    def _build_airplane_mode_on(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("airplane_mode_on", None, {}, "Turn on airplane mode.")]

    def _build_airplane_mode_off(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("airplane_mode_off", None, {}, "Turn off airplane mode.")]

    def _build_system_status(self, parsed: ParsedCommand) -> list[Step]:
        query = parsed.entities.get("query", "all")
        return [self._step("system_status", None, {"query": query}, f"Get system status: {query}.")]

    def _build_sign_out(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("sign_out", None, {}, "Sign out.")]

    def _build_cancel_shutdown(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("cancel_shutdown", None, {}, "Cancel scheduled shutdown/restart.")]

    def _build_open_task_manager(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("open_task_manager", None, {}, "Open Task Manager.")]

    def _build_open_device_manager(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("open_device_manager", None, {}, "Open Device Manager.")]

    def _build_open_control_panel(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("open_control_panel", None, {}, "Open Control Panel.")]

    # ------------------------------------------------------------------
    # Format drive / Kill process builders
    # ------------------------------------------------------------------

    def _build_format_drive(self, parsed: ParsedCommand) -> list[Step]:
        drive = parsed.entities.get("drive", "")
        return [self._step(
            "format_drive", drive,
            {"drive": drive},
            f"Format drive {drive}.",
        )]

    def _build_kill_process(self, parsed: ParsedCommand) -> list[Step]:
        process = parsed.entities.get("process", "")
        return [self._step(
            "kill_process", process,
            {"process": process},
            f"Kill process {process}.",
        )]

    # ------------------------------------------------------------------
    # Security / pentest builders
    # ------------------------------------------------------------------

    def _build_create_pentest_report(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step(
            "create_pentest_report", None,
            dict(parsed.entities),
            f"Create pentest report for {parsed.entities.get('client_name', 'unknown')}.",
        )]

    def _build_organize_scan_results(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step(
            "organize_scan_results", None,
            dict(parsed.entities),
            f"Organise scan results into {parsed.entities.get('project_name', 'project')}.",
        )]

    def _build_summarize_scan_results(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step(
            "summarize_scan_results", None,
            dict(parsed.entities),
            f"Summarize scan results.",
        )]

    def _build_create_pentest_project(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step(
            "create_pentest_project", None,
            dict(parsed.entities),
            f"Create pentest project {parsed.entities.get('project_name', '')}.",
        )]

    # ------------------------------------------------------------------
    # Vision / screen understanding builders
    # ------------------------------------------------------------------

    def _build_read_screen(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step(
            "read_screen", None,
            dict(parsed.entities),
            f"Read screen contents.",
        )]

    def _build_describe_screen(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step(
            "describe_screen", None,
            dict(parsed.entities),
            f"Describe what is on the screen.",
        )]

    def _build_click_element(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step(
            "click_element", None,
            dict(parsed.entities),
            f"Click on {parsed.entities.get('target', 'element')}.",
        )]

    def _build_find_element(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step(
            "find_element", None,
            dict(parsed.entities),
            f"Find {parsed.entities.get('target', 'element')} on screen.",
        )]

    def _build_read_pdf(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step(
            "read_pdf", None,
            dict(parsed.entities),
            f"Read PDF: {parsed.entities.get('file_path', '')}.",
        )]

    def _build_ocr_image(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step(
            "ocr_image", None,
            dict(parsed.entities),
            f"OCR image: {parsed.entities.get('file_path', '')}.",
        )]

    def _build_read_error(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step(
            "read_error", None,
            dict(parsed.entities),
            f"Read error dialog on screen.",
        )]

    def _build_fill_form(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step(
            "fill_form", None,
            dict(parsed.entities),
            f"Fill form field {parsed.entities.get('field', '')} with {parsed.entities.get('value', '')}.",
        )]

    @staticmethod
    def _step(
        action: str,
        target: object,
        parameters: dict[str, Any] | None = None,
        description: str = "",
    ) -> Step:
        return Step(
            action=action,
            target=target if isinstance(target, str) else None,
            parameters=parameters or {},
            description=description,
        )

    _BUILDERS: dict[str, Any] = {
        "open_app": _build_open_app,
        "close_app": _build_close_app,
        "focus_app": _build_focus_app,
        "restart_app": _build_restart_app,
        "minimize_app": _build_minimize_app,
        "maximize_app": _build_maximize_app,
        "restore_app": _build_restore_app,
        "close_all_apps": _build_close_all_apps,
        "open_website": _build_open_website,
        "search": _build_search,
        "compound": _build_compound,
        "open_special_folder": _build_open_special_folder,
        "open_settings": _build_open_settings,
        "increase_volume": _build_increase_volume,
        "decrease_volume": _build_decrease_volume,
        "set_volume": _build_set_volume,
        "mute_volume": _build_mute_volume,
        "unmute_volume": _build_unmute_volume,
        "screenshot": _build_screenshot,
        "lock": _build_lock,
        "shutdown": _build_shutdown,
        "restart": _build_restart,
        "sleep": _build_sleep,
        "open_file": _build_open_file,
        "find_file": _build_find_file,
        "open_file_location": _build_open_file_location,
        "copy_file": _build_copy_file,
        "move_file": _build_move_file,
        "rename_file": _build_rename_file,
        "delete_file": _build_delete_file,
        "set_brightness": _build_set_brightness,
        "wifi_on": _build_wifi_on,
        "wifi_off": _build_wifi_off,
        "bluetooth_on": _build_bluetooth_on,
        "bluetooth_off": _build_bluetooth_off,
        "airplane_mode_on": _build_airplane_mode_on,
        "airplane_mode_off": _build_airplane_mode_off,
        "system_status": _build_system_status,
        "sign_out": _build_sign_out,
        "cancel_shutdown": _build_cancel_shutdown,
        "open_task_manager": _build_open_task_manager,
        "open_device_manager": _build_open_device_manager,
        "open_control_panel": _build_open_control_panel,
        "create_pentest_report": _build_create_pentest_report,
        "organize_scan_results": _build_organize_scan_results,
        "summarize_scan_results": _build_summarize_scan_results,
        "create_pentest_project": _build_create_pentest_project,
        "format_drive": _build_format_drive,
        "kill_process": _build_kill_process,
        "read_screen": _build_read_screen,
        "describe_screen": _build_describe_screen,
        "click_element": _build_click_element,
        "find_element": _build_find_element,
        "read_pdf": _build_read_pdf,
        "ocr_image": _build_ocr_image,
        "read_error": _build_read_error,
        "fill_form": _build_fill_form,
        "ambiguous": _build_ambiguous,
        "unknown": _build_unknown,
    }
