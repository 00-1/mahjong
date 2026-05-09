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
                "--triplet-extra-wait", "--max-tap-retries",
                "--lookahead-depth", "--shot-dir",
                "--surrender-threshold", "--surrender-step-floor",
                "--surrender-min-main-board", "--surrender-sparse-grace",
                "--burst-stability-window",
                "--occult-confidence-threshold", "--posterior-min-confidence",
                "--uct-iterations", "--uct-rollout-depth"):
        val = getattr(args, opt[2:].replace("-", "_"), None)
        if val is not None:
            cmd.extend([opt, str(val)])
    if args.keep_screenshots:
        cmd.append("--keep-screenshots")
    if args.verbose:
        cmd.append("--verbose")
    if args.use_lookahead:
        cmd.append("--use-lookahead")
    if args.use_uct:
        cmd.append("--use-uct")
    if args.learn_occult:
        cmd.append("--learn-occult")
    if args.learn_dim:
        cmd.append("--learn-dim")

    start_ts = time.time()
    print(json.dumps({"event": "attempt_start", "level": level,
                      "attempt": attempt, "cmd": " ".join(cmd),
                      "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z"}))
    proc = subprocess.run(cmd)
    duration = round(time.time() - start_ts, 1)
    rc = proc.returncode
    status = {0: "won", 1: "lost", 2: "abandoned", 3: "setup_error"}.get(rc, "unknown")
    # Find the most recent run dir for this level to read its outcome.json
    # — gives us the autoplay's `reason` (e.g. "game_over_at_start_modal_triggered")
    # which informs the post-attempt recovery decision.
    reason = None
    runs_dir = ROOT / "data" / "runs"
    if runs_dir.exists():
        candidates = sorted(
            (d for d in runs_dir.iterdir()
             if d.is_dir() and d.name.endswith(f"_l{level:02d}")),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            outcome_path = candidates[0] / "outcome.json"
            if outcome_path.exists():
                try:
                    reason = json.loads(outcome_path.read_text()).get("notes")
                except Exception:
                    pass
    return {"level": level, "attempt": attempt, "status": status, "reason": reason,
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
    p.add_argument("--max-consecutive-losses", type=int, default=4,
                   help="Halt after N consecutive *played* losses on the SAME level. "
                        "Strategy probably broken; don't burn all 10 challenge "
                        "tickets. Default 4.")
    p.add_argument("--max-consecutive-abandoned", type=int, default=3,
                   help="Halt after N consecutive abandoned attempts (setup issues, "
                        "snap failures, stale screens — NOT played losses). Default 3.")
    p.add_argument("--use-uct", action="store_true",
                   help="Use single-determinization UCT for EXPLORE decisions. "
                        "Slower but stretches effective horizon via rollouts. "
                        "Forwarded to autoplay.")
    p.add_argument("--uct-iterations", type=int, default=None,
                   help="Forwarded to autoplay.")
    p.add_argument("--uct-rollout-depth", type=int, default=None,
                   help="Forwarded to autoplay.")
    p.add_argument("--use-lookahead", action="store_true",
                   help="Forwarded to autoplay.")
    p.add_argument("--lookahead-depth", type=int, default=None,
                   help="Forwarded to autoplay.")
    p.add_argument("--learn-occult", action="store_true",
                   help="Forwarded to autoplay.")
    p.add_argument("--learn-dim", action="store_true",
                   help="Forwarded to autoplay.")
    p.add_argument("--shot-dir", type=str, default=None,
                   help="Forwarded to autoplay (use writable dir on Termux).")
    # Forwarded autoplay-only flags. Default None means "let autoplay's
    # default apply"; caller can override at the session level if needed.
    p.add_argument("--surrender-threshold", type=float, default=None,
                   help="Forwarded to autoplay.")
    p.add_argument("--surrender-step-floor", type=int, default=None,
                   help="Forwarded to autoplay.")
    p.add_argument("--surrender-min-main-board", type=int, default=None,
                   help="Forwarded to autoplay.")
    p.add_argument("--surrender-sparse-grace", type=int, default=None,
                   help="Forwarded to autoplay.")
    p.add_argument("--burst-stability-window", type=float, default=None,
                   help="Forwarded to autoplay.")
    p.add_argument("--occult-confidence-threshold", type=float, default=None,
                   help="Forwarded to autoplay.")
    p.add_argument("--posterior-min-confidence", type=float, default=None,
                   help="Forwarded to autoplay.")
    args = p.parse_args()

    session_started = time.time()
    summary = []
    levels_won = 0

    print(json.dumps({"event": "session_start", "levels": args.level,
                      "max_attempts": args.max_attempts,
                      "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z"}))

    for level in args.level:
        won_this_level = False
        consecutive_losses = 0
        consecutive_abandoned = 0
        for attempt in range(1, args.max_attempts + 1):
            result = run_autoplay(level, args, attempt=attempt)
            print(json.dumps({"event": "attempt_end", **result,
                              "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z"}))
            summary.append(result)
            if result["status"] == "won":
                won_this_level = True
                break
            if result["status"] == "setup_error":
                print(json.dumps({"event": "session_abort", "reason": "setup_error",
                                  "level": level, "attempt": attempt}))
                return 1
            if result["status"] == "lost":
                consecutive_losses += 1
                consecutive_abandoned = 0
                if consecutive_losses >= args.max_consecutive_losses:
                    print(json.dumps({"event": "halt_on_consecutive_losses",
                                      "level": level, "consecutive_losses": consecutive_losses,
                                      "msg": "strategy probably broken; halting before burning more tickets"}))
                    return 1
            elif result["status"] == "abandoned":
                consecutive_abandoned += 1
                if consecutive_abandoned >= args.max_consecutive_abandoned:
                    print(json.dumps({"event": "halt_on_consecutive_abandoned",
                                      "level": level, "consecutive_abandoned": consecutive_abandoned,
                                      "msg": "repeated setup issues — probable stale screen or "
                                             "broken extract; halting for LLM inspection"}))
                    return 1
            if attempt < args.max_attempts:
                # Invoke restart.py when:
                # - Prior attempt was actually lost (modal already up), OR
                # - Prior attempt abandoned with a reason indicating the
                #   screen IS in a recoverable lose-state (e.g.
                #   game_over_at_start*: tray=7 visible but modal not yet
                #   triggered — autoplay tries to surface it before exiting,
                #   but if that fallback fails we still want to attempt
                #   restart.py).
                reason = result.get("reason") or ""
                should_restart = (
                    result["status"] == "lost"
                    or (result["status"] == "abandoned"
                        and reason.startswith("game_over_at_start"))
                )
                if should_restart and (ROOT / "data" / "restart_config.json").exists():
                    print(json.dumps({"event": "restart_run", "between_attempts": True,
                                      "prior_status": result["status"],
                                      "prior_reason": reason}))
                    rc = subprocess.run([
                        sys.executable, str(ROOT / "scripts" / "restart.py"),
                        "--level", str(level),
                        *(["--shot-dir", args.shot_dir] if args.shot_dir else []),
                    ]).returncode
                    if rc != 0:
                        print(json.dumps({"event": "restart_failed", "rc": rc,
                                          "msg": "falling back to fixed sleep"}))
                        time.sleep(args.inter_attempt_pause)
                else:
                    why = ("post-loss restart not configured"
                           if result["status"] == "lost"
                           else f"prior attempt abandoned (reason={reason}); "
                                "no modal-recovery path applies; "
                                "agent should inspect screen before next attempt")
                    print(json.dumps({"event": "pause_between_attempts",
                                      "seconds": args.inter_attempt_pause,
                                      "prior_status": result["status"],
                                      "prior_reason": reason,
                                      "msg": why}))
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
