"""
tests/test_working_memory.py — Unit tests for the Working Memory service.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest import TestCase

from working_memory import MemoryEntry, MemoryType, WorkingMemory
from working_memory.model import LIST_TYPE_MAX, SINGLETON_TYPES


# ======================================================================
#  Model tests
# ======================================================================

class TestMemoryType(TestCase):
    def test_enum_values(self) -> None:
        self.assertEqual(MemoryType.USER_COMMAND.value, "user_command")
        self.assertEqual(MemoryType.ASSISTANT_ACTION.value, "assistant_action")
        self.assertEqual(MemoryType.PENDING_GOAL.value, "pending_goal")
        self.assertEqual(MemoryType.PENDING_CONFIRMATION.value, "pending_confirmation")
        self.assertEqual(MemoryType.CURRENT_TASK.value, "current_task")
        self.assertEqual(MemoryType.CURRENT_PROJECT.value, "current_project")
        self.assertEqual(MemoryType.CURRENT_APPLICATION.value, "current_application")
        self.assertEqual(MemoryType.CURRENT_FILE.value, "current_file")
        self.assertEqual(MemoryType.CURRENT_BROWSER_TAB.value, "current_browser_tab")
        self.assertEqual(MemoryType.CURRENT_FOLDER.value, "current_folder")
        self.assertEqual(MemoryType.CONVERSATION_CONTEXT.value, "conversation_context")

    def test_singleton_types_defined(self) -> None:
        expected = {
            MemoryType.CURRENT_TASK,
            MemoryType.CURRENT_PROJECT,
            MemoryType.CURRENT_APPLICATION,
            MemoryType.CURRENT_FILE,
            MemoryType.CURRENT_BROWSER_TAB,
            MemoryType.CURRENT_FOLDER,
            MemoryType.CONVERSATION_CONTEXT,
        }
        self.assertEqual(SINGLETON_TYPES, expected)

    def test_list_type_max_defined(self) -> None:
        self.assertEqual(LIST_TYPE_MAX[MemoryType.USER_COMMAND], 20)
        self.assertEqual(LIST_TYPE_MAX[MemoryType.ASSISTANT_ACTION], 20)
        self.assertEqual(LIST_TYPE_MAX[MemoryType.PENDING_GOAL], 50)
        self.assertEqual(LIST_TYPE_MAX[MemoryType.PENDING_CONFIRMATION], 20)


class TestMemoryEntry(TestCase):
    def test_create_entry(self) -> None:
        entry = MemoryEntry(
            id="e1",
            type=MemoryType.USER_COMMAND,
            content="hello",
            timestamp=100.0,
            expires_at=200.0,
            metadata={"foo": "bar"},
        )
        self.assertEqual(entry.id, "e1")
        self.assertEqual(entry.type, MemoryType.USER_COMMAND)
        self.assertEqual(entry.content, "hello")
        self.assertEqual(entry.timestamp, 100.0)
        self.assertEqual(entry.expires_at, 200.0)
        self.assertEqual(entry.metadata, {"foo": "bar"})

    def test_create_entry_minimal(self) -> None:
        entry = MemoryEntry(id="e2", type=MemoryType.PENDING_GOAL, content="goal", timestamp=0.0)
        self.assertIsNone(entry.expires_at)
        self.assertEqual(entry.metadata, {})

    def test_is_expired(self) -> None:
        future = time.time() + 3600
        entry = MemoryEntry(
            id="e3", type=MemoryType.USER_COMMAND, content="x",
            timestamp=0.0, expires_at=future,
        )
        self.assertFalse(entry.is_expired)

        past = time.time() - 10
        expired = MemoryEntry(
            id="e4", type=MemoryType.USER_COMMAND, content="x",
            timestamp=0.0, expires_at=past,
        )
        self.assertTrue(expired.is_expired)

    def test_is_expired_no_expiry(self) -> None:
        entry = MemoryEntry(id="e5", type=MemoryType.CURRENT_TASK, content="task", timestamp=0.0)
        self.assertFalse(entry.is_expired)

    def test_frozen(self) -> None:
        entry = MemoryEntry(id="e6", type=MemoryType.USER_COMMAND, content="x", timestamp=0.0)
        with self.assertRaises(AttributeError):
            entry.content = "y"  # type: ignore[misc]

    def test_age_seconds(self) -> None:
        entry = MemoryEntry(id="e7", type=MemoryType.USER_COMMAND, content="x", timestamp=time.time() - 10)
        self.assertAlmostEqual(entry.age_seconds, 10, delta=1)


# ======================================================================
#  WorkingMemory — Lifecycle
# ======================================================================

class TestLifecycle(TestCase):
    def setUp(self) -> None:
        self.wm = WorkingMemory()

    def tearDown(self) -> None:
        self.wm.stop()

    def test_start_stop(self) -> None:
        self.wm.start()
        self.assertIsNotNone(self.wm._eviction_thread)
        self.assertTrue(self.wm._eviction_thread.is_alive())
        self.wm.stop()
        self.assertFalse(self.wm._eviction_thread.is_alive())

    def test_start_twice(self) -> None:
        self.wm.start()
        t1 = self.wm._eviction_thread
        self.wm.start()  # second call should be no-op
        self.assertIs(self.wm._eviction_thread, t1)
        self.wm.stop()

    def test_stop_without_start(self) -> None:
        # Should not raise
        self.wm.stop()


# ======================================================================
#  WorkingMemory — Add
# ======================================================================

class TestAdd(TestCase):
    def setUp(self) -> None:
        self.wm = WorkingMemory()

    def tearDown(self) -> None:
        self.wm.stop()

    def test_add_command(self) -> None:
        eid = self.wm.add_command("list files")
        entry = self.wm.get(eid)
        assert entry is not None
        self.assertEqual(entry.type, MemoryType.USER_COMMAND)
        self.assertEqual(entry.content, "list files")

    def test_add_action(self) -> None:
        eid = self.wm.add_action("listed 3 files")
        entry = self.wm.get(eid)
        assert entry is not None
        self.assertEqual(entry.type, MemoryType.ASSISTANT_ACTION)
        self.assertEqual(entry.content, "listed 3 files")

    def test_add_goal(self) -> None:
        eid = self.wm.add_goal("implement search")
        entry = self.wm.get(eid)
        assert entry is not None
        self.assertEqual(entry.type, MemoryType.PENDING_GOAL)

    def test_add_confirmation(self) -> None:
        eid = self.wm.add_confirmation("proceed with deletion?")
        entry = self.wm.get(eid)
        assert entry is not None
        self.assertEqual(entry.type, MemoryType.PENDING_CONFIRMATION)

    def test_add_with_explicit_id(self) -> None:
        eid = self.wm.add(MemoryType.USER_COMMAND, "hello", id="myid")
        self.assertEqual(eid, "myid")
        entry = self.wm.get("myid")
        assert entry is not None
        self.assertEqual(entry.content, "hello")

    def test_add_with_metadata(self) -> None:
        eid = self.wm.add(MemoryType.USER_COMMAND, "cmd", metadata={"pid": 1234})
        entry = self.wm.get(eid)
        assert entry is not None
        self.assertEqual(entry.metadata, {"pid": 1234})

    def test_add_with_ttl(self) -> None:
        eid = self.wm.add(MemoryType.USER_COMMAND, "cmd", ttl_seconds=10.0)
        entry = self.wm.get(eid)
        assert entry is not None
        self.assertIsNotNone(entry.expires_at)
        self.assertAlmostEqual(entry.expires_at - entry.timestamp, 10, delta=0.1)

    def test_add_persistent(self) -> None:
        eid = self.wm.add(MemoryType.CURRENT_TASK, "my task")
        entry = self.wm.get(eid)
        assert entry is not None
        self.assertIsNone(entry.expires_at)  # CURRENT_TASK default is None

    def test_singleton_replaces_old(self) -> None:
        self.wm.add(MemoryType.CURRENT_TASK, "old task")
        self.wm.add(MemoryType.CURRENT_TASK, "new task")
        entries = self.wm.query(MemoryType.CURRENT_TASK)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].content, "new task")

    def test_non_singleton_accumulates(self) -> None:
        self.wm.add_command("cmd1")
        self.wm.add_command("cmd2")
        entries = self.wm.query(MemoryType.USER_COMMAND)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].content, "cmd2")  # newest first
        self.assertEqual(entries[1].content, "cmd1")

    def test_list_trim_obeys_max(self) -> None:
        max_cmds = LIST_TYPE_MAX[MemoryType.USER_COMMAND]
        for i in range(max_cmds + 5):
            self.wm.add_command(f"cmd{i}")
        entries = self.wm.query(MemoryType.USER_COMMAND)
        self.assertEqual(len(entries), max_cmds)

    def test_list_trim_removes_oldest(self) -> None:
        max_cmds = LIST_TYPE_MAX[MemoryType.USER_COMMAND]
        for i in range(max_cmds):
            self.wm.add_command(f"cmd{i}")
        # The oldest should be cmd0 … add one more to push it out
        self.wm.add_command("cmd_last")
        entries = self.wm.query(MemoryType.USER_COMMAND)
        self.assertEqual(entries[0].content, "cmd_last")
        self.assertEqual(entries[-1].content, "cmd1")  # cmd0 was evicted


# ======================================================================
#  WorkingMemory — Update
# ======================================================================

class TestUpdate(TestCase):
    def setUp(self) -> None:
        self.wm = WorkingMemory()

    def tearDown(self) -> None:
        self.wm.stop()

    def test_update_content(self) -> None:
        eid = self.wm.add_command("old content")
        ok = self.wm.update(eid, content="new content")
        self.assertTrue(ok)
        entry = self.wm.get(eid)
        assert entry is not None
        self.assertEqual(entry.content, "new content")

    def test_update_metadata(self) -> None:
        eid = self.wm.add_command("cmd")
        ok = self.wm.update(eid, metadata={"key": "val"})
        self.assertTrue(ok)
        entry = self.wm.get(eid)
        assert entry is not None
        self.assertEqual(entry.metadata, {"key": "val"})

    def test_update_extend_ttl(self) -> None:
        eid = self.wm.add(MemoryType.USER_COMMAND, "cmd", ttl_seconds=10.0)
        entry_before = self.wm.get(eid)
        assert entry_before is not None
        old_expiry = entry_before.expires_at
        time.sleep(0.01)
        ok = self.wm.update(eid, extend_ttl=60.0)
        self.assertTrue(ok)
        entry_after = self.wm.get(eid)
        assert entry_after is not None
        self.assertGreater(entry_after.expires_at, old_expiry)

    def test_update_non_existent(self) -> None:
        ok = self.wm.update("nonexistent", content="x")
        self.assertFalse(ok)

    def test_update_preserves_id_and_type(self) -> None:
        eid = self.wm.add_command("original")
        self.wm.update(eid, content="updated")
        entry = self.wm.get(eid)
        assert entry is not None
        self.assertEqual(entry.id, eid)
        self.assertEqual(entry.type, MemoryType.USER_COMMAND)

    def test_update_preserves_timestamp(self) -> None:
        eid = self.wm.add_command("original")
        entry_before = self.wm.get(eid)
        assert entry_before is not None
        time.sleep(0.01)
        self.wm.update(eid, content="updated")
        entry_after = self.wm.get(eid)
        assert entry_after is not None
        self.assertEqual(entry_after.timestamp, entry_before.timestamp)


# ======================================================================
#  WorkingMemory — Query
# ======================================================================

class TestQuery(TestCase):
    def setUp(self) -> None:
        self.wm = WorkingMemory()
        self.wm.add_command("cmd1")
        self.wm.add_command("cmd2")
        self.wm.add_action("act1")
        self.wm.add_action("act2")

    def tearDown(self) -> None:
        self.wm.stop()

    def test_query_all_types(self) -> None:
        results = self.wm.query()
        # Should include both commands and actions
        types = {e.type for e in results}
        self.assertIn(MemoryType.USER_COMMAND, types)
        self.assertIn(MemoryType.ASSISTANT_ACTION, types)

    def test_query_by_type(self) -> None:
        results = self.wm.query(MemoryType.USER_COMMAND)
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r.type, MemoryType.USER_COMMAND)

    def test_query_limit(self) -> None:
        results = self.wm.query(MemoryType.USER_COMMAND, limit=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "cmd2")  # newest first

    def test_query_excludes_expired(self) -> None:
        eid = self.wm.add(MemoryType.USER_COMMAND, "ephemeral", ttl_seconds=0.001)
        time.sleep(0.01)
        self.wm.evict_expired()
        results = self.wm.query(MemoryType.USER_COMMAND, include_expired=False)
        ids = {e.id for e in results}
        self.assertNotIn(eid, ids)

    def test_query_includes_expired_when_requested(self) -> None:
        eid = self.wm.add(MemoryType.USER_COMMAND, "ephemeral", ttl_seconds=0.001)
        time.sleep(0.01)
        # Without evict_expired — the entry is still in _entries but marked expired
        results_with = self.wm.query(
            MemoryType.USER_COMMAND, include_expired=True,
        )
        ids_with = {e.id for e in results_with}
        self.assertIn(eid, ids_with)

        results_without = self.wm.query(
            MemoryType.USER_COMMAND, include_expired=False,
        )
        ids_without = {e.id for e in results_without}
        self.assertNotIn(eid, ids_without)


# ======================================================================
#  WorkingMemory — Singleton accessors
# ======================================================================

class TestSingletonAccessors(TestCase):
    def setUp(self) -> None:
        self.wm = WorkingMemory()

    def tearDown(self) -> None:
        self.wm.stop()

    def test_get_current_task_none_when_empty(self) -> None:
        self.assertIsNone(self.wm.get_current_task())

    def test_get_current_task(self) -> None:
        self.wm.add(MemoryType.CURRENT_TASK, "implement search")
        self.assertEqual(self.wm.get_current_task(), "implement search")

    def test_get_current_project(self) -> None:
        self.wm.add(MemoryType.CURRENT_PROJECT, "JARVIS")
        self.assertEqual(self.wm.get_current_project(), "JARVIS")

    def test_get_current_application(self) -> None:
        self.wm.add(MemoryType.CURRENT_APPLICATION, "chrome.exe")
        self.assertEqual(self.wm.get_current_application(), "chrome.exe")

    def test_get_current_file(self) -> None:
        self.wm.add(MemoryType.CURRENT_FILE, "main.py")
        self.assertEqual(self.wm.get_current_file(), "main.py")

    def test_get_current_browser_tab(self) -> None:
        self.wm.add(MemoryType.CURRENT_BROWSER_TAB, "GitHub")
        self.assertEqual(self.wm.get_current_browser_tab(), "GitHub")

    def test_get_current_folder(self) -> None:
        self.wm.add(MemoryType.CURRENT_FOLDER, "/home/user/project")
        self.assertEqual(self.wm.get_current_folder(), "/home/user/project")

    def test_get_conversation_context(self) -> None:
        self.wm.add(MemoryType.CONVERSATION_CONTEXT, "user is debugging")
        self.assertEqual(self.wm.get_conversation_context(), "user is debugging")


# ======================================================================
#  WorkingMemory — List accessors
# ======================================================================

class TestListAccessors(TestCase):
    def setUp(self) -> None:
        self.wm = WorkingMemory()

    def tearDown(self) -> None:
        self.wm.stop()

    def test_get_recent_commands_empty(self) -> None:
        self.assertEqual(self.wm.get_recent_commands(), [])

    def test_get_recent_commands(self) -> None:
        self.wm.add_command("cmd1")
        self.wm.add_command("cmd2")
        self.wm.add_command("cmd3")
        results = self.wm.get_recent_commands(2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].content, "cmd3")
        self.assertEqual(results[1].content, "cmd2")

    def test_get_recent_actions(self) -> None:
        self.wm.add_action("act1")
        self.wm.add_action("act2")
        results = self.wm.get_recent_actions()
        self.assertEqual(len(results), 2)

    def test_get_pending_goals_empty(self) -> None:
        self.assertEqual(self.wm.get_pending_goals(), [])

    def test_get_pending_goals(self) -> None:
        self.wm.add_goal("goal1")
        self.wm.add_goal("goal2")
        self.assertEqual(len(self.wm.get_pending_goals()), 2)

    def test_get_pending_confirmations(self) -> None:
        self.wm.add_confirmation("confirm?")
        self.assertEqual(len(self.wm.get_pending_confirmations()), 1)


# ======================================================================
#  WorkingMemory — Eviction
# ======================================================================

class TestEviction(TestCase):
    def setUp(self) -> None:
        self.wm = WorkingMemory()

    def tearDown(self) -> None:
        self.wm.stop()

    def test_evict_expired_removes_ttl_entries(self) -> None:
        eid = self.wm.add(MemoryType.USER_COMMAND, "ephemeral", ttl_seconds=0.001)
        time.sleep(0.01)
        removed = self.wm.evict_expired()
        self.assertGreaterEqual(removed, 1)
        self.assertIsNone(self.wm.get(eid))

    def test_evict_expired_preserves_persistent(self) -> None:
        eid = self.wm.add(MemoryType.CURRENT_TASK, "persistent")
        self.wm.evict_expired()
        self.assertIsNotNone(self.wm.get(eid))

    def test_evict_expired_on_empty(self) -> None:
        self.assertEqual(self.wm.evict_expired(), 0)

    def test_expired_entry_query_excluded(self) -> None:
        self.wm.add(MemoryType.USER_COMMAND, "gone", ttl_seconds=0.001)
        time.sleep(0.01)
        results = self.wm.query(MemoryType.USER_COMMAND)
        self.assertEqual(len(results), 0)

    def test_expired_entry_retrieved_by_id_returns_none(self) -> None:
        eid = self.wm.add(MemoryType.USER_COMMAND, "gone", ttl_seconds=0.001)
        time.sleep(0.01)
        # Without explicit eviction, get() still checks is_expired
        self.assertIsNone(self.wm.get(eid))


# ======================================================================
#  WorkingMemory — Clear
# ======================================================================

class TestClear(TestCase):
    def setUp(self) -> None:
        self.wm = WorkingMemory()

    def tearDown(self) -> None:
        self.wm.stop()

    def test_clear_removes_all(self) -> None:
        self.wm.add_command("cmd")
        self.wm.add_action("act")
        self.wm.add(MemoryType.CURRENT_TASK, "task")
        count = self.wm.clear()
        self.assertEqual(count, 3)
        self.assertEqual(len(self.wm.query()), 0)

    def test_clear_empty(self) -> None:
        self.assertEqual(self.wm.clear(), 0)

    def test_clear_after_eviction(self) -> None:
        self.wm.add_command("cmd")
        self.wm.evict_expired()
        self.assertEqual(self.wm.clear(), 1)


# ======================================================================
#  WorkingMemory — Summarize
# ======================================================================

class TestSummarize(TestCase):
    def setUp(self) -> None:
        self.wm = WorkingMemory()

    def tearDown(self) -> None:
        self.wm.stop()

    def test_summarize_empty(self) -> None:
        self.assertEqual(self.wm.summarize(), "(empty)")

    def test_summarize_with_task(self) -> None:
        self.wm.add(MemoryType.CURRENT_TASK, "fix bug")
        summary = self.wm.summarize()
        self.assertIn("Task: fix bug", summary)

    def test_summarize_project_and_app(self) -> None:
        self.wm.add(MemoryType.CURRENT_PROJECT, "JARVIS")
        self.wm.add(MemoryType.CURRENT_APPLICATION, "vscode")
        summary = self.wm.summarize()
        self.assertIn("Project: JARVIS", summary)
        self.assertIn("Application: vscode", summary)

    def test_summarize_goals(self) -> None:
        self.wm.add_goal("goal1")
        self.wm.add_goal("goal2")
        summary = self.wm.summarize()
        self.assertIn("Pending goals (2)", summary)
        self.assertIn("goal1", summary)
        self.assertIn("goal2", summary)

    def test_summarize_last_command(self) -> None:
        self.wm.add_command("cmd1")
        self.wm.add_command("cmd2")
        summary = self.wm.summarize()
        self.assertIn("Last command: cmd2", summary)


# ======================================================================
#  WorkingMemory — Thread safety
# ======================================================================

class TestThreadSafety(TestCase):
    def setUp(self) -> None:
        self.wm = WorkingMemory()

    def tearDown(self) -> None:
        self.wm.stop()

    def test_concurrent_adds(self) -> None:
        n = 100
        errors: list[Exception] = []

        def add_cmd(i: int) -> None:
            try:
                self.wm.add_command(f"cmd{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_cmd, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        results = self.wm.query(MemoryType.USER_COMMAND)
        # May be less than n due to list trimming
        self.assertLessEqual(len(results), n)
        self.assertGreater(len(results), 0)

    def test_concurrent_read_write(self) -> None:
        n = 50
        errors: list[Exception] = []
        stop_event = threading.Event()

        def writer() -> None:
            i = 0
            while not stop_event.is_set():
                try:
                    self.wm.add_command(f"w{i}")
                    self.wm.add_action(f"a{i}")
                    i += 1
                except Exception as e:
                    errors.append(e)

        def reader() -> None:
            while not stop_event.is_set():
                try:
                    self.wm.query()
                    self.wm.get_recent_commands(5)
                    self.wm.summarize()
                except Exception as e:
                    errors.append(e)

        wt = threading.Thread(target=writer, daemon=True)
        rt = threading.Thread(target=reader, daemon=True)
        wt.start()
        rt.start()
        time.sleep(0.2)
        stop_event.set()
        wt.join(timeout=2)
        rt.join(timeout=2)
        self.assertEqual(len(errors), 0)

    def test_concurrent_update(self) -> None:
        eid = self.wm.add_command("original")
        n = 20
        errors: list[Exception] = []

        def updater(i: int) -> None:
            try:
                self.wm.update(eid, content=f"update{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=updater, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        entry = self.wm.get(eid)
        assert entry is not None
        self.assertIn(entry.content, {f"update{i}" for i in range(n)})


# ======================================================================
#  WorkingMemory — Edge cases
# ======================================================================

class TestEdgeCases(TestCase):
    def setUp(self) -> None:
        self.wm = WorkingMemory()

    def tearDown(self) -> None:
        self.wm.stop()

    def test_get_nonexistent_id(self) -> None:
        self.assertIsNone(self.wm.get("nope"))

    def test_query_with_type_with_no_entries(self) -> None:
        results = self.wm.query(MemoryType.PENDING_GOAL)
        self.assertEqual(results, [])

    def test_add_empty_content(self) -> None:
        eid = self.wm.add_command("")
        entry = self.wm.get(eid)
        assert entry is not None
        self.assertEqual(entry.content, "")

    def test_add_then_update_then_query(self) -> None:
        eid = self.wm.add_command("original")
        self.wm.update(eid, content="revised")
        results = self.wm.query(MemoryType.USER_COMMAND)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "revised")

    def test_multiple_singletons_of_different_types(self) -> None:
        self.wm.add(MemoryType.CURRENT_TASK, "task")
        self.wm.add(MemoryType.CURRENT_PROJECT, "project")
        self.wm.add(MemoryType.CURRENT_FILE, "file")
        self.assertEqual(self.wm.get_current_task(), "task")
        self.assertEqual(self.wm.get_current_project(), "project")
        self.assertEqual(self.wm.get_current_file(), "file")

    def test_goal_list_respects_max(self) -> None:
        max_goals = LIST_TYPE_MAX[MemoryType.PENDING_GOAL]
        for i in range(max_goals + 10):
            self.wm.add_goal(f"goal{i}")
        self.assertEqual(len(self.wm.get_pending_goals()), max_goals)
