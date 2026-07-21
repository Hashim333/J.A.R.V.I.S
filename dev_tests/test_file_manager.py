"""
dev_tests/test_file_manager.py

Comprehensive unit tests for the File & Document Manager.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from brain.parser import Parser
from brain.planner import Planner
from brain.parsed_command import ParsedCommand
from memory.file_memory import FileMemory


# =========================================================================
# Parser tests
# =========================================================================

class TestParserFileCommands(unittest.TestCase):
    """Tests for file command parsing in Parser."""

    def setUp(self) -> None:
        self.parser = Parser()

    # --- Open file ---

    def test_open_my_file(self) -> None:
        parsed = self.parser.parse("open my resume")
        self.assertEqual(parsed.intent, "open_file")
        self.assertEqual(parsed.entities.get("file_query"), "resume")

    def test_open_the_file(self) -> None:
        parsed = self.parser.parse("open the invoice")
        self.assertEqual(parsed.intent, "open_file")
        self.assertEqual(parsed.entities.get("file_query"), "invoice")

    def test_open_this_file(self) -> None:
        parsed = self.parser.parse("open this report")
        self.assertEqual(parsed.intent, "open_file")
        self.assertEqual(parsed.entities.get("file_query"), "report")

    def test_open_file_with_extension(self) -> None:
        parsed = self.parser.parse("open report.pdf")
        self.assertEqual(parsed.intent, "open_file")
        self.assertEqual(parsed.entities.get("file_query"), "report.pdf")

    def test_open_file_with_format_word(self) -> None:
        parsed = self.parser.parse("open invoice pdf")
        self.assertEqual(parsed.intent, "open_file")
        self.assertEqual(parsed.entities.get("file_query"), "invoice pdf")

    def test_open_app_still_works(self) -> None:
        parsed = self.parser.parse("open notepad")
        self.assertEqual(parsed.intent, "open_app")

    def test_open_website_still_works(self) -> None:
        parsed = self.parser.parse("open google")
        self.assertEqual(parsed.intent, "open_website")

    # --- Find file ---

    def test_find_my_file(self) -> None:
        parsed = self.parser.parse("find my resume")
        self.assertEqual(parsed.intent, "find_file")
        self.assertEqual(parsed.entities.get("file_query"), "resume")

    def test_find_the_file(self) -> None:
        parsed = self.parser.parse("find the invoice")
        self.assertEqual(parsed.intent, "find_file")
        self.assertEqual(parsed.entities.get("file_query"), "invoice")

    def test_find_pdf(self) -> None:
        parsed = self.parser.parse("find invoice pdf")
        self.assertEqual(parsed.intent, "find_file")
        self.assertEqual(parsed.entities.get("file_query"), "invoice pdf")

    def test_find_with_for(self) -> None:
        parsed = self.parser.parse("find for my resume")
        self.assertEqual(parsed.intent, "find_file")
        self.assertEqual(parsed.entities.get("file_query"), "resume")

    def test_find_web_search_still_works(self) -> None:
        parsed = self.parser.parse("find python tutorial")
        self.assertIn(parsed.intent, ("search", "find_file"))

    def test_locate_file(self) -> None:
        parsed = self.parser.parse("locate my resume")
        self.assertEqual(parsed.intent, "find_file")

    # --- Open file location ---

    def test_show_folder_containing(self) -> None:
        parsed = self.parser.parse("show folder containing my resume")
        self.assertEqual(parsed.intent, "open_file_location")
        self.assertEqual(parsed.entities.get("file_query"), "my resume")

    def test_open_file_location(self) -> None:
        parsed = self.parser.parse("open file location")
        self.assertEqual(parsed.intent, "open_file_location")

    def test_open_containing_folder(self) -> None:
        parsed = self.parser.parse("open containing folder")
        self.assertEqual(parsed.intent, "open_file_location")

    def test_show_in_folder(self) -> None:
        parsed = self.parser.parse("show in folder report.docx")
        self.assertEqual(parsed.intent, "open_file_location")

    # --- Copy / Move / Rename / Delete ---

    def test_copy_file(self) -> None:
        parsed = self.parser.parse("copy invoice.pdf to documents")
        self.assertEqual(parsed.intent, "copy_file")
        self.assertEqual(parsed.entities.get("source"), "invoice.pdf")
        self.assertEqual(parsed.entities.get("destination"), "documents")

    def test_move_file(self) -> None:
        parsed = self.parser.parse("move report.docx to desktop")
        self.assertEqual(parsed.intent, "move_file")
        self.assertEqual(parsed.entities.get("source"), "report.docx")
        self.assertEqual(parsed.entities.get("destination"), "desktop")

    def test_rename_file(self) -> None:
        parsed = self.parser.parse("rename draft.docx to final report")
        self.assertEqual(parsed.intent, "rename_file")
        self.assertEqual(parsed.entities.get("source"), "draft.docx")
        self.assertEqual(parsed.entities.get("new_name"), "final report")

    def test_delete_file(self) -> None:
        parsed = self.parser.parse("delete temp.txt")
        self.assertEqual(parsed.intent, "delete_file")
        self.assertEqual(parsed.entities.get("file_query"), "temp.txt")

    def test_remove_file(self) -> None:
        parsed = self.parser.parse("remove old backup.zip")
        self.assertEqual(parsed.intent, "delete_file")
        self.assertEqual(parsed.entities.get("file_query"), "old backup.zip")

    # --- Negative cases (should NOT be file commands) ---

    def test_open_known_app_not_file(self) -> None:
        parsed = self.parser.parse("open chrome")
        self.assertEqual(parsed.intent, "open_app")

    def test_open_known_website_not_file(self) -> None:
        parsed = self.parser.parse("open youtube")
        self.assertEqual(parsed.intent, "open_website")

    def test_open_downloads_special_folder(self) -> None:
        parsed = self.parser.parse("open downloads")
        self.assertEqual(parsed.intent, "open_special_folder")

    def test_find_single_word_web_search(self) -> None:
        parsed = self.parser.parse("find python")
        self.assertEqual(parsed.intent, "search")


# =========================================================================
# Planner tests
# =========================================================================

class TestPlannerFileIntents(unittest.TestCase):
    """Tests for file intent builders in Planner."""

    def setUp(self) -> None:
        self.planner = Planner()

    def _plan(self, intent: str, entities: dict) -> ParsedCommand:
        return ParsedCommand(
            raw_text="test",
            intent=intent,
            entities=entities,
        )

    def test_open_file_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("open_file", {"file_query": "resume.pdf"}))
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].action, "open_file")
        self.assertEqual(plan.steps[0].parameters["file_query"], "resume.pdf")

    def test_find_file_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("find_file", {"file_query": "invoice pdf"}))
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].action, "find_file")

    def test_open_file_location_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("open_file_location", {"file_query": "report.docx"}))
        self.assertEqual(plan.steps[0].action, "open_file_location")

    def test_copy_file_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("copy_file", {"source": "a.pdf", "destination": "docs"}))
        self.assertEqual(plan.steps[0].action, "copy_file")
        self.assertEqual(plan.steps[0].parameters["source"], "a.pdf")

    def test_move_file_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("move_file", {"source": "a.pdf", "destination": "docs"}))
        self.assertEqual(plan.steps[0].action, "move_file")

    def test_rename_file_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("rename_file", {"source": "draft.docx", "new_name": "final.docx"}))
        self.assertEqual(plan.steps[0].action, "rename_file")

    def test_delete_file_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("delete_file", {"file_query": "temp.txt"}))
        self.assertEqual(plan.steps[0].action, "delete_file")
        self.assertTrue(plan.metadata.get("requires_confirmation", False))


# =========================================================================
# File memory tests
# =========================================================================

class TestFileMemory(unittest.TestCase):
    """Tests for FileMemory persistence and query."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.storage = os.path.join(self.tmp_dir, "test_memory.json")
        self.memory = FileMemory(storage_path=self.storage)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_record_access(self) -> None:
        self.memory.record_access(r"C:\Users\Test\Documents\resume.pdf")
        freq = self.memory.get_frequently_used(limit=10)
        self.assertEqual(len(freq), 1)
        self.assertEqual(freq[0]["name"], "resume.pdf")

    def test_multiple_accesses(self) -> None:
        path = r"C:\Users\Test\Documents\resume.pdf"
        self.memory.record_access(path)
        self.memory.record_access(path)
        freq = self.memory.get_frequently_used()
        self.assertEqual(freq[0]["access_count"], 2)

    def test_search_with_memory(self) -> None:
        self.memory.record_access(r"C:\Users\Test\Documents\resume.pdf")
        self.memory.record_access(r"C:\Users\Test\Documents\invoice.pdf")
        results = self.memory.search_with_memory("resume")
        self.assertEqual(len(results), 1)
        self.assertIn("resume", results[0]["name"])

    def test_search_with_memory_no_match(self) -> None:
        self.memory.record_access(r"C:\Users\Test\Documents\resume.pdf")
        results = self.memory.search_with_memory("nonexistent")
        self.assertEqual(len(results), 0)

    def test_get_recent_files(self) -> None:
        self.memory.record_access(r"C:\Users\Test\Documents\resume.pdf")
        recent = self.memory.get_recent_files(days=30)
        self.assertEqual(len(recent), 1)

    def test_clear(self) -> None:
        self.memory.record_access(r"C:\Users\Test\Documents\resume.pdf")
        self.memory.clear()
        self.assertEqual(len(self.memory.get_frequently_used()), 0)

    def test_persistence(self) -> None:
        """Data should survive reloading from disk."""
        self.memory.record_access(r"C:\Users\Test\Documents\resume.pdf")
        del self.memory
        memory2 = FileMemory(storage_path=self.storage)
        freq = memory2.get_frequently_used()
        self.assertEqual(len(freq), 1)
        self.assertEqual(freq[0]["name"], "resume.pdf")

    def test_empty_memory(self) -> None:
        self.assertEqual(self.memory.get_frequently_used(), [])
        self.assertEqual(self.memory.search_with_memory("anything"), [])

    def test_special_chars_in_path(self) -> None:
        path = r"C:\Users\Test\My Documents\project report (final).pdf"
        self.memory.record_access(path)
        freq = self.memory.get_frequently_used()
        self.assertEqual(len(freq), 1)


