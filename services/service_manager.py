"""
services/service_manager.py

ServiceManager owns the lifetime of long-running background services
(Wake Word, Voice Recognition, Speaker Verification, Text-to-Speech,
Vision/OCR, Security Monitor, Malware/File Watchdog, Network Monitor,
Scheduler, Notification Service, Memory Service, Background Automation
Service, ...).

ServiceManager is completely independent of the Brain -> Parser ->
Planner -> Executor -> Registry -> Handler pipeline. It does not
resolve commands, does not participate in parsing, planning,
execution, or handler lookup, and never imports anything from
brain/, planner/, executor/, or automation/. It only manages objects
that satisfy the BaseService interface.

This module is deliberately generic: it holds services by name and
calls the same BaseService methods on all of them. Adding a new
service later never requires changing ServiceManager's code -- only
calling manager.register(name, service) with a new BaseService
subclass instance.
"""

from __future__ import annotations

import threading

from services.base_service import BaseService, ServiceStatus


class ServiceManager:
    """
    Registers BaseService instances by name and manages their
    lifecycle: initialize, start, stop, shutdown, restart, and status
    queries.

    Thread-safe: all reads and writes to the internal service map, and
    all lifecycle transitions, are guarded by a single internal lock,
    since services are expected to run on their own threads and may be
    queried or restarted (e.g. by a future watchdog) concurrently with
    normal application flow.

    Constructor takes no arguments. Services are added afterward via
    register().
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._services: dict[str, BaseService] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, name: str, service: BaseService) -> None:
        """
        Register a service under a given name.

        Args:
            name: unique key used to look up this service later. If
                the same name is registered twice, the new service
                replaces the old one -- the caller is responsible for
                stopping the old instance first if that matters.
            service: an object implementing BaseService.

        Raises:
            TypeError: if name is not a string or service is not a
                BaseService instance.
            ValueError: if name is empty/blank.
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Service name must be a non-empty string.")
        if not isinstance(service, BaseService):
            raise TypeError(
                f"service must be a BaseService instance, got "
                f"{type(service).__name__!r}"
            )

        with self._lock:
            self._services[name] = service

    # ------------------------------------------------------------------
    # Lifecycle: bulk operations
    # ------------------------------------------------------------------

    def initialize_all(self) -> dict[str, str]:
        """
        Call initialize() on every registered service.

        A failure in one service's initialize() does not prevent the
        others from being initialized -- ServiceManager iterates all
        services regardless of individual failures.

        Returns:
            A dict mapping service name -> "ok" or an error message,
            so callers (e.g. run.py) can report what happened without
            ServiceManager raising and aborting startup.
        """
        return self._apply_to_all("initialize", ServiceStatus.STARTING, ServiceStatus.STOPPED)

    def start_all(self) -> dict[str, str]:
        """
        Call start() on every registered service.

        Returns:
            A dict mapping service name -> "ok" or an error message.
        """
        return self._apply_to_all("start", ServiceStatus.STARTING, ServiceStatus.RUNNING)

    def stop_all(self) -> dict[str, str]:
        """
        Call stop() on every registered service.

        Returns:
            A dict mapping service name -> "ok" or an error message.
        """
        return self._apply_to_all("stop", ServiceStatus.STOPPING, ServiceStatus.STOPPED)

    def shutdown_all(self) -> dict[str, str]:
        """
        Call shutdown() on every registered service. Intended to be
        called once, when the application is exiting.

        Returns:
            A dict mapping service name -> "ok" or an error message.
        """
        return self._apply_to_all("shutdown", ServiceStatus.STOPPING, ServiceStatus.STOPPED)

    def _apply_to_all(
        self,
        method_name: str,
        in_progress_status: ServiceStatus,
        success_status: ServiceStatus,
    ) -> dict[str, str]:
        """
        Shared helper: call the named lifecycle method on every
        registered service, updating status before/after and
        capturing any exception per-service rather than letting it
        propagate and abort the remaining services.
        """
        results: dict[str, str] = {}
        with self._lock:
            names = list(self._services.keys())

        for name in names:
            results[name] = self._apply_to_one(
                name, method_name, in_progress_status, success_status
            )
        return results

    def _apply_to_one(
        self,
        name: str,
        method_name: str,
        in_progress_status: ServiceStatus,
        success_status: ServiceStatus,
    ) -> str:
        """
        Call the named lifecycle method on a single service by name,
        updating its status and converting any exception into an
        error string rather than raising.
        """
        with self._lock:
            service = self._services.get(name)
            if service is None:
                return f"error: no service registered under {name!r}"
            service._set_status(in_progress_status)

        try:
            method = getattr(service, method_name)
            method()
        except Exception as exc:  # noqa: BLE001 - intentional, broad by design
            with self._lock:
                service._set_status(ServiceStatus.FAILED)
            return f"error: {type(exc).__name__}: {exc}"

        with self._lock:
            service._set_status(success_status)
        return "ok"

    # ------------------------------------------------------------------
    # Lifecycle: single-service operations
    # ------------------------------------------------------------------

    def restart(self, name: str) -> str:
        """
        Restart a single service by name (calls its restart(), which
        by default is stop() then start()).

        Args:
            name: the registered service name.

        Returns:
            "ok" on success, or an "error: ..." string describing what
            went wrong (unknown name, or an exception from the
            service's own restart()).
        """
        with self._lock:
            service = self._services.get(name)
            if service is None:
                return f"error: no service registered under {name!r}"
            service._set_status(ServiceStatus.STARTING)

        try:
            service.restart()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                service._set_status(ServiceStatus.FAILED)
            return f"error: {type(exc).__name__}: {exc}"

        with self._lock:
            service._set_status(ServiceStatus.RUNNING)
        return "ok"

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_status(self, name: str) -> ServiceStatus | None:
        """
        Return the current ServiceStatus for a registered service, or
        None if no service is registered under that name.
        """
        with self._lock:
            service = self._services.get(name)
            return service.status if service is not None else None

    def list_services(self) -> dict[str, ServiceStatus]:
        """
        Return a snapshot mapping every registered service name to its
        current ServiceStatus.
        """
        with self._lock:
            return {
                name: service.status
                for name, service in self._services.items()
            }