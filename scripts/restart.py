#!/usr/bin/env python3
"""Post-loss restart flow: dismiss modal -> Challenge Again -> back to puzzle.

The level-8 loss flow as documented by the agent:
1. Tray fills -> "Use Discard or Withdraw" Tip modal appears
2. Tap Discard button -> LOSE screen appears
3. Tap "Challenge Again" -> fresh puzzle loads

This script automates that, using calibrated tap coords from a config.
First run: pass coords via CLI flags; the script saves them for reuse.
Subsequent runs: just `restart.py` reads the saved config.

Usage:
    # First-time calibration (agent identifies buttons via snap, then runs):
    python scripts/restart.py \\
        --discard-x 950 --discard-y 1500 \\
        --challenge-again-x 610 --challenge-again-y 2100

    # Subsequent restarts (just execute):
    python scripts/restart.py

Exit codes:
    0 - back at puzzle gameplay screen, ready for next autoplay run
    1 - couldn't recover (modal not detected, button taps failed, etc.)
    2 - config missing, must calibrate first

Integrates with session.py: when autoplay returns 1 (lost), call this
script to recover before the next attempt.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.autoplay_lib import adb_check_device, adb_screencap, adb_tap
from src.agent.path_log import log_path_failure
from src.vision.detect import DetectConfig, detect_tile_faces

import cv2


CONFIG_PATH = ROOT / "data" / "restart_config.json"


def load_config() -> dict | None:
    if not CONFIG_PATH.exists():
        return None
    return json.loads(CONFIG_PATH.read_text())


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def looks_like_puzzle(device_arg: list[str], tmp_path: Path) -> bool:
    """Use the same heuristic as agent.py check: >= 6 tile faces detected
    means we're on a puzzle gameplay screen."""
    if not adb_screencap(device_arg, tmp_path):
        return False
    bgr = cv2.imread(str(tmp_path))
    if bgr is None:
        return False
    return len(detect_tile_faces(bgr, DetectConfig())) >= 6


def detect_resolution(device_arg: list[str], tmp_path: Path) -> tuple[int, int] | None:
    """Take a screenshot and read its dimensions."""
    if not adb_screencap(device_arg, tmp_path):
        return None
    bgr = cv2.imread(str(tmp_path))
    if bgr is None:
        return None
    return (bgr.shape[1], bgr.shape[0])


