"""Thread-safe backend state and window-action bridge."""
from __future__ import annotations

import logging
import time
from enum import Enum
from PySide6.QtCore import QObject, Property, QThread, Qt, Signal, Slot

logger = logging.getLogger(__name__)


class UIState(Enum):
    """UI states for the single-channel bridge.

    PASSIVE    - System idle, not listening, not processing
    WAKE       - Wake word detected (or direct-listening entry)
    LISTENING  - Actively capturing user speech
    UNDERSTANDING - Speech recognized, being processed/interpreted
    THINKING   - LLM reasoning / planning in progress
    WORKING    - Executing action (app launch, web search, etc.)
    SPEAKING   - TTS playing audio
    DONE       - Turn complete, returning to PASSIVE
    ERROR      - Recoverable error, user-visible message
    """
    PASSIVE = "PASSIVE"
    WAKE = "WAKE"
    LISTENING = "LISTENING"
    UNDERSTANDING = "UNDERSTANDING"
    THINKING = "THINKING"
    WORKING = "WORKING"
    SPEAKING = "SPEAKING"
    DONE = "DONE"
    ERROR = "ERROR"

    @classmethod
    def all(cls) -> set[str]:
        return {s.value for s in cls}


class DragHandler(QObject):
    """Handles window drag requests from the web view via QWebChannel."""

    def __init__(self, window: QObject | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window = window

    def set_window(self, window: QObject) -> None:
        self._window = window

    @Slot()
    def start_drag(self) -> None:
        """Start native system drag for frameless window."""
        if self._window is not None:
            # Use Qt 6's startSystemMove for native window dragging
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
            else:
                logger.warning("DragHandler: windowHandle() is None")


class Bridge(QObject):
    """Single channel for backend state updates and window actions.

    All state transitions are emitted via `stateChanged` with a payload dict:
        {"state": str, "label": str, "caption": str, "audio_level": float | None}

    Thread-safe: all public methods are @Slot and use queued connections
    when called from non-UI threads. Every transition is logged.
    """

    # Legacy signals (kept for backward compatibility)
    coreStateChanged = Signal(str)
    subtitleChanged = Signal(str)
    currentTaskChanged = Signal(str)
    showRequested = Signal()
    hideRequested = Signal()
    quitRequested = Signal()

    # New unified state signal with full payload
    stateChanged = Signal(dict)

    _core_state_requested = Signal(str)
    _subtitle_requested = Signal(str)
    _task_requested = Signal(str)
    _state_transition_requested = Signal(dict)

    _VALID_STATES = frozenset(UIState.all()) | frozenset({
        "idle", "listening", "thinking", "speaking", "error", "offline",
        "starting", "understanding", "working", "executing", "success",
        "done", "waiting", "observing", "verifying", "planning", "cancelled",
    })
    _STALE_LISTENING_SUBTITLES = frozenset({
        "Listening...", "I'm still listening.",
    })

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._core_state = "idle"
        self._subtitle = ""
        self._task = ""
        self._ui_state = UIState.PASSIVE.value
        self._audio_level: float | None = None

        # Queued connections for thread safety
        self._core_state_requested.connect(
            self._apply_core_state, Qt.ConnectionType.QueuedConnection,
        )
        self._subtitle_requested.connect(
            self._apply_subtitle, Qt.ConnectionType.QueuedConnection,
        )
        self._task_requested.connect(
            self._apply_current_task, Qt.ConnectionType.QueuedConnection,
        )
        self._state_transition_requested.connect(
            self._apply_state_transition, Qt.ConnectionType.QueuedConnection,
        )

        # Transition log for diagnostics
        self._transition_log: list[dict] = []
        self._max_log_entries = 500

    @Property(str, notify=coreStateChanged)
    def coreState(self) -> str:
        return self._core_state

    @Property(str, notify=subtitleChanged)
    def subtitleText(self) -> str:
        return self._subtitle

    @Property(str, notify=currentTaskChanged)
    def currentTask(self) -> str:
        return self._task

    @Property(str, notify=stateChanged)
    def uiState(self) -> str:
        return self._ui_state

    @Property(float, notify=stateChanged)
    def audioLevel(self) -> float:
        return self._audio_level if self._audio_level is not None else 0.0

    # ------------------------------------------------------------------
    # Public API (called from backend threads)
    # ------------------------------------------------------------------

    @Slot(str)
    def set_core_state(self, state: str) -> None:
        """Legacy core state setter. Maps to new UI states."""
        if self._on_ui_thread():
            self._apply_core_state(state)
        else:
            self._core_state_requested.emit(state)

    @Slot(str)
    def show_subtitle(self, text: str) -> None:
        """Legacy subtitle setter."""
        value = str(text or "").strip()
        if self._on_ui_thread():
            self._apply_subtitle(value)
        else:
            self._subtitle_requested.emit(value)

    @Slot(str)
    def set_current_task(self, task: str) -> None:
        """Legacy task setter."""
        value = str(task or "")
        if self._on_ui_thread():
            self._apply_current_task(value)
        else:
            self._task_requested.emit(value)

    # ------------------------------------------------------------------
    # New unified state transition API
    # ------------------------------------------------------------------

    def emit_state(
        self,
        state: UIState | str,
        label: str = "",
        caption: str = "",
        audio_level: float | None = None,
    ) -> None:
        """Emit a state transition with full payload.

        Called from: ConversationOwner, DuplexVoiceSession, Brain/Executor,
        VoiceManager, WakeWordService.

        Args:
            state: UIState enum or string value
            label: Human-readable state label (e.g., "Listening for command")
            caption: Optional subtitle text for UI
            audio_level: Optional 0.0-1.0 audio level for visualizer
        """
        state_val = state.value if isinstance(state, UIState) else str(state)
        payload = {
            "state": state_val,
            "label": label or state_val.replace("_", " ").title(),
            "caption": caption,
            "audio_level": audio_level,
            "timestamp": time.time(),
        }
        # Backward compatibility: map new states to legacy core states
        legacy_map = {
            UIState.PASSIVE.value: "idle",
            UIState.WAKE.value: "waiting",
            UIState.LISTENING.value: "listening",
            UIState.UNDERSTANDING.value: "understanding",
            UIState.THINKING.value: "thinking",
            UIState.WORKING.value: "working",
            UIState.SPEAKING.value: "speaking",
            UIState.DONE.value: "done",
            UIState.ERROR.value: "error",
        }
        if self._on_ui_thread():
            self._apply_state_transition(payload)
            # Also emit legacy core state for backward compat
            legacy = legacy_map.get(state_val)
            if legacy:
                self._apply_core_state(legacy)
        else:
            self._state_transition_requested.emit(payload)
            # Queue legacy core state as well
            legacy = legacy_map.get(state_val)
            if legacy:
                self._core_state_requested.emit(legacy)

    # Convenience methods for each state
    def emit_passive(self, caption: str = "Ready when you are.") -> None:
        self.emit_state(UIState.PASSIVE, "Passive", caption)

    def emit_wake(self, caption: str = "Wake word detected") -> None:
        self.emit_state(UIState.WAKE, "Wake Detected", caption)

    def emit_listening(self, caption: str = "Listening...", audio_level: float | None = None) -> None:
        self.emit_state(UIState.LISTENING, "Listening", caption, audio_level)

    def emit_understanding(self, caption: str = "Understanding...") -> None:
        self.emit_state(UIState.UNDERSTANDING, "Understanding", caption)

    def emit_thinking(self, caption: str = "Thinking...") -> None:
        self.emit_state(UIState.THINKING, "Thinking", caption)

    def emit_working(self, caption: str = "Working...") -> None:
        self.emit_state(UIState.WORKING, "Working", caption)

    def emit_speaking(self, caption: str = "Speaking...") -> None:
        self.emit_state(UIState.SPEAKING, "Speaking", caption)

    def emit_done(self, caption: str = "Done") -> None:
        self.emit_state(UIState.DONE, "Done", caption)

    def emit_error(self, caption: str, label: str = "Error") -> None:
        self.emit_state(UIState.ERROR, label, caption)
        # Backward compat: also call show_subtitle for error messages
        self.show_subtitle(caption)

    # ------------------------------------------------------------------
    # Internal application (UI thread only)
    # ------------------------------------------------------------------

    @Slot(str)
    def _apply_core_state(self, state: str) -> None:
        if state not in self._VALID_STATES:
            logger.warning("Bridge: unknown core state %r", state)
            return
        if self._core_state == state:
            return
        self._core_state = state
        self.coreStateChanged.emit(state)

        # Map legacy states to new UI states for compatibility
        state_map = {
            "idle": UIState.PASSIVE,
            "listening": UIState.LISTENING,
            "thinking": UIState.THINKING,
            "speaking": UIState.SPEAKING,
            "error": UIState.ERROR,
            "offline": UIState.ERROR,
            "understanding": UIState.UNDERSTANDING,
            "working": UIState.WORKING,
            "executing": UIState.WORKING,
            "done": UIState.DONE,
            "waiting": UIState.WAKE,
        }
        if state in state_map:
            self._apply_state_transition({
                "state": state_map[state].value,
                "label": state_map[state].value.replace("_", " ").title(),
                "caption": "",
                "audio_level": None,
                "timestamp": time.time(),
            })

        if state == "thinking" and self._subtitle != "Thinking...":
            self._apply_subtitle("Thinking...")
        elif state == "listening" and self._subtitle == "Thinking...":
            self._apply_subtitle("Listening...")
        elif state == "idle" and self._subtitle in self._STALE_LISTENING_SUBTITLES:
            self._apply_subtitle("Ready when you are.")

    @Slot(str)
    def _apply_subtitle(self, text: str) -> None:
        if text in {"Listening...", "Thinking..."}:
            if self._core_state in {"thinking", "listening"}:
                text = "Thinking..." if self._core_state == "thinking" else "Listening..."
        if text in self._STALE_LISTENING_SUBTITLES and self._core_state == "idle":
            text = "Ready when you are."
        if self._subtitle != text:
            self._subtitle = text
            self.subtitleChanged.emit(text)

    @Slot(str)
    def _apply_current_task(self, task: str) -> None:
        if self._task != task:
            self._task = task
            self.currentTaskChanged.emit(task)

    @Slot(dict)
    def _apply_state_transition(self, payload: dict) -> None:
        """Apply a state transition on the UI thread."""
        state = payload.get("state")
        if state not in self._VALID_STATES:
            logger.warning("Bridge: unknown UI state %r", state)
            return

        old_state = self._ui_state
        if old_state == state and self._subtitle == payload.get("caption", ""):
            # Only update audio level if state unchanged
            if payload.get("audio_level") is not None:
                self._audio_level = float(payload["audio_level"])
                self.stateChanged.emit(self._build_payload(state, payload.get("label", ""), payload.get("caption", "")))
            return

        self._ui_state = state
        self._subtitle = payload.get("caption", "")
        self._audio_level = payload.get("audio_level")

        # Log transition
        transition = {
            "from": old_state,
            "to": state,
            "label": payload.get("label", ""),
            "caption": payload.get("caption", ""),
            "audio_level": payload.get("audio_level"),
            "timestamp": payload.get("timestamp", time.time()),
        }
        self._log_transition(transition)

        # Emit signals
        self.stateChanged.emit(self._build_payload(state, payload.get("label", ""), payload.get("caption", "")))
        self.subtitleChanged.emit(self._subtitle)

    def _build_payload(self, state: str, label: str, caption: str) -> dict:
        return {
            "state": state,
            "label": label,
            "caption": caption,
            "audio_level": self._audio_level,
        }

    def _log_transition(self, transition: dict) -> None:
        """Log and store transition for diagnostics."""
        t_str = f"UI STATE: {transition['from']} -> {transition['to']}"
        if transition.get("label"):
            t_str += f" [{transition['label']}]"
        if transition.get("caption"):
            t_str += f" | {transition['caption']}"
        if transition.get("audio_level") is not None:
            t_str += f" | audio={transition['audio_level']:.2f}"
        logger.info(t_str)

        self._transition_log.append(transition)
        if len(self._transition_log) > self._max_log_entries:
            self._transition_log.pop(0)

    # ------------------------------------------------------------------
    # Window actions
    # ------------------------------------------------------------------

    @Slot()
    def show_window(self) -> None:
        self.showRequested.emit()

    @Slot()
    def hide_window(self) -> None:
        self.hideRequested.emit()

    @Slot()
    def quit_app(self) -> None:
        self.quitRequested.emit()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_transition_log(self) -> list[dict]:
        """Return the full state transition log."""
        return list(self._transition_log)

    def print_transition_log(self) -> None:
        """Print formatted transition log to stdout."""
        print("\n=== BRIDGE STATE TRANSITION LOG ===")
        for i, t in enumerate(self._transition_log):
            ts = time.strftime("%H:%M:%S", time.localtime(t.get("timestamp", 0)))
            audio = f" audio={t['audio_level']:.2f}" if t.get("audio_level") is not None else ""
            print(f"  {i:3d} [{ts}] {t['from']} -> {t['to']} [{t.get('label','')}] | {t.get('caption','')}{audio}")
        print(f"=== END LOG ({len(self._transition_log)} transitions) ===\n")

    def _on_ui_thread(self) -> bool:
        return QThread.currentThread() == self.thread()