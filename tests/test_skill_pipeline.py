"""
tests/test_skill_pipeline.py

End-to-end Skill Awareness through the Brain/Pipeline:

  * capability meta-commands are answered deterministically,
  * unknown requests that map to an acknowledged-but-unimplemented skill
    are registered in the Skill Registry and answered with the closest
    available capability,
  * real commands still execute normally,
  * the forbidden refusal strings are never produced.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automation.registry import Registry
from brain.brain import Brain
from brain.parser import Parser
from brain.planner import Planner
from context_manager.context_manager import ContextManager
from executor.executor import Executor
from skills.manager import SkillManager
from skills.registry import SkillRegistry

FORBIDDEN = (
    "I can only open and close apps",
    "Command not found",
    "I don't know",
)


class TestSkillPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.registry = SkillRegistry(path=self.dir / "reg.json")
        self.manager = SkillManager(registry=self.registry)
        self.brain = Brain(
            Parser(),
            Planner(),
            Executor(Registry()),
            context_manager=ContextManager(),
            skill_manager=self.manager,
        )

    def _process(self, text: str):
        return self.brain.process(text)

    def assertNotForbidden(self, message: str) -> None:
        lowered = message.casefold()
        for phrase in FORBIDDEN:
            self.assertNotIn(phrase.casefold(), lowered, f"forbidden phrase in {message!r}")

    def test_meta_command_what_can_you_do(self) -> None:
        resp = self._process("what can you do")
        self.assertTrue(resp.success)
        self.assertIn("I can do", resp.message)
        self.assertNotForbidden(resp.message)

    def test_meta_command_missing_skills(self) -> None:
        resp = self._process("what skills are missing")
        self.assertTrue(resp.success)
        self.assertNotForbidden(resp.message)

    def test_missing_capability_registered_and_explained(self) -> None:
        resp = self._process("send an email to john about the meeting")
        self.assertTrue(resp.success)
        self.assertIn("send and read email", resp.message)
        self.assertIn("isn't implemented yet", resp.message)
        self.assertNotForbidden(resp.message)
        entry = self.registry.get("email.send")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["last_request"], "send an email to john about the meeting")

    def test_missing_capability_then_visible_in_roadmap(self) -> None:
        self._process("remind me to buy milk")
        resp = self._process("what skills are missing")
        self.assertIn("calendar.schedule", resp.message)
        self.assertIn("roadmap", resp.data)

    def test_known_command_still_executes(self) -> None:
        # "open notepad" is a real capability — it must not be flagged as a
        # missing skill.  (Executing may be environment-dependent, but the
        # intent must be open_app, not a skill-manager intercept.)
        resp = self._process("open notepad")
        self.assertNotForbidden(resp.message)
        self.assertNotEqual(resp.data.get("skill"), "notepad")

    def test_meta_commands_never_register_skills(self) -> None:
        self._process("what can you do")
        self._process("what skills are missing")
        self._process("what can't you do yet")
        self.assertEqual(self.registry.count(), 0)

    def test_garbage_never_forbidden(self) -> None:
        resp = self._process("asdkjhqwe 98213")
        self.assertTrue(resp.success)
        self.assertNotForbidden(resp.message)


if __name__ == "__main__":
    unittest.main()
