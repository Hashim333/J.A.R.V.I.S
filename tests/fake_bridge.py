"""A Bridge-faithful test double for backend tests.

The conversation owner publishes state through ``Bridge.emit_state`` and its
``emit_*`` convenience wrappers — exactly one channel.  A bare ``MagicMock``
therefore records nothing, so tests that asserted on ``set_core_state`` saw an
owner that "never returned to idle" even though the real UI contract was
honoured.

``FakeBridge`` mirrors :class:`ui.bridge.Bridge`: the same public methods and
the same ``UIState`` -> legacy core-state mapping, recording what the Qt UI
would have received.  It needs no QApplication, so backend tests stay headless.
"""

from __future__ import annotations

from typing import Any, Callable

# Mirrors Bridge.emit_state's legacy_map in ui/bridge.py.
_LEGACY_CORE_STATE = {
    "PASSIVE": "idle",
    "WAKE": "waiting",
    "LISTENING": "listening",
    "UNDERSTANDING": "understanding",
    "THINKING": "thinking",
    "WORKING": "working",
    "SPEAKING": "speaking",
    "DONE": "done",
    "ERROR": "error",
}


class FakeBridge:
    """Records the state a real :class:`ui.bridge.Bridge` would publish."""

    def __init__(self) -> None:
        self.core_states: list[str] = []
        self.subtitles: list[str] = []
        self.current_tasks: list[str] = []
        self.errors: list[tuple[str, str]] = []
        self.window_actions: list[str] = []

    # ── Recorded state ──────────────────────────────────────────────

    @property
    def core_state(self) -> str:
        return self.core_states[-1] if self.core_states else "idle"

    @property
    def subtitle(self) -> str:
        return self.subtitles[-1] if self.subtitles else ""

    def saw(self, state: str) -> bool:
        """True when *state* was ever published as the core state."""
        return state in self.core_states

    # ── Legacy API ──────────────────────────────────────────────────

    def set_core_state(self, state: str) -> None:
        self.core_states.append(state)

    def show_subtitle(self, text: str) -> None:
        self.subtitles.append(str(text or ""))

    def set_current_task(self, task: str) -> None:
        self.current_tasks.append(str(task or ""))

    # ── Unified state API ───────────────────────────────────────────

    def emit_state(
        self,
        state: Any,
        label: str = "",
        caption: str = "",
        audio_level: float | None = None,
    ) -> None:
        name = getattr(state, "value", state)
        legacy = _LEGACY_CORE_STATE.get(str(name))
        if legacy:
            self.set_core_state(legacy)
        if caption:
            self.show_subtitle(caption)

    def _emitter(self, ui_state: str) -> Callable[..., None]:
        def _emit(caption: str = "", *extra: object) -> None:
            self.set_core_state(_LEGACY_CORE_STATE[ui_state])
            if caption:
                self.show_subtitle(caption)

        return _emit

    def emit_passive(self, caption: str = "Ready when you are.") -> None:
        self._emitter("PASSIVE")(caption)

    def emit_wake(self, caption: str = "Wake word detected") -> None:
        self._emitter("WAKE")(caption)

    def emit_listening(self, caption: str = "Listening...", audio_level: float | None = None) -> None:
        self._emitter("LISTENING")(caption)

    def emit_understanding(self, caption: str = "Understanding...") -> None:
        self._emitter("UNDERSTANDING")(caption)

    def emit_thinking(self, caption: str = "Thinking...") -> None:
        self._emitter("THINKING")(caption)

    def emit_working(self, caption: str = "Working...") -> None:
        self._emitter("WORKING")(caption)

    def emit_speaking(self, caption: str = "Speaking...") -> None:
        self._emitter("SPEAKING")(caption)

    def emit_done(self, caption: str = "Done") -> None:
        self._emitter("DONE")(caption)

    def emit_error(self, caption: str, label: str = "Error") -> None:
        self.errors.append((caption, label))
        self.set_core_state(_LEGACY_CORE_STATE["ERROR"])
        self.show_subtitle(caption)

    # ── Window actions (recorded, never performed) ──────────────────

    def show_window(self) -> None:
        self.window_actions.append("show")

    def hide_window(self) -> None:
        self.window_actions.append("hide")

    def quit_app(self) -> None:
        self.window_actions.append("quit")
