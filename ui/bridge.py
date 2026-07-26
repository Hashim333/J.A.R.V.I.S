"""
ui/bridge.py

Master Python-to-QML bridge for the JARVIS desktop shell.
"""

from __future__ import annotations

import datetime
import logging
import platform
import time

from PySide6.QtCore import QObject, Signal, Property, Slot, QTimer

logger = logging.getLogger(__name__)


class Bridge(QObject):
    """Single bridge object exposed as 'bridge' in QML."""

    # ── Core state ────────────────────────────────────────────────────
    coreStateChanged = Signal(str)
    _core_state: str = "idle"

    # ── Window mode ───────────────────────────────────────────────────
    windowModeChanged = Signal(str)
    _window_mode: str = "fullscreen"

    # ── Subtitles ─────────────────────────────────────────────────────
    subtitleChanged = Signal(str)

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
            logger.info("Bridge: core → %s", state)

    @Slot(str)
    def set_core_state(self, state: str) -> None:
        self.coreState = state

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

    @Slot(str)
    def set_window_mode(self, mode: str) -> None:
        self.windowMode = mode

    # ── Subtitles ─────────────────────────────────────────────────────

    @Slot(str)
    def show_subtitle(self, text: str) -> None:
        self.subtitleChanged.emit(text)

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
        self._cpu = pct
        self.cpuUsageChanged.emit(pct)

    @Slot(float)
    def set_ram_usage(self, pct: float) -> None:
        self._ram = pct
        self.ramUsageChanged.emit(pct)

    @Slot(float)
    def set_memory_usage(self, pct: float) -> None:
        self.set_ram_usage(pct)

    @Slot(float)
    def set_gpu_usage(self, pct: float) -> None:
        self._gpu = pct
        self.gpuUsageChanged.emit(pct)

    @Slot(float)
    def set_battery(self, pct: float) -> None:
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

    @Slot()
    def quit_app(self) -> None:
        logger.info("Bridge: clean shutdown requested")
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.quit()

    # ── Internal ──────────────────────────────────────────────────────

    def _tick(self) -> None:
        self.clockChanged.emit(datetime.datetime.now().strftime("%H:%M:%S"))
