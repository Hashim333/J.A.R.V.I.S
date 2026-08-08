"""
tests/test_skill_manager.py

Skill Manager: capability meta-commands, missing-skill classification,
registration, and the guarantee that the forbidden refusal strings are
never produced.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from models.response import Response
from skills.manager import SkillManager
from skills.registry import SkillRegistry

FORBIDDEN = (
    "I can only open and close apps",
    "Command not found",
    "I don't know",
)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.registry = SkillRegistry(path=self.dir / "reg.json")
        self.manager = SkillManager(registry=self.registry)

    def assertNotForbidden(self, text: str) -> None:
        lowered = text.casefold()
        for phrase in FORBIDDEN:
            self.assertNotIn(phrase.casefold(), lowered, f"forbidden phrase in {text!r}")


class TestSkillManagerMetaCommands(_Base):
    def test_what_can_you_do(self) -> None:
        resp = self.manager.answer("what can you do")
        self.assertIsNotNone(resp)
        self.assertTrue(resp.success)
        self.assertIn("open", resp.message)
        self.assertNotForbidden(resp.message)

    def test_capabilities_synonym(self) -> None:
        self.assertIsNotNone(self.manager.answer("what are your capabilities"))

    def test_help(self) -> None:
        self.assertIsNotNone(self.manager.answer("help"))

    def test_missing_skills_empty(self) -> None:
        resp = self.manager.answer("what skills are missing")
        self.assertIsNotNone(resp)
        self.assertIn("roadmap", resp.message)

    def test_missing_skills_with_entries(self) -> None:
        self.registry.request("email.send", "Send and read email")
        resp = self.manager.answer("show requested features")
        self.assertIsNotNone(resp)
        self.assertIn("email.send", resp.message)
        self.assertIn("roadmap", resp.data)

    def test_unfinished_skills_alias(self) -> None:
        self.registry.request("email.send", "Send and read email")
        resp = self.manager.answer("show unfinished skills")
        self.assertIsNotNone(resp)
        self.assertIn("email.send", resp.message)

    def test_cannot_do(self) -> None:
        resp = self.manager.answer("what can't you do yet")
        self.assertIsNotNone(resp)
        self.assertIn("don't have yet", resp.message)
        self.assertNotForbidden(resp.message)

    def test_cannot_do_no_apostrophe(self) -> None:
        self.assertIsNotNone(self.manager.answer("what cant you do"))

    def test_non_meta_passes_through(self) -> None:
        self.assertIsNone(self.manager.answer("open chrome"))
        self.assertIsNone(self.manager.answer("tell me a joke"))
        self.assertIsNone(self.manager.answer("increase the volume"))


class TestSkillManagerClassification(_Base):
    def test_email_request(self) -> None:
        match = self.manager.classify_missing("send an email to john about the project")
        self.assertIsNotNone(match)
        self.assertEqual(match.capability.name, "email.send")

    def test_messaging_request(self) -> None:
        match = self.manager.classify_missing("whatsapp my friend")
        self.assertIsNotNone(match)
        self.assertEqual(match.capability.name, "messaging.send")

    def test_reminder_request(self) -> None:
        match = self.manager.classify_missing("remind me to buy milk at 5")
        self.assertIsNotNone(match)
        self.assertEqual(match.capability.name, "calendar.schedule")

    def test_home_automation_request(self) -> None:
        match = self.manager.classify_missing("turn on the lights")
        self.assertIsNotNone(match)
        self.assertEqual(match.capability.name, "home.automation")

    def test_weak_signal_does_not_match(self) -> None:
        self.assertIsNone(self.manager.classify_missing("hello there"))
        self.assertIsNone(self.manager.classify_missing("what time is it"))

    def test_implemented_capability_not_flagged_missing(self) -> None:
        # The parser handles "open chrome" in the pipeline; the manager
        # must not classify it as a missing skill.
        self.assertIsNone(self.manager.classify_missing("open chrome"))

    def test_empty_and_garbage(self) -> None:
        self.assertIsNone(self.manager.classify_missing(""))
        self.assertIsNone(self.manager.classify_missing("asdf 123 !!!"))


class TestSkillManagerResponses(_Base):
    def test_respond_missing_registers_and_explains(self) -> None:
        match = self.manager.classify_missing("send an email to john")
        resp = self.manager.respond_missing("send an email to john", match)
        self.assertIsInstance(resp, Response)
        self.assertTrue(resp.success)
        self.assertIn("send and read email", resp.message)
        self.assertIn("isn't implemented yet", resp.message)
        self.assertIn("closest thing", resp.message)
        self.assertIn("email.send", resp.message)
        self.assertNotForbidden(resp.message)
        self.assertEqual(resp.data["skill"], "email.send")
        self.assertEqual(resp.data["category"], "communication")
        entry = self.registry.get("email.send")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["last_request"], "send an email to john")

    def test_rerequest_bumps_count(self) -> None:
        match = self.manager.classify_missing("send an email")
        self.manager.respond_missing("send an email", match)
        self.manager.respond_missing("send another email", match)
        entry = self.registry.get("email.send")
        self.assertEqual(entry["request_count"], 2)

    def test_respond_unintelligible(self) -> None:
        resp = self.manager.respond_unintelligible("asdkjhqwe 98213")
        self.assertTrue(resp.success)
        self.assertIn("rephrase", resp.message)
        self.assertNotForbidden(resp.message)

    def test_speech_confidence_preserved(self) -> None:
        match = self.manager.classify_missing("send an email")
        resp = self.manager.respond_missing("send an email", match, speech_confidence=0.42)
        self.assertEqual(resp.speech_confidence, 0.42)


if __name__ == "__main__":
    unittest.main()
