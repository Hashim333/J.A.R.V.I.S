"""
services/

Lifecycle management for long-running background services (Wake Word,
Voice Recognition, Speaker Verification, Text-to-Speech, Vision/OCR,
Security Monitor, Malware/File Watchdog, Network Monitor, Scheduler,
Notification Service, Memory Service, Background Automation Service,
...).

This package is a sibling to brain/, planner/, executor/, automation/,
voice/, vision/, and config/ -- it is not part of the Brain pipeline
and never imports from it.
"""

from services.base_service import BaseService, ServiceStatus
from services.service_manager import ServiceManager
from services.listener_service import ListenerService
from services.wake_word_service import WakeWordService

__all__ = [
    "BaseService",
    "ServiceStatus",
    "ServiceManager",
    "ListenerService",
    "WakeWordService",
]