# =========================================================================
# File operations tests
# =========================================================================

class TestFileOps(unittest.TestCase):
    """Tests for file operations using real temporary files."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.tmp_dir, "test_document.txt")
        with open(self.test_file, "w") as f:
            f.write("Hello, world!")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # We test the handler's pathway indirectly via the file_ops module

    def test_open_file_success(self) -> None:
        from automation.file_ops import open_file
        result = open_file(self.test_file)
        self.assertTrue(result["success"])

    def test_open_file_not_found(self) -> None:
        from automation.file_ops import open_file
        result = open_file("nonexistent_file_xyz.txt")
        self.assertFalse(result["success"])
        self.assertTrue(result.get("needs_search", False))

    def test_find_file_by_name(self) -> None:
        from automation.file_ops import find_file
        results = find_file("test_document", search_folders=[self.tmp_dir])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "test_document.txt")

    def test_find_file_no_match(self) -> None:
        from automation.file_ops import find_file
        results = find_file("zzzz_nothing", search_folders=[self.tmp_dir])
        self.assertEqual(len(results), 0)

    def test_rename_file(self) -> None:
        from automation.file_ops import rename_file
        new_name = "renamed_doc.txt"
        result = rename_file(self.test_file, new_name)
        self.assertTrue(result["success"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp_dir, new_name)))
        self.assertFalse(os.path.exists(self.test_file))

    def test_copy_file(self) -> None:
        from automation.file_ops import copy_file
        dest_dir = os.path.join(self.tmp_dir, "subfolder")
        os.makedirs(dest_dir)
        result = copy_file(self.test_file, dest_dir)
        self.assertTrue(result["success"])
        self.assertTrue(os.path.exists(os.path.join(dest_dir, "test_document.txt")))

    def test_move_file(self) -> None:
        from automation.file_ops import move_file
        dest_dir = os.path.join(self.tmp_dir, "subfolder")
        os.makedirs(dest_dir)
        result = move_file(self.test_file, dest_dir)
        self.assertTrue(result["success"])
        self.assertTrue(os.path.exists(os.path.join(dest_dir, "test_document.txt")))
        self.assertFalse(os.path.exists(self.test_file))

    def test_delete_file_unconfirmed(self) -> None:
        from automation.file_ops import delete_file
        result = delete_file(self.test_file, confirmed=False)
        self.assertTrue(result.get("needs_confirmation", False))
        self.assertTrue(os.path.exists(self.test_file))

    def test_delete_file_confirmed(self) -> None:
        from automation.file_ops import delete_file
        result = delete_file(self.test_file, confirmed=True)
        self.assertTrue(result["success"])
        self.assertFalse(os.path.exists(self.test_file))

    def test_open_containing_folder(self) -> None:
        from automation.file_ops import open_containing_folder
        result = open_containing_folder(self.test_file)
        self.assertTrue(result["success"])

    def test_score_file_match_exact(self) -> None:
        from automation.file_ops import _score_file_match
        import os
        with os.scandir(self.tmp_dir) as it:
            for entry in it:
                score = _score_file_match(entry, "test_document", "test_document", ["test_document"])
                self.assertGreater(score, 0)
                break


# =========================================================================
# Registry integration test
# =========================================================================

class TestRegistryIntegration(unittest.TestCase):
    """Verify file actions are registered and dispatchable."""

    def test_registry_has_file_actions(self) -> None:
        from automation.registry import Registry
        reg = Registry()
        for action in ("open_file", "find_file", "open_file_location",
                        "copy_file", "move_file", "rename_file", "delete_file"):
            self.assertTrue(reg.is_registered(action), f"{action} not registered")

    def test_file_handler_can_run(self) -> None:
        from automation.registry import Registry
        reg = Registry()
        from models.execution_plan import Step
        handler = reg.get_handler("find_file")
        result = handler.run(Step(
            action="find_file",
            target=None,
            parameters={"file_query": "nonexistent"},
        ))
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
