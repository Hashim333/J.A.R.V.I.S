"""
diag_harness.py — JARVIS runtime diagnostic harness.

Launches the real desktop app (run.py) with JARVIS_DIAG=1, feeds a
scripted workload through stdin (the same channel the text-input thread
consumes), and captures a complete diagnostic log.  The user must
interact with the UI as instructed by the printed schedule.

Modes:
  --steady N      run N seconds idle (default 120), issuing one command/min
  --stress N      issue a rapid burst of N commands after the steady phase
  --soak N        keep app alive N more seconds after stress (default 60)
  --shutdown      send "exit" and measure shutdown duration from logs
  --out FILE      log file path (default diagnostics/run_log.txt)

Usage:
    python tests/diag_harness.py --steady 180 --stress 20 --soak 60 --shutdown
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

STEADY_COMMANDS = [
    "open notepad",
    "open calculator",
    "what time is it",
    "battery status",
    "open downloads folder",
]

STRESS_COMMANDS = [
    "open notepad",
    "open calculator",
    "close notepad",
    "search for weather",
    "open youtube",
    "increase volume",
    "take screenshot",
    "open settings",
    "open gmail",
    "open reddit",
    "battery status",
    "open github",
]


def _run(
    steady: int,
    stress: int,
    soak: int,
    shutdown: bool,
    out: str,
) -> int:
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["JARVIS_DIAG"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [PY, "run.py"],
        cwd=str(ROOT),
        env=env,
        stdin=subprocess.PIPE,
        stdout=open(out_path, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        text=True,
    )

    print(f"[HARNESS] PID={proc.pid} log={out_path}")
    print("[HARNESS] The JARVIS UI window will open. Leave it alone.")
    print("[HARNESS] Phase 1: STEADY-STATE idle soak for %ds" % steady)
    print("[HARNESS]   Type commands below as prompted (or press Enter).")

    def send(cmd: str) -> None:
        proc.stdin.write(cmd + "\n")
        proc.stdin.flush()
        print(f"[HARNESS] >> sent: {cmd!r}")

    t0 = time.monotonic()
    deadline = t0 + steady
    cmd_idx = 0
    while time.monotonic() < deadline:
        if cmd_idx < len(STEADY_COMMANDS) and (time.monotonic() - t0) >= cmd_idx * (steady / len(STEADY_COMMANDS)):
            send(STEADY_COMMANDS[cmd_idx])
            cmd_idx += 1
        try:
            line = sys.stdin.readline()
        except (KeyboardInterrupt, EOFError):
            line = ""
        if line:
            line = line.strip()
            if line:
                send(line)
        time.sleep(0.1)

    if stress > 0:
        print(f"[HARNESS] Phase 2: STRESS burst of {stress} commands")
        for i in range(stress):
            send(STRESS_COMMANDS[i % len(STRESS_COMMANDS)])
            time.sleep(0.35)

    if soak > 0:
        print(f"[HARNESS] Phase 3: SOAK for {soak}s (UI freeze window)")
        end = time.monotonic() + soak
        while time.monotonic() < end:
            try:
                line = sys.stdin.readline()
            except (KeyboardInterrupt, EOFError):
                line = ""
            if line and line.strip():
                send(line.strip())
            time.sleep(0.1)

    if shutdown:
        print("[HARNESS] Phase 4: SHUTDOWN — sending 'exit'")
        send("exit")
        t_shutdown = time.monotonic()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            print("[HARNESS] ERROR: process did not exit within 60s — killing")
            proc.kill()
            proc.wait()
            return 2
        elapsed = time.monotonic() - t_shutdown
        print(f"[HARNESS] Process exited {elapsed:.1f}s after 'exit' sent")
    else:
        print("[HARNESS] Keeping app alive. Press Ctrl+C in the app to quit.")
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.kill()
            proc.wait()

    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="JARVIS diagnostic harness")
    ap.add_argument("--steady", type=int, default=120)
    ap.add_argument("--stress", type=int, default=0)
    ap.add_argument("--soak", type=int, default=60)
    ap.add_argument("--shutdown", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "diagnostics" / "run_log.txt"))
    args = ap.parse_args()

    code = _run(args.steady, args.stress, args.soak, args.shutdown, args.out)
    sys.exit(code)


if __name__ == "__main__":
    main()
