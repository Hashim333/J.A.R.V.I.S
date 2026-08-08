"""
tests/test_task_manager.py

Unit tests for the single-active-task execution manager
(tasks/task_manager.py).

Verifies:
  - Only ONE task is ever active (a new command cancels the previous one).
  - Lifecycle CREATED -> RUNNING -> SUCCESS / FAILED / CANCELLED.
  - Cancelling/failing a task runs its cleanup callbacks exactly once and
    sets its cancel_event (so detached workers abort at the next step).
  - A successful task does NOT set its cancel_event.
  - Expired RUNNING tasks are marked FAILED(timeout) by check_timeouts().
  - Every lifecycle transition is logged for diagnosis.
"""

from __future__ import annotations

import time
import unittest

from tasks.task_manager import Task, TaskManager, TaskStatus


class _CleanupProbe:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


class TestSingleActiveTask(unittest.TestCase):
    def test_second_command_cancels_first(self) -> None:
        tm = TaskManager()
        first = tm.create_task("open chrome")
        second = tm.create_task("search cats on youtube")

        self.assertEqual(first.status, TaskStatus.CANCELLED)
        self.assertEqual(second.status, TaskStatus.CREATED)
        self.assertIs(tm.current_task, second)
        self.assertFalse(first.is_active)
        self.assertIs(tm.active_task, second)
        self.assertEqual(len([t for t in (first, second) if t.is_active]), 1)

    def test_only_one_task_active_at_a_time(self) -> None:
        tm = TaskManager()
        tasks = [tm.create_task(f"cmd {i}") for i in range(5)]
        active = [t for t in tasks if t.is_active]
        self.assertEqual(len(active), 1)
        self.assertIs(active[0], tasks[-1])
        self.assertEqual([t.status for t in tasks[:-1]],
                         [TaskStatus.CANCELLED] * 4)


class TestLifecycle(unittest.TestCase):
    def test_created_to_running_to_success(self) -> None:
        tm = TaskManager()
        task = tm.create_task("open notepad")
        self.assertEqual(task.status, TaskStatus.CREATED)

        self.assertTrue(tm.start_task(task))
        self.assertEqual(task.status, TaskStatus.RUNNING)

        self.assertTrue(tm.mark_success(task))
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertIsNone(tm.current_task)
        self.assertFalse(tm.is_active())

    def test_start_task_twice_is_noop(self) -> None:
        tm = TaskManager()
        task = tm.create_task("x")
        self.assertTrue(tm.start_task(task))
        self.assertFalse(tm.start_task(task))

    def test_terminal_transition_is_idempotent(self) -> None:
        tm = TaskManager()
        task = tm.create_task("x")
        self.assertTrue(tm.mark_success(task))
        self.assertFalse(tm.mark_success(task))
        self.assertFalse(tm.mark_failed(task, reason="again"))
        self.assertFalse(tm.cancel(task, reason="again"))
        self.assertEqual(task.status, TaskStatus.SUCCESS)

    def test_cancel_sets_status_and_event(self) -> None:
        tm = TaskManager()
        task = tm.create_task("open chrome")
        self.assertTrue(tm.cancel(task, reason="superseded"))
        self.assertEqual(task.status, TaskStatus.CANCELLED)
        self.assertTrue(task.cancel_event.is_set())
        self.assertEqual(task.reason, "superseded")


class TestCleanup(unittest.TestCase):
    def test_cancel_runs_cleanup_callbacks(self) -> None:
        tm = TaskManager()
        task = tm.create_task("open chrome")
        probe = _CleanupProbe()
        tm.register_cleanup(task, probe)
        tm.cancel(task, reason="new command")

        self.assertEqual(probe.calls, 1)

    def test_failed_runs_cleanup_callbacks(self) -> None:
        tm = TaskManager()
        task = tm.create_task("open chrome")
        probe = _CleanupProbe()
        tm.register_cleanup(task, probe)
        tm.mark_failed(task, reason="timeout")

        self.assertEqual(probe.calls, 1)
        self.assertTrue(task.cancel_event.is_set())

    def test_success_does_not_set_cancel_event(self) -> None:
        tm = TaskManager()
        task = tm.create_task("open chrome")
        probe = _CleanupProbe()
        tm.register_cleanup(task, probe)
        tm.mark_success(task)

        self.assertFalse(task.cancel_event.is_set())
        self.assertEqual(probe.calls, 1)

    def test_cleanup_runs_exactly_once(self) -> None:
        tm = TaskManager()
        task = tm.create_task("x")
        probe = _CleanupProbe()
        tm.register_cleanup(task, probe)
        tm.cancel(task)
        tm.cancel(task)
        tm.mark_failed(task)

        self.assertEqual(probe.calls, 1)

    def test_cleanup_registered_after_terminal_runs_immediately(self) -> None:
        tm = TaskManager()
        task = tm.create_task("x")
        tm.mark_failed(task, reason="boom")
        probe = _CleanupProbe()
        tm.register_cleanup(task, probe)
        self.assertEqual(probe.calls, 1)

    def test_cleanup_exception_is_contained(self) -> None:
        tm = TaskManager()

        def boom() -> None:
            raise RuntimeError("cleanup failed")

        task = tm.create_task("x")
        probe = _CleanupProbe()
        tm.register_cleanup(task, boom)
        tm.register_cleanup(task, probe)
        tm.cancel(task)  # must not raise
        self.assertEqual(probe.calls, 1)


class TestDeadlines(unittest.TestCase):
    def test_check_timeouts_marks_expired_task_failed(self) -> None:
        tm = TaskManager(default_deadline=0.05)
        task = tm.create_task("open chrome")
        tm.start_task(task)
        time.sleep(0.2)
        expired = tm.check_timeouts()

        self.assertEqual(expired, [task])
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.reason, "timeout")
        self.assertTrue(task.cancel_event.is_set())

    def test_unexpired_task_not_touched(self) -> None:
        tm = TaskManager(default_deadline=30.0)
        task = tm.create_task("open chrome")
        tm.start_task(task)
        self.assertEqual(tm.check_timeouts(), [])
        self.assertEqual(task.status, TaskStatus.RUNNING)


class TestLifecycleLogging(unittest.TestCase):
    def test_events_recorded(self) -> None:
        tm = TaskManager()
        task = tm.create_task("open chrome")
        tm.start_task(task)
        tm.mark_success(task)

        events = tm.events
        self.assertEqual([e["event"] for e in events],
                         ["created", "started", "completed"])
        self.assertEqual(events[0]["status"], "CREATED")
        self.assertEqual(events[-1]["status"], "SUCCESS")
        self.assertEqual(events[0]["raw_text"], "open chrome")

    def test_cancel_event_recorded(self) -> None:
        tm = TaskManager()
        first = tm.create_task("a")
        tm.create_task("b")
        events = tm.events
        cancelled = [e for e in events if e["event"] == "cancelled"]
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(cancelled[0]["task_id"], first.task_id)
        self.assertEqual(cancelled[0]["reason"], "superseded by new command")


if __name__ == "__main__":
    unittest.main()
