#!/usr/bin/env python3
"""Multi-attempt session orchestrator. Runs autoplay over and over, with
configurable retry policy.

Usage:
    # Try level 8 up to 5 times until won
    python scripts/session.py --level 8 --max-attempts 5

    # Each level in a list, up to 3 attempts each
    python scripts/session.py --level 8 --level 9 --level 10 --max-attempts 3

The session expects you (or the LLM agent) to navigate to the gameplay
screen of the FIRST level before launching. Between attempts of the same
level (e.g. after a loss), the session pauses and asks the user/agent to
re-navigate (we can't automate "tap Restart" reliably yet — that's the
LLM's responsibility).

Output:
    JSON line per session event (start, attempt, attempt_end, session_end)
    Exit code: 0 if all levels won at least once, 1 otherwise

Exit on:
    - Configured max-attempts hit on a level (give up, move to next)
    - All levels processed
    - User Ctrl+C
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_autoplay(level: int, args, *, attempt: int) -> dict:
    """Invoke autoplay.py for one attempt at one level. Returns summary dict."""
    cmd = [sys.executable, str(ROOT / "scripts" / "autoplay.py"), "--level", str(level)]
    for opt in ("--device", "--max-steps", "--min-wait", "--max-wait",
                "--triplet-extra-wait", "--max-tap-retries"):
        val = getattr(args, opt[2:].replace("-", "_"), None)
        if val is not None:
            cmd.extend([opt, str(val)])
    if args.keep_screenshots:
        cmd.append("--keep-screenshots")
    if args.verbose:
        cmd.append("--verbose")

    start_ts = time.time()
    print(json.dumps({"event": "attempt_start", "level": level,
                      "attempt": attempt, "cmd": " ".join(cmd),
                      "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z"}))
    proc = subprocess.run(cmd)
    duration = round(time.time() - start_ts, 1)
    rc = proc.returncode
    status = {0: "won", 1: "lost", 2: "abandoned", 3: "setup_error"}.get(rc, "unknown")
    return {"level": level, "attempt": attempt, "status": status,
            "rc": rc, "duration_sec": duration}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--level", type=int, action="append", required=True,
                   help="Level to attempt. Repeat for multiple levels in order.")
    p.add_argument("--max-attempts", type=int, default=3,
                   help="Per-level retries before giving up (default 3)")
    p.add_argument("--device", default=None)
    p.add_argument("--max-steps", type=int, default=200)
    p.add_argument("--min-wait", type=float, default=0.3)
    p.add_argument("--max-wait", type=float, default=3.0)
    p.add_argument("--triplet-extra-wait", type=float, default=1.0)
    p.add_argument("--max-tap-retries", type=int, default=2)
    p.add_argument("--keep-screenshots", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--inter-attempt-pause", type=float, default=8.0,
                   help="Seconds to wait between attempts (for navigation back)")
    args = p.parse_args()

    session_started = time.time()
    summary = []
    levels_won = 0

    print(json.dumps({"event": "session_start", "levels": args.level,
                      "max_attempts": args.max_attempts,
                      "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z"}))

    for level in args.level:
        won_this_level = False
        for attempt in range(1, args.max_attempts + 1):
            result = run_autoplay(level, args, attempt=attempt)
            print(json.dumps({"event": "attempt_end", **result,
                              "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z"}))
            summary.append(result)
            if result["status"] == "won":
                won_this_level = True
                break
            if result["status"] == "setup_error":
                # adb dropped or environment broken — not transient, bail
                print(json.dumps({"event": "session_abort", "reason": "setup_error",
                                  "level": level, "attempt": attempt}))
                return 1
            # lost / abandoned — pause and retry
            if attempt < args.max_attempts:
                print(json.dumps({"event": "pause_between_attempts",
                                  "seconds": args.inter_attempt_pause,
                                  "msg": "navigate back to gameplay screen now"}))
                time.sleep(args.inter_attempt_pause)
        if won_this_level:
            levels_won += 1
        # Pause between levels too — for navigating to the next one
        print(json.dumps({"event": "pause_between_levels",
                          "seconds": args.inter_attempt_pause}))
        time.sleep(args.inter_attempt_pause)

    duration = round(time.time() - session_started, 1)
    print(json.dumps({
        "event": "session_end",
        "levels_attempted": len(args.level),
        "levels_won": levels_won,
        "total_attempts": len(summary),
        "duration_sec": duration,
        "summary": summary,
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }))
    return 0 if levels_won == len(args.level) else 1


if __name__ == "__main__":
    sys.exit(main())
