"""
world_model/collectors/ — Domain-specific collectors.

Each collector is a subclass of ``BaseCollector`` and produces a typed
dict fragment that the WorldModel merges into the global snapshot.
"""

from __future__ import annotations

import abc
import logging

logger = logging.getLogger(__name__)


class BaseCollector(abc.ABC):
    """Abstract base for all WorldModel collectors.

    Each collector runs on its own poll interval and produces a dict
    fragment that the WorldModel merges into the snapshot.

    All I/O must happen in ``collect()``, which is called from a
    background worker thread.  Implementations MUST NOT block for more
    than a few hundred milliseconds.
    """

    def __init__(self, poll_interval: float = 5.0) -> None:
        self._poll_interval = poll_interval

    @property
    def poll_interval(self) -> float:
        return self._poll_interval

    @abc.abstractmethod
    def collect(self) -> dict:
        """Collect and return a dict fragment.

        The dict keys must match ``WorldSnapshot`` field names
        (e.g. ``{"applications": [...]}``).  Return an empty dict
        if nothing to report.
        """
        ...
