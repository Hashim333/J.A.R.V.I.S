"""
working_memory — Short-term context about the current conversation, task,
and computer state.

Public API
----------
    from working_memory import WorkingMemory

    wm = WorkingMemory()
    wm.start()

    # Add memories from any thread:
    wm.add_command("list files in current directory")
    wm.add_action("listed 3 files: foo.py, bar.py, baz.py")
    wm.set_current_task("implement search feature")

    # Query (read-only):
    snapshot = wm.get_snapshot()         # dict of all active entries
    recent = wm.get_recent_commands(5)
    task = wm.get_current_task()
    summary = wm.summarize()

    wm.stop()

Classes
-------
- ``WorkingMemory`` — thread-safe short-term memory service
- ``MemoryEntry`` — frozen dataclass representing one memory unit
- ``MemoryType`` — enum categorising each entry
"""

from working_memory.model import MemoryEntry, MemoryType
from working_memory.working_memory import WorkingMemory

__all__ = [
    "WorkingMemory",
    "MemoryEntry",
    "MemoryType",
]