def scale_coords(coords: dict, calibrated_resolution: tuple[int, int],
                 actual_resolution: tuple[int, int]) -> dict:
    """Scale (x, y) from the calibration resolution to the device's actual
    resolution. Coords are stored verbatim; scaled at execution time."""
    cal_w, cal_h = calibrated_resolution
    act_w, act_h = actual_resolution
    if (cal_w, cal_h) == (act_w, act_h):
        return coords
    sx = act_w / cal_w
    sy = act_h / cal_h
    return {"x": int(coords["x"] * sx), "y": int(coords["y"] * sy)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--device", default=None)
    p.add_argument("--shot-dir", type=Path, default=Path("/tmp"))
    p.add_argument("--discard-x", type=int, default=None,
                   help="Discard button x-coord (modal). First-run calibration.")
    p.add_argument("--discard-y", type=int, default=None)
    p.add_argument("--challenge-again-x", type=int, default=None,
                   help="Challenge Again button x-coord (lose screen)")
    p.add_argument("--challenge-again-y", type=int, default=None)
    p.add_argument("--modal-wait", type=float, default=2.0,
                   help="Seconds to wait for modal to appear after tray-full")
    p.add_argument("--lose-screen-wait", type=float, default=2.5,
                   help="Seconds to wait for lose screen after Discard tap")
    p.add_argument("--puzzle-load-wait", type=float, default=4.0,
                   help="Seconds to wait for fresh puzzle to load after Challenge Again")
    p.add_argument("--max-puzzle-poll", type=int, default=10,
                   help="Number of times to retry checking for puzzle after load")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    device_arg = ["-s", args.device] if args.device else []

    if adb_check_device(device_arg) != "device":
        print(json.dumps({"event": "error", "msg": "adb device unreachable"}))
        return 1

    args.shot_dir.mkdir(parents=True, exist_ok=True)

    # Load existing config; merge with any CLI overrides
    cfg = load_config() or {}
    if args.discard_x is not None and args.discard_y is not None:
        cfg["discard"] = {"x": args.discard_x, "y": args.discard_y}
    if args.challenge_again_x is not None and args.challenge_again_y is not None:
        cfg["challenge_again"] = {"x": args.challenge_again_x, "y": args.challenge_again_y}

    if "discard" not in cfg or "challenge_again" not in cfg:
        print(json.dumps({
            "event": "missing_config",
            "msg": ("First-time setup: pass --discard-x/y and --challenge-again-x/y "
                    "based on the buttons in your post-loss modal flow. Optionally "
                    "pass --calibrated-resolution WxH if you're not on the same "
                    "device the coords were calibrated on."),
        }))
        return 2

    # On first calibration, record the resolution so future runs on
    # different-size phones can scale.
    if "calibrated_resolution" not in cfg:
        # Take an initial snapshot to record the calibration resolution
        res = detect_resolution(device_arg, args.shot_dir / "restart_init.png")
        if res:
            cfg["calibrated_resolution"] = list(res)

    save_config(cfg)

    # Scale coords for current device if it differs from the calibrated one
    actual_res = detect_resolution(device_arg, args.shot_dir / "restart_init.png")
    if actual_res and "calibrated_resolution" in cfg:
        cal_res = tuple(cfg["calibrated_resolution"])
        if cal_res != actual_res:
            cfg_use = {
                "discard": scale_coords(cfg["discard"], cal_res, actual_res),
                "challenge_again": scale_coords(cfg["challenge_again"], cal_res, actual_res),
            }
            print(json.dumps({"event": "scaled_coords",
                              "calibrated": cal_res, "actual": actual_res,
                              "scaled_config": cfg_use}))
        else:
            cfg_use = cfg
    else:
        cfg_use = cfg

    print(json.dumps({"event": "restart_start", "config": cfg_use}))

    # Step 1: wait for modal, tap Discard
    time.sleep(args.modal_wait)
    print(json.dumps({"event": "tap_discard", "x": cfg_use["discard"]["x"], "y": cfg_use["discard"]["y"]}))
    if not adb_tap(device_arg, cfg_use["discard"]["x"], cfg_use["discard"]["y"]):
        print(json.dumps({"event": "error", "msg": "discard tap failed"}))
        return 1

    # Step 2: wait for lose screen, tap Challenge Again
    time.sleep(args.lose_screen_wait)
    print(json.dumps({"event": "tap_challenge_again",
                      "x": cfg_use["challenge_again"]["x"], "y": cfg_use["challenge_again"]["y"]}))
    if not adb_tap(device_arg, cfg_use["challenge_again"]["x"], cfg_use["challenge_again"]["y"]):
        print(json.dumps({"event": "error", "msg": "challenge_again tap failed"}))
        return 1

    # Step 3: poll until fresh puzzle is loaded
    time.sleep(args.puzzle_load_wait)
    tmp = args.shot_dir / "restart_check.png"
    for attempt in range(1, args.max_puzzle_poll + 1):
        if looks_like_puzzle(device_arg, tmp):
            print(json.dumps({"event": "restart_ok", "attempt": attempt}))
            return 0
        if args.verbose:
            print(json.dumps({"event": "puzzle_not_yet_visible", "attempt": attempt}))
        time.sleep(1.0)

    print(json.dumps({"event": "error",
                      "msg": "fresh puzzle never appeared after Challenge Again"}))
    log_path_failure(
        path="restart",
        script="scripts/restart.py",
        failure_reason="puzzle_not_visible_after_challenge_again",
        step="puzzle_load_poll",
        expected="puzzle", observed="non-puzzle screen",
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
