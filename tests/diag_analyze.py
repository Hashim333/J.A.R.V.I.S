"""
diag_analyze.py — parse a JARVIS diagnostic log into structured evidence.

Reads a log produced by diag_harness.py (run.py with JARVIS_DIAG=1) and
emits a per-symptom evidence summary so the stabilization report can be
written from facts.

Usage:
    python tests/diag_analyze.py diagnostics/run_log.txt

Output sections:
  - Runtime summary (startup, shutdown durations, thread inventory)
  - Task timing outliers (>3s)
  - UI heartbeat gaps / stalls
  - Watchdog STALL events
  - Unhandled exceptions / CRASH lines
  - Thread list growth over time (leak detection)
  - Queue depth peaks
  - Shutdown phase timings
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

_TASK_START = re.compile(
    r"\[DIAG\] TASK START \| task=(?P<task>.+?) thread=(?P<thread>.+?) tid=(?P<tid>\d+)"
)
_TASK_END = re.compile(
    r"\[DIAG\] TASK END   \| task=(?P<task>.+?) thread=(?P<thread>.+?) tid=(?P<tid>\d+) "
    r"status=(?P<status>\w+) duration=(?P<dur>\d+)ms"
)
_SNAP = re.compile(
    r"\[DIAG\] SNAPSHOT \| cpu=(?P<cpu>[-\d.]+)% rss=(?P<rss>[-\d.]+)MB "
    r"ui_tick=(?P<tick>[-\d.]+)/s threads=(?P<n>\d+) queues=(?P<qs>.*?) threadlist=(?P<tl>.*)"
)
_STALL = re.compile(r"Watchdog\[(?P<name>.+?)\] STALL detected")
_FREEZE = re.compile(r"\[UI FREEZE\]|\[UI BLOCKED\]|\[UI CRASH\]|\[UI MONITOR\]")
_CRASH = re.compile(r"Traceback|Unhandled|CRITICAL|Error:|Exception")
_SHUTDOWN_PHASE = re.compile(
    r"Shutdown phase (?P<name>\w+) completed in (?P<ms>\d+)ms"
)
_SHUTDOWN_TOTAL = re.compile(r"Shutdown completed in (?P<sec>[-\d.]+)s")
_JOIN_WARN = re.compile(r"did not (?:join|stop) within|not join within")


def _parse(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    tasks: list[dict] = []
    starts: dict[tuple[str, int], dict] = {}
    snaps: list[dict] = []
    stalls: list[str] = []
    ui_events: list[str] = []
    crashes: list[str] = []
    shutdown_phases: list[tuple[str, int]] = []
    shutdown_total: float | None = None
    join_warns: list[str] = []

    for line in lines:
        if m := _TASK_END.search(line):
            key = (m.group("task"), int(m.group("tid")))
            tasks.append({
                "task": m.group("task"),
                "thread": m.group("thread"),
                "status": m.group("status"),
                "dur_ms": int(m.group("dur")),
            })
        elif m := _SNAP.search(line):
            snaps.append({
                "cpu": float(m.group("cpu")),
                "rss": float(m.group("rss")),
                "tick": float(m.group("tick")),
                "n": int(m.group("n")),
                "tl": m.group("tl"),
            })
        elif m := _STALL.search(line):
            stalls.append(line)
        elif _FREEZE.search(line):
            ui_events.append(line)
        elif m := _SHUTDOWN_PHASE.search(line):
            shutdown_phases.append((m.group("name"), int(m.group("ms"))))
        elif m := _SHUTDOWN_TOTAL.search(line):
            shutdown_total = float(m.group("sec"))
        elif _JOIN_WARN.search(line):
            join_warns.append(line)
        elif _CRASH.search(line) and "TASK START" not in line and "TASK END" not in line:
            crashes.append(line)

    return {
        "lines": lines,
        "tasks": tasks,
        "snaps": snaps,
        "stalls": stalls,
        "ui_events": ui_events,
        "crashes": crashes,
        "shutdown_phases": shutdown_phases,
        "shutdown_total": shutdown_total,
        "join_warns": join_warns,
    }


def _report(data: dict) -> None:
    print("=" * 72)
    print("JARVIS DIAGNOSTIC ANALYSIS")
    print("=" * 72)

    tasks = data["tasks"]
    print(f"\n[TASKS] {len(tasks)} start/end records")
    if tasks:
        by_task: dict[str, list[int]] = defaultdict(list)
        for t in tasks:
            by_task[t["task"]].append(t["dur_ms"])
        print(f"  {'task':<28} {'count':>6} {'max(ms)':>9} {'avg(ms)':>9} {'p95(ms)':>9}")
        for name, durs in sorted(by_task.items(), key=lambda kv: -max(kv[1])):
            durs.sort()
            p95 = durs[int(len(durs) * 0.95) - 1] if durs else 0
            print(f"  {name:<28} {len(durs):>6} {max(durs):>9} {sum(durs)//len(durs):>9} {p95:>9}")

    outliers = [t for t in tasks if t["dur_ms"] > 3000]
    if outliers:
        print(f"\n[TASK OUTLIERS >3s] {len(outliers)}")
        for t in sorted(outliers, key=lambda x: -x["dur_ms"])[:15]:
            print(f"  {t['task']:<28} {t['dur_ms']:>8}ms  {t['thread']:<20} {t['status']}")

    snaps = data["snaps"]
    if snaps:
        rss = [s["rss"] for s in snaps]
        print(f"\n[SNAPSHOTS] {len(snaps)}")
        print(f"  RSS min/max/first/last: "
              f"{min(rss):.0f}/{max(rss):.0f}/{rss[0]:.0f}/{rss[-1]:.0f} MB")
        print(f"  RSS delta first->last: {rss[-1] - rss[0]:+.0f} MB")
        n_threads = [s["n"] for s in snaps]
        print(f"  Thread count min/max/first/last: "
              f"{min(n_threads)}/{max(n_threads)}/{n_threads[0]}/{n_threads[-1]}")
        print(f"  UI tick min/max/avg: "
              f"{min(s['tick'] for s in snaps):.1f}/{max(s['tick'] for s in snaps):.1f}/"
              f"{sum(s['tick'] for s in snaps)/len(snaps):.1f} /s")
        print("  First 3 thread lists:")
        for s in snaps[:3]:
            print(f"    [{s['n']} threads] {s['tl'][:180]}")

    if data["stalls"]:
        print(f"\n[WATCHDOG STALLS] {len(data['stalls'])}")
        for s in data["stalls"][:10]:
            print(f"  {s[:160]}")
    else:
        print("\n[WATCHDOG STALLS] none")

    if data["ui_events"]:
        print(f"\n[UI EVENTS] {len(data['ui_events'])}")
        for e in data["ui_events"][:15]:
            print(f"  {e[:160]}")
    else:
        print("\n[UI EVENTS] none (no stalls/freezes detected)")

    if data["crashes"]:
        print(f"\n[CRASHES / EXCEPTIONS] {len(data['crashes'])}")
        for c in data["crashes"][:15]:
            print(f"  {c[:160]}")
    else:
        print("\n[CRASHES / EXCEPTIONS] none")

    if data["join_warns"]:
        print(f"\n[SHUTDOWN JOIN WARNINGS] {len(data['join_warns'])}")
        for j in data["join_warns"][:10]:
            print(f"  {j[:160]}")

    if data["shutdown_phases"]:
        print("\n[SHUTDOWN PHASES]")
        total = sum(ms for _, ms in data["shutdown_phases"])
        for name, ms in data["shutdown_phases"]:
            print(f"  {name:<24} {ms:>7}ms")
        print(f"  {'TOTAL (phases)':<24} {total:>7}ms")
    if data["shutdown_total"] is not None:
        print(f"  ShutdownManager total: {data['shutdown_total']:.1f}s")

    print("\n" + "=" * 72)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", help="path to diagnostic log file")
    args = ap.parse_args()
    path = Path(args.log)
    if not path.exists():
        print(f"ERROR: {path} not found")
        sys.exit(1)
    _report(_parse(path))


if __name__ == "__main__":
    main()
