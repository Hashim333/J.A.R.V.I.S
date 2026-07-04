"""
services/base_service.py

Defines BaseService: the common interface every long-running
background service (Wake Word, Voice Recognition, Speaker
Verification, Text-to-Speech, Vision/OCR, Security Monitor,
Malware/File Watchdog, Network Monitor, Scheduler, Notification
Service, Memory Service, Background Automation Service, ...) must
implement in order to be managed by ServiceManager.

This module knows nothing about ServiceManager, Brain, Parser,
Planner, Executor, Registry, or any Handler. It only describes the
shape a service must have. ServiceManager depends on this shape;
concrete services depend on this shape; nothing here depends on them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum


class ServiceStatus(Enum):
    """
    Lifecycle states a service can be in.

    STOPPED:  Not initialized, or fully stopped/shutdown. Default
              state before initialize() has ever been called, and the
              state after stop()/shutdown() complete successfully.
    STARTING: initialize() and/or start() are currently in progress.
    RUNNING:  start() completed successfully; the service is active.
    STOPPING: stop() or shutdown() is currently in progress.
    FAILED:   initialize(), start(), or restart() raised an exception.
    """

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class BaseService(ABC):
    """
    Abstract base class for every background service managed by
    ServiceManager.

    Concrete subclasses (implemented in later milestones) must
    provide initialize(), start(), and stop(). restart() has a
    sensible default (stop then start) but may be overridden by a
    subclass that needs a different restart strategy.

    A service tracks its own ServiceStatus via the protected
    self._status attribute, exposed read-only through the status
    property. BaseService itself never talks to ServiceManager -- it
    has no reference back to it and does not know it is being
    managed.

    Attributes:
        name: A short, unique, human-readable identifier for this
            service (e.g. "wake_word", "tts"). Used by ServiceManager
            as the registration key and in status/log output.
    """

    def __init__(self, name: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("BaseService name must be a non-empty string.")
        self._name = name
        self._status: ServiceStatus = ServiceStatus.STOPPED

    @property
    def name(self) -> str:
        """The unique name this service was registered under."""
        return self._name

    @property
    def status(self) -> ServiceStatus:
        """The service's current lifecycle state."""
        return self._status

    def _set_status(self, status: ServiceStatus) -> None:
        """
        Update this service's lifecycle state.

        Intended to be called by ServiceManager (and, if a subclass
        needs to reflect an internal state change, by the subclass
        itself) rather than by unrelated code. Kept as a plain method
        rather than a public setter so status transitions read as a
        deliberate action, not an incidental attribute assignment.
        """
        if not isinstance(status, ServiceStatus):
            raise TypeError(
                f"status must be a ServiceStatus, got {type(status).__name__!r}"
            )
        self._status = status

    @abstractmethod
    def initialize(self) -> None:
        """
        Perform one-time setup required before the service can start
        (e.g. loading a model, opening a connection, allocating
        resources). Called once by ServiceManager before start().

        Implementations should raise on failure; ServiceManager is
        responsible for catching exceptions and marking the service
        FAILED.
        """
        raise NotImplementedError

    @abstractmethod
    def start(self) -> None:
        """
        Start the service's ongoing work (e.g. spin up a background
        thread, begin listening). Called by ServiceManager after
        initialize() has succeeded.

        Implementations should raise on failure; ServiceManager is
        responsible for catching exceptions and marking the service
        FAILED.
        """
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """
        Stop the service's ongoing work without necessarily releasing
        every resource acquired in initialize() (a stopped service may
        later be started again). Must be safe to call even if the
        service is already stopped.

        Implementations should raise on failure; ServiceManager is
        responsible for catching exceptions and marking the service
        FAILED.
        """
        raise NotImplementedError

    def shutdown(self) -> None:
        """
        Fully release any resources acquired by this service,
        including those from initialize(). Called once by
        ServiceManager when the application is exiting.

        Default implementation just calls stop(). Subclasses that
        acquire resources in initialize() beyond what stop() releases
        (e.g. closing a persistent connection) should override this
        and call super().shutdown() or stop() as part of their own
        cleanup.
        """
        self.stop()

    def restart(self) -> None:
        """
        Restart the service.

        Default implementation calls stop() followed by start(). A
        subclass may override this if it needs a different restart
        strategy (e.g. reinitializing rather than just stop/start).
        """
        self.stop()
        self.start()