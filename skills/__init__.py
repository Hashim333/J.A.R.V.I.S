"""
skills/

Skill Awareness & Missing Capability Manager.

The Skill Manager makes JARVIS behave like an intelligent assistant that
understands requests even when it cannot execute them:

  * Every request is classified against a data-driven capability catalog.
  * Known capabilities flow through the normal Parser/Planner/Executor.
  * Unknown requests that map to a known-but-unimplemented capability are
    acknowledged, registered in the persistent Skill Registry, and answered
    with the closest available capability.
  * Meta commands ("what can you do?", "what skills are missing?", ...) are
    answered deterministically from the registry and catalog.

Future skills are added as plugins: append a ``Capability`` entry to
``skills/capability.py`` (and, once it is executable, set ``implemented``).
No core assistant code has to change.
"""

from skills.capability import Capability, CATALOG
from skills.manager import SkillManager
from skills.registry import SkillRegistry

__all__ = ["Capability", "CATALOG", "SkillManager", "SkillRegistry"]
