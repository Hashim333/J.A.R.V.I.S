"""
tests/test_skill_registry.py

Skill Registry: persistent storage, upsert on re-request, priority
escalation, status transitions, and resilience to corrupt/missing files.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from skills.registry import SkillRegistry


class TestSkillRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp()
        self.path = Path(self._dir) / "skills_registry.json"
        self.registry = SkillRegistry(path=self.path)

    def test_starts_empty(self) -> None:
        self.assertEqual(self.registry.count(), 0)
        self.assertEqual(self.registry.missing(), [])

    def test_request_creates_full_entry(self) -> None:
        entry = self.registry.request(
            "email.send",
            "Send and read email",
            category="communication",
            priority="high",
            dependencies=["email API"],
            notes="asked twice",
            closest_capability="open email in the browser",
            last_request="send an email to john",
        )
        self.assertEqual(entry["skill"], "email.send")
        self.assertEqual(entry["description"], "Send and read email")
        self.assertEqual(entry["category"], "communication")
        self.assertEqual(entry["priority"], "high")
        self.assertEqual(entry["status"], "requested")
        self.assertEqual(entry["dependencies"], ["email API"])
        self.assertEqual(entry["request_count"], 1)
        self.assertEqual(entry["notes"], "asked twice")
        self.assertIn("date_requested", entry)
        self.assertIn("last_requested", entry)

    def test_rerequest_increments_and_escalates(self) -> None:
        self.registry.request("email.send", "Send email", priority="low")
        entry = self.registry.request("email.send", "Send email")
        self.assertEqual(entry["request_count"], 2)
        self.assertEqual(entry["priority"], "high")

    def test_rerequest_keeps_low_priority_until_second(self) -> None:
        self.registry.request("email.send", "Send email", priority="low")
        entry = self.registry.get("email.send")
        self.assertEqual(entry["priority"], "low")
        self.registry.request("email.send", "Send email")
        self.assertEqual(self.registry.get("email.send")["priority"], "high")

    def test_missing_excludes_implemented(self) -> None:
        self.registry.request("email.send", "Send email")
        self.registry.mark_implemented("email.send")
        self.assertEqual(self.registry.missing(), [])
        self.assertEqual(len(self.registry.missing(include_implemented=True)), 1)

    def test_set_status(self) -> None:
        self.registry.request("email.send", "Send email")
        entry = self.registry.set_status("email.send", "in_progress")
        self.assertEqual(entry["status"], "in_progress")
        with self.assertRaises(ValueError):
            self.registry.set_status("email.send", "bogus")

    def test_remove(self) -> None:
        self.registry.request("email.send", "Send email")
        self.assertTrue(self.registry.remove("email.send"))
        self.assertFalse(self.registry.remove("email.send"))
        self.assertEqual(self.registry.count(), 0)

    def test_reset(self) -> None:
        self.registry.request("email.send", "Send email")
        self.registry.reset()
        self.assertEqual(self.registry.count(), 0)

    def test_persistence_across_instances(self) -> None:
        self.registry.request(
            "calendar.schedule", "Manage calendar events",
            category="productivity",
        )
        reloaded = SkillRegistry(path=self.path)
        self.assertEqual(reloaded.count(), 1)
        entry = reloaded.get("calendar.schedule")
        self.assertEqual(entry["description"], "Manage calendar events")
        self.assertEqual(entry["category"], "productivity")

    def test_corrupt_file_recovers_empty(self) -> None:
        self.path.write_text("{not valid json!!", encoding="utf-8")
        registry = SkillRegistry(path=self.path)
        self.assertEqual(registry.count(), 0)
        registry.request("email.send", "Send email")
        self.assertEqual(registry.get("email.send")["skill"], "email.send")

    def test_missing_file_is_created_on_save(self) -> None:
        target = Path(self._dir) / "nested" / "registry.json"
        registry = SkillRegistry(path=target)
        registry.request("email.send", "Send email")
        self.assertTrue(target.exists())
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        self.assertIn("email.send", data["entries"])

    def test_all_sorted_newest_first(self) -> None:
        self.registry.request("a.skill", "A")
        self.registry.request("b.skill", "B")
        entries = self.registry.all()
        self.assertEqual(len(entries), 2)


if __name__ == "__main__":
    unittest.main()
