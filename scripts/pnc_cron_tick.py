#!/usr/bin/env python3
"""PNC cron-tick orchestrator: one entry the cron prompt invokes.

Sequence:
  1. Run popup_dismiss to clear any launch chain.
  2. Snap. If sapphire panel is idle or timer < 6 h, run pnc_sapphire.
  3. Run pnc_iron_gather (5/5 → 1, ≥1 send → 0).
  4. Snap. Read troop count and emit a `next_recheck` line containing
     the cadence.next_recheck delay. The cron prompt schedules the
     next CronCreate from that delay.

Each child script is invoked via subprocess so its JSON event log
streams through to the same stdout. Failures of one phase don't block
the others — the orchestrator gives every phase a chance to act.

Usage:
    python3 scripts/pnc_cron_tick.py
    python3 scripts/pnc_cron_tick.py --skip-sapphire --verbose
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
sys.path.insert(0, str(ROOT))

import cv2

from src.pnc.cadence import TroopState, next_recheck
from src.pnc.state import read_sapphire_sidepanel, read_troop_count


SCRIPTS = ROOT / "scripts"


def emit(event: str, **fields):
    print(json.dumps({
        "event": event,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "phase": "tick",
        **fields,
    }), flush=True)


def snap(tmp: Path):
    raw = subprocess.run(
        ["adb", "exec-out", "screencap", "-p"],
        capture_output=True, timeout=15,
    ).stdout
    tmp.write_bytes(raw)
    return cv2.imread(str(tmp))


def run_phase(name: str, argv: list[str]) -> int:
    """Run a child script and stream its output through. Returns its
    exit code."""
    emit("phase_start", name=name, argv=argv)
    res = subprocess.run(argv, capture_output=False)
    emit("phase_end", name=name, code=res.returncode)
    return res.returncode


def should_run_sapphire(tmp: Path) -> tuple[bool, str]:
    """Inspect the city-side panel. Run if state==idle, or if the timer
    is below 6h. We can't yet parse the timer to seconds, so 'active'
    is conservatively assumed to mean don't-run-yet — the user has
    asked us to act when timer < 6h, which currently requires manual
    judgement until OCR lands."""
    bgr = snap(tmp)
    if bgr is None:
        return False, "snap_failed"
    panel = read_sapphire_sidepanel(bgr)
    if panel.state == "idle":
        return True, "sapphire_idle"
    if panel.state == "active":
        # Conservative: skip until timer parsing is in. Future:
        # if panel.timer_seconds is not None and panel.timer_seconds < 6*3600: True
        return False, "sapphire_active_timer_unknown"
    return False, "sapphire_panel_absent"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--shot-dir", type=Path, default=Path.home() / "snaps")
    p.add_argument("--skip-popup", action="store_true")
    p.add_argument("--skip-sapphire", action="store_true")
    p.add_argument("--skip-iron", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    args.shot_dir.mkdir(parents=True, exist_ok=True)
    tmp = args.shot_dir / "tick.png"

    # Phase 1: popup dismiss
    if not args.skip_popup:
        run_phase("popup_dismiss", [
            sys.executable, str(SCRIPTS / "pnc_popup_dismiss.py"),
            "--shot-dir", str(args.shot_dir),
        ])

    # Phase 2: sapphire (only if conditions warrant)
    if not args.skip_sapphire:
        should_run, why = should_run_sapphire(tmp)
        emit("sapphire_decision", run=should_run, reason=why)
        if should_run:
            run_phase("sapphire", [
                sys.executable, str(SCRIPTS / "pnc_sapphire.py"),
                "--shot-dir", str(args.shot_dir),
            ])
            # Sapphire flow lands on world view via Depart; popups can
            # surface (e.g., reward toast). Do another popup sweep.
            time.sleep(2)
            run_phase("popup_dismiss_post_sapphire", [
                sys.executable, str(SCRIPTS / "pnc_popup_dismiss.py"),
                "--shot-dir", str(args.shot_dir),
                "--max-rounds", "4",
            ])

    # Phase 3: iron gather
    if not args.skip_iron:
        run_phase("iron_gather", [
            sys.executable, str(SCRIPTS / "pnc_iron_gather.py"),
            "--shot-dir", str(args.shot_dir),
        ])

    # Phase 4: schedule next recheck
    bgr = snap(tmp)
    if bgr is None:
        emit("schedule_failed", reason="snap_failed")
        return 3
    info = read_troop_count(bgr)
    if info.n_active is None:
        # Not on world view. Caller decides — emit a default.
        emit("next_recheck", delay_seconds=30 * 60,
             reason="not_on_world_view_after_tick")
        return 0

    # We can't read individual timers yet; build a degenerate
    # TroopState list of n_active "long timer" troops and let
    # cadence.next_recheck pick the safe default.
    troops = [TroopState(seconds_remaining=4 * 3600, kind="gather")
              for _ in range(info.n_active)]
    plan = next_recheck(troops, n_total=info.n_total)
    emit("next_recheck",
         delay_seconds=plan.delay_seconds,
         reason=plan.reason,
         n_active=info.n_active,
         n_total=info.n_total,
         note=("timer-parsing not yet wired — using conservative all-long "
               "estimate; cadence will refine once HH:MM:SS OCR lands"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
