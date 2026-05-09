#!/usr/bin/env python3
"""Self-driving play loop: screenshot, decide, tap, sleep — no LLM in the loop.

Runs an entire level autonomously. Calls the local solver for each move,
talks to ADB directly for screencaps and taps. Logs every step under
`data/runs/<run_id>/`. Exits when the level is won, lost, or stuck.

Usage:
    python scripts/autoplay.py --level 8 [options]

Options:
    --device SERIAL       adb device serial (omit if only one device connected)
    --max-steps N         abort after N steps (default 200)
    --tap-settle SEC      sleep after each tap (default 1.5)
    --triplet-settle SEC  sleep after triplet-completing taps (default 2.5)
    --shot-dir PATH       where to put transient screencap PNGs (default /tmp)
    --keep-screenshots    save each screenshot in the run dir (default off)
    --run-id ID           use a specific run id (default auto)
    --no-stats            don't integrate into per-level stats (e.g. for testing)
    --verbose             extra logging

Exit codes:
    0  won
    1  lost
    2  abandoned (stuck, max-steps, ADB error, etc.)
    3  setup error (adb not connected, level not found, etc.)
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

import cv2  # noqa: E402

from src.agent.decide import decide as decide_fn
from src.agent.run import end_run, next_step_number, record_step, save_meta, start_run
from src.agent.stats import integrate_run


ADB_TIMEOUT = 15
TRIPLET_REASONS = {"TRIPLET", "PROBABLE"}


def _adb(device_arg: list[str], *args: str, capture: bool = True, timeout: int = ADB_TIMEOUT) -> subprocess.CompletedProcess:
    cmd = ["adb"] + device_arg + list(args)
    return subprocess.run(cmd, capture_output=capture, timeout=timeout)


def adb_screencap(device_arg: list[str], output_path: Path) -> bool:
    try:
        r = _adb(device_arg, "exec-out", "screencap", "-p")
        if r.returncode != 0:
            return False
        output_path.write_bytes(r.stdout)
        return output_path.stat().st_size > 1000
    except subprocess.TimeoutExpired:
        return False


def adb_tap(device_arg: list[str], x: int, y: int) -> bool:
    try:
        r = _adb(device_arg, "shell", "input", "tap", str(x), str(y))
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def adb_check_device(device_arg: list[str]) -> str | None:
    """Return device state from `adb get-state`, or None if not reachable."""
    try:
        r = _adb(device_arg, "get-state", timeout=5)
        if r.returncode != 0:
            return None
        return r.stdout.decode().strip()
    except Exception:
        return None


def load_labels(tiles_dir: Path) -> dict:
    idx = tiles_dir / "index.json"
    if not idx.exists():
        return {}
    return {
        e["tile_id"]: e.get("label") or e["tile_id"]
        for e in json.loads(idx.read_text()).get("entries", [])
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--level", type=int, required=True)
    p.add_argument("--device", default=None)
    p.add_argument("--max-steps", type=int, default=200)
    p.add_argument("--tap-settle", type=float, default=1.5)
    p.add_argument("--triplet-settle", type=float, default=2.5)
    p.add_argument("--shot-dir", type=Path, default=Path("/tmp"))
    p.add_argument("--keep-screenshots", action="store_true")
    p.add_argument("--run-id", default=None)
    p.add_argument("--no-stats", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--tiles-dir", type=Path, default=ROOT / "data" / "tiles")
    args = p.parse_args()

    device_arg = ["-s", args.device] if args.device else []

    state = adb_check_device(device_arg)
    if state != "device":
        print(f"[autoplay] adb device unreachable (state={state!r}). Connect first.", file=sys.stderr)
        return 3

    args.shot_dir.mkdir(parents=True, exist_ok=True)
    labels = load_labels(args.tiles_dir)
    label_fn = lambda t: labels.get(t, t) if t else "?"  # noqa: E731

    runs_dir = ROOT / "data" / "runs"
    meta = start_run(runs_dir, args.level, args.run_id)
    run_id = meta.run_id
    print(json.dumps({"event": "run_start", "run_id": run_id, "level": args.level,
                      "started_at": meta.started_at}))

    step = 0
    final_status = "abandoned"
    consecutive_not_a_puzzle = 0
    last_decision = None

    try:
        while step < args.max_steps:
            shot_path = args.shot_dir / f"autoplay_{run_id}_{step:03d}.png"

            if not adb_screencap(device_arg, shot_path):
                print(json.dumps({"event": "error", "step": step, "msg": "screencap failed"}))
                final_status = "abandoned"
                break

            extract = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "extract_board.py"),
                 str(shot_path), "--level", str(args.level)],
                capture_output=True, text=True,
            )
            if extract.returncode != 0:
                print(json.dumps({"event": "error", "step": step,
                                  "msg": "extract failed", "stderr": extract.stderr.strip()}))
                final_status = "abandoned"
                break

            state_path = (
                ROOT / "data" / "extractions" / f"level_{args.level:02d}"
                / shot_path.stem / "state.json"
            )
            if not state_path.exists():
                print(json.dumps({"event": "error", "step": step,
                                  "msg": "state.json missing"}))
                final_status = "abandoned"
                break

            img = cv2.imread(str(shot_path))
            if img is None:
                final_status = "abandoned"
                break
            image_size = (img.shape[1], img.shape[0])

            decision = decide_fn(state_path, image_size, label_fn=label_fn)

            with open(state_path) as f:
                state_dict = json.load(f)
            record_step(
                runs_dir, run_id, step, shot_path, state_dict, decision,
                keep_screenshot=args.keep_screenshots,
            )
            meta.last_step = step
            save_meta(runs_dir, meta)
            last_decision = decision

            reason = decision.get("reason_code", "")
            if args.verbose:
                summary = {
                    "step": step, "reason": reason,
                    "tray": decision.get("state", {}).get("tray_filled"),
                    "tap": decision.get("tap"),
                }
                print(json.dumps({"event": "decision", **summary}))

            if decision.get("should_stop"):
                if reason == "GAME_OVER":
                    final_status = "lost"
                    print(json.dumps({"event": "game_over", "step": step}))
                    break
                if reason == "NOT_A_PUZZLE":
                    consecutive_not_a_puzzle += 1
                    print(json.dumps({"event": "not_a_puzzle", "step": step,
                                      "consecutive": consecutive_not_a_puzzle}))
                    if consecutive_not_a_puzzle >= 5:
                        # After 5 NOT_A_PUZZLE in a row we're stuck — probably
                        # the level finished or popped up something we can't
                        # dismiss. Hand control back.
                        final_status = "abandoned"
                        break
                    time.sleep(2.0)
                    step += 1
                    continue
                # NO_MOVES, EXTRACTION_FAILED, etc.
                final_status = "abandoned"
                print(json.dumps({"event": "stop", "step": step, "reason": reason,
                                  "msg": decision.get("reason")}))
                break

            consecutive_not_a_puzzle = 0

            # Speed-up: if a full triplet sequence is available, blast all
            # taps in sequence without re-snapping. ~3x faster than one
            # decide cycle per tap.
            triplet_seq = decision.get("triplet_sequence")
            if triplet_seq and len(triplet_seq) >= 2:
                print(json.dumps({
                    "event": "triplet_burst", "step": step,
                    "tile": decision.get("label"),
                    "taps": len(triplet_seq),
                    "locations": [t["location"] for t in triplet_seq],
                }))
                burst_ok = True
                for t in triplet_seq:
                    if not adb_tap(device_arg, t["x"], t["y"]):
                        burst_ok = False
                        break
                    time.sleep(0.4)  # short per-tap delay; game queues taps
                if not burst_ok:
                    print(json.dumps({"event": "error", "step": step, "msg": "burst tap failed"}))
                    final_status = "abandoned"
                    break
                # After the full triplet, wait longer for the auto-clear animation
                time.sleep(args.triplet_settle)
                step += 1
                continue

            tap = decision.get("tap")
            if not tap:
                final_status = "abandoned"
                break

            x, y = tap["x"], tap["y"]
            print(json.dumps({
                "event": "tap", "step": step,
                "x": x, "y": y, "loc": tap.get("location"),
                "tile": decision.get("label"), "reason": reason,
                "score": decision.get("score"),
            }))
            if not adb_tap(device_arg, x, y):
                print(json.dumps({"event": "error", "step": step, "msg": "tap failed"}))
                final_status = "abandoned"
                break

            settle = args.triplet_settle if reason in TRIPLET_REASONS else args.tap_settle
            time.sleep(settle)
            step += 1

        else:
            print(json.dumps({"event": "max_steps_reached", "step": step}))
            final_status = "abandoned"

    except KeyboardInterrupt:
        print(json.dumps({"event": "keyboard_interrupt", "step": step}))
        final_status = "abandoned"

    end_run(runs_dir, run_id, final_status)
    if not args.no_stats:
        levels_root = ROOT / "data" / "levels"
        stats = integrate_run(levels_root, runs_dir, run_id)
        win_rate = stats.win_rate() if stats else None
    else:
        win_rate = None

    print(json.dumps({
        "event": "run_end",
        "run_id": run_id,
        "status": final_status,
        "steps": step,
        "level": args.level,
        "level_win_rate": win_rate,
    }))

    return {"won": 0, "lost": 1, "abandoned": 2}.get(final_status, 2)


if __name__ == "__main__":
    sys.exit(main())
