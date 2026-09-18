"""
ui/bridge.py

Master Python-to-QML bridge for the JARVIS desktop shell.

Bridge ONLY:
  - receives already-computed values
  - emits Qt signals (auto-queued by Qt for cross-thread safety)
  - updates properties
  - schedules repaints

Bridge NEVER queries WMI, win32com, psutil, or performs blocking I/O.
All system resource polling is delegated to ui.system_monitor.SystemMonitor.

Thread safety
-------------
All public ``@Slot`` methods can be called from any thread — Qt's
``AutoConnection`` queues their emission to the UI thread.  All
``@Property`` getters/setters should only be accessed from the UI thread.
Use ``@Slot`` methods (``set_cpu_usage``, etc.) from background threads.
"""

from __future__ import annotations

import datetime
import logging
import time

from PySide6.QtCore import QObject, Signal, Property, Slot, QTimer

logger = logging.getLogger(__name__)

_THROTTLE_DELTA = 0.5

# How long the backend may go without a heartbeat before the UI reports
# it as offline (Core Offline).
_BACKEND_STALL_SECONDS = 8.0
_BACKEND_CHECK_MS = 1000


class Bridge(QObject):
    """Single bridge object exposed as 'bridge' in QML.

    Write methods decorated with ``@Slot`` are safe to call from any
    thread — Qt's cross-thread signal/slot mechanism queues execution
    to the GUI thread.

    Property **getters** and **setters** (``bridge.coreState = ...``)
    run on the caller's thread and should only be used from the GUI
    thread.  Background threads must use the ``@Slot`` setter methods.
    """

    # ── Core state ────────────────────────────────────────────────────
    coreStateChanged = Signal(str)
    _core_state: str = "idle"

    # ── Window mode ───────────────────────────────────────────────────
    windowModeChanged = Signal(str)
    _window_mode: str = "fullscreen"

    # ── Subtitles / Conversation History ─────────────────────────────
    subtitleChanged = Signal(str)
    conversationHistoryChanged = Signal()
    _conversation_history: list = []
    # Last subtitle text shown (tracked so state transitions can detect a
    # stale subtitle; see coreState setter).
    _subtitle: str = ""

    # ── Wake word ─────────────────────────────────────────────────────
    wakeActiveChanged = Signal(bool)
    _wake_active: bool = False

    # ── Voice energy (0.0–1.0) ────────────────────────────────────────
    micEnergyChanged = Signal(float)
    assistantEnergyChanged = Signal(float)
    _mic_energy: float = 0.0
    _assistant_energy: float = 0.0

    # ── Status indicators ─────────────────────────────────────────────
    internetStatusChanged = Signal(bool)
    micStatusChanged = Signal(bool)
    speakerStatusChanged = Signal(bool)
    cpuUsageChanged = Signal(float)
    ramUsageChanged = Signal(float)
    gpuUsageChanged = Signal(float)
    diskUsageChanged = Signal(float)
    batteryChanged = Signal(float)
    clockChanged = Signal(str)
    providerChanged = Signal(str)
    modelChanged = Signal(str)
    currentTaskChanged = Signal(str)

    _internet_ok: bool = False
    _mic_ok: bool = False
    _speaker_ok: bool = False
    _cpu: float = 0.0
    _ram: float = 0.0
    _gpu: float = 0.0
    _disk: float = 0.0
    _battery: float = -1.0
    _provider: str = ""
    _model: str = ""
    _task: str = ""

    # ── Sidebar ───────────────────────────────────────────────────────
    sidebarVisibleChanged = Signal(bool)
    _sidebar_visible: bool = False
    sidebarSectionChanged = Signal(str)
    _sidebar_section: str = "conversation"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick)
        self._clock_timer.start(1000)
        self._tick()

        # Backend liveness monitor — flips the UI to "Core Offline" if the
        # backend stops sending heartbeats, and back to "idle" on recovery.
        self._backend_heartbeat: float = 0.0
        self._backend_offline: bool = False
        self._backend_monitor = QTimer(self)
        self._backend_monitor.timeout.connect(self._monitor_backend)
        self._backend_monitor.start(_BACKEND_CHECK_MS)

    # ── Backend heartbeat ────────────────────────────────────────────

    @Slot()
    def set_backend_heartbeat(self) -> None:
        """Record that the backend is alive. Safe from any thread."""
        self._backend_heartbeat = time.monotonic()

    def _monitor_backend(self) -> None:
        """UI-thread check: mark the backend offline when heartbeats stop."""
        if self._backend_heartbeat == 0.0:
            return  # backend has not signalled yet
        stale = (time.monotonic() - self._backend_heartbeat) > _BACKEND_STALL_SECONDS
        if stale and not self._backend_offline:
            self._backend_offline = True
            self.coreState = "offline"
            self.show_subtitle(
                "Core Offline — backend not responding. Attempting to recover..."
            )
            logger.warning("Bridge: backend heartbeat stale — showing Core Offline")
        elif not stale and self._backend_offline:
            self._backend_offline = False
            self.coreState = "idle"
            self.show_subtitle("Backend recovered.")
            logger.info("Bridge: backend heartbeat resumed — back online")

    # ── Core state ────────────────────────────────────────────────────

    @Property(str, notify=coreStateChanged)
    def coreState(self) -> str:
        return self._core_state

    @coreState.setter
    def coreState(self, state: str) -> None:
        valid = {"idle", "listening", "thinking", "speaking", "error", "offline"}
        if state not in valid:
            logger.warning("Bridge: unknown core state %r", state)
            return
        if self._core_state != state:
            self._core_state = state
            self.coreStateChanged.emit(state)
            logger.debug("Bridge: core → %s", state)
            # Keep the subtitle coherent with the new state.  coreState and
            # subtitleText travel on independent signals, so without this a
            # transition can leave a stale subtitle on screen (e.g. THINKING
            # while "Listening..." or a partial transcript is still shown).
            # The backend ConversationManager/ConversationOwner stays the
            # sole owner of state; this only refreshes the label.
            self._sync_subtitle_for_state(state)

    @Slot(str)
    def set_core_state(self, state: str) -> None:
        self.coreState = state

    # State labels published automatically on transitions.  Only states
    # whose subtitle is always a fixed label are mapped here; speaking /
    # error / offline keep whatever subtitle the backend set explicitly
    # (response text, error message) alongside the transition.
    _STATE_SUBTITLES = {
        "listening": "Listening...",
        "thinking": "Thinking...",
    }
    # Subtitles that describe listening and must not survive a return to
    # idle (replaced with the idle label below).
    _STALE_LISTENING_SUBTITLES = frozenset({"Listening...", "I'm still listening."})
    _IDLE_SUBTITLE = "Ready when you are."

    def _sync_subtitle_for_state(self, state: str) -> None:
        """Publish a state-label subtitle when the current one is stale.

        Never touches conversation history (state labels are chrome, not
        conversation) and never overwrites content subtitles except when
        they describe a different state than the one just entered.
        """
        if state == "thinking":
            if self._subtitle != self._STATE_SUBTITLES["thinking"]:
                self._publish_state_subtitle(self._STATE_SUBTITLES["thinking"])
        elif state == "listening":
            if self._subtitle == self._STATE_SUBTITLES["thinking"]:
                self._publish_state_subtitle(self._STATE_SUBTITLES["listening"])
        elif state == "idle":
            if self._subtitle in self._STALE_LISTENING_SUBTITLES:
                self._publish_state_subtitle(self._IDLE_SUBTITLE)

    def _publish_state_subtitle(self, text: str) -> None:
        """Emit a state-label subtitle without recording history."""
        self._subtitle = text
        self.subtitleChanged.emit(text)
        logger.debug("Bridge: state subtitle → %r", text)

    @Slot(str)
    def set_mode(self, state: str) -> None:
        self.set_core_state(state)

    # ── Window mode ───────────────────────────────────────────────────

    @Property(str, notify=windowModeChanged)
    def windowMode(self) -> str:
        return self._window_mode

    @windowMode.setter
    def windowMode(self, mode: str) -> None:
        valid = {"fullscreen", "floating_orb", "edge_dock", "system_tray"}
        if mode not in valid:
            logger.warning("Bridge: unknown window mode %r", mode)
            return
        if self._window_mode != mode:
            self._window_mode = mode
            self.windowModeChanged.emit(mode)
            logger.debug("Bridge: windowMode → %s", mode)

    @Slot(str)
    def set_window_mode(self, mode: str) -> None:
        self.windowMode = mode

    # ── Subtitles / Conversation History ─────────────────────────────

    @Property(list, notify=conversationHistoryChanged)
    def conversationHistory(self) -> list:
        return self._conversation_history

    @Slot(str)
    def show_subtitle(self, text: str) -> None:
        cleaned = (text or "").strip()

        if cleaned in self._STATE_SUBTITLES.values():
            if self._core_state == "thinking" and cleaned == self._STATE_SUBTITLES["listening"]:
                logger.debug("Bridge: corrected stale listening subtitle while thinking")
                cleaned = self._STATE_SUBTITLES["thinking"]
            elif self._core_state == "listening" and cleaned == self._STATE_SUBTITLES["thinking"]:
                logger.debug("Bridge: corrected stale thinking subtitle while listening")
                cleaned = self._STATE_SUBTITLES["listening"]
            elif self._core_state == "speaking" and cleaned in self._STATE_SUBTITLES.values():
                logger.debug("Bridge: ignored stale state subtitle while speaking")
                return

        if cleaned in self._STALE_LISTENING_SUBTITLES and self._core_state == "idle":
            cleaned = self._IDLE_SUBTITLE

        self._subtitle = cleaned
        self.subtitleChanged.emit(cleaned)
        if cleaned:
            self.add_conversation_entry("JARVIS", cleaned)

    @Slot(str, str)
    def add_conversation_entry(self, speaker: str, text: str) -> None:
        if not text:
            return
        import datetime as _dt
        entry = {
            "speaker": speaker,
            "text": text,
            "timestamp": _dt.datetime.now().strftime("%H:%M:%S"),
        }
        self._conversation_history.append(entry)
        if len(self._conversation_history) > 50:
            self._conversation_history = self._conversation_history[-50:]
        self.conversationHistoryChanged.emit()

    # ── Wake word ─────────────────────────────────────────────────────

    @Property(bool, notify=wakeActiveChanged)
    def wakeActive(self) -> bool:
        return self._wake_active

    @wakeActive.setter
    def wakeActive(self, active: bool) -> None:
        if self._wake_active != active:
            self._wake_active = active
            self.wakeActiveChanged.emit(active)

    # ── Voice energy ──────────────────────────────────────────────────

    @Slot(float)
    def set_mic_energy(self, energy: float) -> None:
        self._mic_energy = max(0.0, min(1.0, energy))
        self.micEnergyChanged.emit(self._mic_energy)

    @Slot(float)
    def set_assistant_energy(self, energy: float) -> None:
        self._assistant_energy = max(0.0, min(1.0, energy))
        self.assistantEnergyChanged.emit(self._assistant_energy)

    # ── Status ────────────────────────────────────────────────────────

    @Slot(bool)
    def set_internet_status(self, ok: bool) -> None:
        if self._internet_ok != ok:
            self._internet_ok = ok
            self.internetStatusChanged.emit(ok)

    @Slot(bool)
    def set_mic_status(self, ok: bool) -> None:
        if self._mic_ok != ok:
            self._mic_ok = ok
            self.micStatusChanged.emit(ok)

    @Slot(bool)
    def set_speaker_status(self, ok: bool) -> None:
        if self._speaker_ok != ok:
            self._speaker_ok = ok
            self.speakerStatusChanged.emit(ok)

    @Slot(bool)
    def set_provider_status(self, ok: bool) -> None:
        self.set_speaker_status(ok)

    @Slot(bool)
    def set_llm_status(self, ok: bool) -> None:
        self.set_internet_status(ok)

    @Slot(float)
    def set_cpu_usage(self, pct: float) -> None:
        if abs(pct - self._cpu) <= _THROTTLE_DELTA and self._cpu != 0.0:
            return
        self._cpu = pct
        self.cpuUsageChanged.emit(pct)

    @Slot(float)
    def set_ram_usage(self, pct: float) -> None:
        if abs(pct - self._ram) <= _THROTTLE_DELTA and self._ram != 0.0:
            return
        self._ram = pct
        self.ramUsageChanged.emit(pct)

    @Slot(float)
    def set_memory_usage(self, pct: float) -> None:
        self.set_ram_usage(pct)

    @Slot(float)
    def set_gpu_usage(self, pct: float) -> None:
        if abs(pct - self._gpu) <= _THROTTLE_DELTA and self._gpu != 0.0:
            return
        self._gpu = pct
        self.gpuUsageChanged.emit(pct)

    @Slot(float)
    def set_disk_usage(self, pct: float) -> None:
        if abs(pct - self._disk) <= _THROTTLE_DELTA and self._disk != 0.0:
            return
        self._disk = pct
        self.diskUsageChanged.emit(pct)

    @Slot(float)
    def set_battery(self, pct: float) -> None:
        if abs(pct - self._battery) <= _THROTTLE_DELTA and self._battery != -1.0:
            return
        self._battery = pct
        self.batteryChanged.emit(pct)

    @Slot(str)
    def set_provider(self, name: str) -> None:
        if self._provider != name:
            self._provider = name
            self.providerChanged.emit(name)

    @Slot(str)
    def set_model(self, name: str) -> None:
        if self._model != name:
            self._model = name
            self.modelChanged.emit(name)

    @Slot(str)
    def set_current_task(self, task: str) -> None:
        if self._task != task:
            self._task = task
            self.currentTaskChanged.emit(task)

    # ── Sidebar ───────────────────────────────────────────────────────

    @Property(bool, notify=sidebarVisibleChanged)
    def sidebarVisible(self) -> bool:
        return self._sidebar_visible

    @sidebarVisible.setter
    def sidebarVisible(self, visible: bool) -> None:
        if self._sidebar_visible != visible:
            self._sidebar_visible = visible
            self.sidebarVisibleChanged.emit(visible)

    @Slot()
    def toggle_sidebar(self) -> None:
        self.sidebarVisible = not self._sidebar_visible

    @Slot(str)
    def set_sidebar_section(self, section: str) -> None:
        if self._sidebar_section != section:
            self._sidebar_section = section
            self.sidebarSectionChanged.emit(section)

    # ── Window minimize ───────────────────────────────────────────────

    minimizeRequested = Signal()

    @Slot()
    def minimize_window(self) -> None:
        self.minimizeRequested.emit()

    # ── Clean shutdown ────────────────────────────────────────────────

    def stop_timers(self) -> None:
        """Stop all internal timers. Call during shutdown before quit."""
        if self._clock_timer is not None:
            self._clock_timer.stop()
            logger.debug("Bridge: clock timer stopped")
        if getattr(self, "_backend_monitor", None) is not None:
            self._backend_monitor.stop()
            logger.debug("Bridge: backend monitor timer stopped")

    @Slot()
    def quit_app(self) -> None:
        logger.info("Bridge: clean shutdown requested")
        self.stop_timers()
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.quit()

    # ── Internal ──────────────────────────────────────────────────────

    def _tick(self) -> None:
        self.clockChanged.emit(datetime.datetime.now().strftime("%H:%M:%S"))
