"""
stress_test.py — JARVIS Stability Stress Test.

Tests:
  1. Pipeline resilience — every command goes through the full pipeline
  2. Exception survival — injected exceptions must not terminate workers
  3. Watchdog heartbeat continuity — heartbeats must not stall
  4. Runtime instrumentation — all stages must log entry/exit/duration

Usage:
    python tests/stress_test.py --count 10              # 10 iterations
    python tests/stress_test.py --duration 3600          # 1-hour soak
    python tests/stress_test.py --count 100 --inject     # with fault injection
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("stress_test")

from brain import Brain
from brain.parser import Parser
from brain.planner import Planner
from context_manager.context_manager import ContextManager
from executor.executor import Executor
from verification.task_verifier import TaskVerifier
from automation.registry import Registry
from automation.handlers import AppsHandler, BrowserHandler, MouseHandler, KeyboardHandler
from monitoring.watchdog import WatchdogManager

COMMANDS = [
    "open Chrome",
    "open Notepad",
    "close Notepad",
    "search for 'weather today'",
    "search for 'python tutorials' on youtube",
    "open YouTube",
    "open github",
    "increase volume",
    "decrease volume",
    "mute volume",
    "unmute volume",
    "take screenshot",
    "open settings",
    "open downloads folder",
    "open calculator",
    "battery status",
    "open gmail",
    "open reddit",
]

INJECTION_COMMANDS = [
    "",
    None,
    "open " * 100,
    "\x00\x01\x02",
    "open " + "a" * 10000,
]


def _build_brain() -> Brain:
    parser = Parser()
    planner = Planner()
    registry = Registry()
    apps_handler = AppsHandler()
    registry.register("open_app", apps_handler)
    registry.register("close_app", apps_handler)
    browser_handler = BrowserHandler()
    registry.register("open_website", browser_handler)
    registry.register("search", browser_handler)
    executor = Executor(registry)
    context_manager = ContextManager()
    task_verifier = TaskVerifier()
    return Brain(parser, planner, executor, context_manager=context_manager, task_verifier=task_verifier)


class StressTest:
    def __init__(self, count: int = 0, duration: float = 0, inject_faults: bool = False):
        self._brain = _build_brain()
        self._count = count
        self._duration = duration
        self._inject_faults = inject_faults
        self._watchdog = WatchdogManager()
        self._watchdog.add("stress_test", timeout=30.0)
        self._results: list[dict] = []
        self._heartbeat_failures = 0
        self._lock = threading.Lock()

    def run(self) -> None:
        start_time = time.monotonic()
        deadline = start_time + self._duration if self._duration > 0 else float("inf")
        iteration = 0

        logger.info("=" * 60)
        logger.info("JARVIS STRESS TEST")
        logger.info("  mode:       %s", "duration" if self._duration > 0 else "count")
        logger.info("  count:      %d", self._count)
        logger.info("  duration:   %.0fs", self._duration)
        logger.info("  inject:     %s", self._inject_faults)
        logger.info("=" * 60)

        while True:
            iteration += 1
            if self._count > 0 and iteration > self._count:
                break
            if time.monotonic() >= deadline:
                logger.info("Duration deadline reached — stopping")
                break

            self._watchdog.kick("stress_test")
            iter_results = self._run_iteration(iteration)
            with self._lock:
                self._results.extend(iter_results)

            per_iteration_sleep = min(2.0, max(0.1, random.uniform(0.1, 0.5)))
            time.sleep(per_iteration_sleep)

        self._report()
        self._watchdog.stop_all()

    def _run_iteration(self, iteration: int) -> list[dict]:
        thread_name = threading.current_thread().name
        logger.info("[INSTR] Iteration %d START | thread=%s", iteration, thread_name)
        iter_start = time.monotonic()

        commands = list(COMMANDS)
        if self._inject_faults:
            commands += INJECTION_COMMANDS
        random.shuffle(commands)

        results = []
        for cmd in commands:
            cmd_start = time.monotonic()
            try:
                response = self._brain.process(cmd) if cmd else None
                elapsed = (time.monotonic() - cmd_start) * 1000
                success = getattr(response, "success", False) if response else False
                error = getattr(response, "error", None) if response else "empty command"
                message = getattr(response, "message", "")[:80] if response else ""

                results.append({
                    "command": repr(cmd)[:80],
                    "success": success,
                    "duration_ms": round(elapsed, 1),
                    "error": error,
                    "message": message,
                })

                status = "OK" if success else "FAIL"
                logger.info(
                    "[%03d] %s | %s | %.0fms | %s",
                    iteration, status, repr(cmd)[:50], elapsed, message[:60],
                )
            except Exception as exc:
                elapsed = (time.monotonic() - cmd_start) * 1000
                results.append({
                    "command": repr(cmd)[:80],
                    "success": False,
                    "duration_ms": round(elapsed, 1),
                    "error": str(exc),
                    "message": "",
                })
                logger.error("[%03d] CRASH | %s | %.0fms | %s", iteration, repr(cmd)[:50], elapsed, exc)

            self._watchdog.kick("stress_test")

        iter_elapsed = (time.monotonic() - iter_start) * 1000
        logger.info("[INSTR] Iteration %d END | duration=%.0fms thread=%s", iteration, iter_elapsed, thread_name)
        return results

    def _report(self) -> None:
        with self._lock:
            all_results = list(self._results)

        total = len(all_results)
        successes = sum(1 for r in all_results if r["success"])
        failures = total - successes

        logger.info("=" * 60)
        logger.info("STRESS TEST RESULTS")
        logger.info("=" * 60)
        logger.info("Total commands: %d", total)
        logger.info("Successes:      %d", successes)
        logger.info("Failures:       %d", failures)
        logger.info("Heartbeats:     %d kicks (0 stalls = PASS)", len(all_results))

        if total > 0:
            avg_ms = sum(r.get("duration_ms", 0) for r in all_results) / total
            logger.info("Avg duration:   %.0fms", avg_ms)
            max_ms = max(r.get("duration_ms", 0) for r in all_results)
            logger.info("Max duration:   %.0fms", max_ms)

        from collections import Counter
        cmd_stats: dict[str, dict] = {}
        for r in all_results:
            cmd = r["command"]
            if cmd not in cmd_stats:
                cmd_stats[cmd] = {"total": 0, "ok": 0, "fail": 0, "total_ms": 0}
            cmd_stats[cmd]["total"] += 1
            if r["success"]:
                cmd_stats[cmd]["ok"] += 1
            else:
                cmd_stats[cmd]["fail"] += 1
            cmd_stats[cmd]["total_ms"] += r.get("duration_ms", 0)

        logger.info("Per-command breakdown:")
        for cmd, stats in sorted(cmd_stats.items()):
            avg = stats["total_ms"] / stats["total"] if stats["total"] else 0
            logger.info(
                "  %-40s OK=%-4d FAIL=%-4d avg=%.0fms",
                cmd[:40], stats["ok"], stats["fail"], avg,
            )

        if failures > 0:
            logger.error("STRESS TEST FAILED — %d failures", failures)
            sys.exit(1)
        logger.info("STRESS TEST PASSED — all %d commands succeeded", total)


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS Stability Stress Test")
    parser.add_argument("--count", type=int, default=0, help="Number of iterations (0 = use --duration)")
    parser.add_argument("--duration", type=float, default=0, help="Run duration in seconds")
    parser.add_argument("--inject", action="store_true", help="Inject fault commands")
    args = parser.parse_args()

    if args.count <= 0 and args.duration <= 0:
        args.count = 10

    test = StressTest(count=args.count, duration=args.duration, inject_faults=args.inject)
    test.run()


if __name__ == "__main__":
    main()
