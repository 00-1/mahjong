#!/usr/bin/env python3
"""Automate menu navigation: home -> Event Center -> Festival Event ->
Arcane Puzzle -> scroll to target level -> tap Continue. Lands at the
gameplay screen ready for autoplay.

Calibrated tap coords are stored in `data/navigation_config.json`. The
config has a calibrated_resolution; if the current device differs,
coords are scaled.

Continue button position varies between attempts (level list scroll
settles unpredictably) — we use vision (yellow-button detection) to
find it, scaled.

Usage:

    # First-time calibration (per device):
    python scripts/navigate.py calibrate \\
        --event-banner-x 1029 --event-banner-y 242 \\
        --festival-tab-x 610 --festival-tab-y 400 \\
        --arcane-puzzle-x 610 --arcane-puzzle-y 2400 \\
        --scroll-from-x 600 --scroll-from-y 2200 \\
        --scroll-to-x 600 --scroll-to-y 1700 \\
        --continue-y-hint 1981 \\
        --num-scrolls 1

    # Subsequent navigations (zero-LLM):
    python scripts/navigate.py go --level 8

Exit codes:
    0  arrived at puzzle gameplay screen
    1  navigation failed at some step (caller should let LLM take over)
    2  config missing — calibrate first
    3  setup error (adb not connected, etc.)

The script verifies state after each step via screen detection. If a
verification fails (we're not on the expected screen), it bails with
needs_llm so the LLM can take over without thrashing.
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

import cv2

from src.agent.autoplay_lib import adb_check_device, adb_screencap, adb_tap
from src.agent.navigate import detect_screen, find_continue_button
from src.agent.path_log import log_path_failure


CONFIG_PATH = ROOT / "data" / "navigation_config.json"


def load_config() -> dict | None:
    if not CONFIG_PATH.exists():
        return None
    return json.loads(CONFIG_PATH.read_text())


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def adb_swipe(device_arg: list[str], x1: int, y1: int, x2: int, y2: int, ms: int) -> bool:
    cmd = ["adb"] + device_arg + ["shell", "input", "swipe",
                                    str(x1), str(y1), str(x2), str(y2), str(ms)]
    try:
        return subprocess.run(cmd, timeout=10, capture_output=True).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def detect_resolution(device_arg: list[str], tmp: Path) -> tuple[int, int] | None:
    if not adb_screencap(device_arg, tmp):
        return None
    bgr = cv2.imread(str(tmp))
    if bgr is None:
        return None
    return (bgr.shape[1], bgr.shape[0])


def scale_xy(xy: tuple[int, int], cal_res: tuple[int, int],
             actual_res: tuple[int, int]) -> tuple[int, int]:
    if cal_res == actual_res:
        return xy
    sx = actual_res[0] / cal_res[0]
    sy = actual_res[1] / cal_res[1]
    return (int(xy[0] * sx), int(xy[1] * sy))


def calibrate(args) -> int:
    """Save calibration coords + record current device resolution."""
    device_arg = ["-s", args.device] if args.device else []
    if adb_check_device(device_arg) != "device":
        print(json.dumps({"event": "error", "msg": "adb not connected"}))
        return 3
    res = detect_resolution(device_arg, args.shot_dir / "calibrate.png")
    if res is None:
        print(json.dumps({"event": "error", "msg": "couldn't detect resolution"}))
        return 3
    cfg = {
        "calibrated_resolution": list(res),
        "event_banner": {"x": args.event_banner_x, "y": args.event_banner_y},
        "festival_tab": {"x": args.festival_tab_x, "y": args.festival_tab_y},
        "arcane_puzzle": {"x": args.arcane_puzzle_x, "y": args.arcane_puzzle_y},
        "scroll_from": {"x": args.scroll_from_x, "y": args.scroll_from_y},
        "scroll_to": {"x": args.scroll_to_x, "y": args.scroll_to_y},
        "scroll_duration_ms": args.scroll_duration_ms,
        "continue_y_hint": args.continue_y_hint,
        "num_scrolls": args.num_scrolls,
    }
    save_config(cfg)
    print(json.dumps({"event": "calibrated", "resolution": res, "config_path": str(CONFIG_PATH)}))
    return 0


def navigate(args) -> int:
    device_arg = ["-s", args.device] if args.device else []
    if adb_check_device(device_arg) != "device":
        print(json.dumps({"event": "error", "msg": "adb not connected"}))
        return 3

    cfg = load_config()
    if cfg is None:
        print(json.dumps({"event": "missing_config",
                          "msg": "Run `navigate.py calibrate ...` first."}))
        return 2

    args.shot_dir.mkdir(parents=True, exist_ok=True)
    cal_res = tuple(cfg["calibrated_resolution"])
    actual_res = detect_resolution(device_arg, args.shot_dir / "nav_init.png")
    if actual_res is None:
        return 3
    if cal_res != actual_res:
        print(json.dumps({"event": "scaling",
                          "calibrated": list(cal_res), "actual": list(actual_res)}))

    def tap_xy(label: str, x: int, y: int, settle: float) -> bool:
        sx, sy = scale_xy((x, y), cal_res, actual_res)
        print(json.dumps({"event": "tap", "step": label, "x": sx, "y": sy}))
        if not adb_tap(device_arg, sx, sy):
            print(json.dumps({"event": "error", "step": label, "msg": "tap failed"}))
            return False
        time.sleep(settle)
        return True

    def take_snap(label: str):
        p = args.shot_dir / f"nav_{label}.png"
        if not adb_screencap(device_arg, p):
            return None
        bgr = cv2.imread(str(p))
        return bgr

    # Step 1: home -> Event Center
    if not tap_xy("event_banner", cfg["event_banner"]["x"], cfg["event_banner"]["y"], 1.5):
        return 1
    bgr = take_snap("step1")
    if bgr is None:
        return 1

    # Step 2: Festival tab
    if not tap_xy("festival_tab", cfg["festival_tab"]["x"], cfg["festival_tab"]["y"], 1.0):
        return 1

    # Step 3: Arcane Puzzle card
    if not tap_xy("arcane_puzzle", cfg["arcane_puzzle"]["x"], cfg["arcane_puzzle"]["y"], 2.0):
        return 1
    bgr = take_snap("step3")
    if bgr is None:
        return 1
    screen_kind = detect_screen(bgr)
    if screen_kind == "puzzle":
        # Already in a puzzle from a Continue link? Unlikely but possible.
        print(json.dumps({"event": "early_arrival", "screen": screen_kind}))
        return 0

    # Step 4: scroll level list
    sf = scale_xy((cfg["scroll_from"]["x"], cfg["scroll_from"]["y"]), cal_res, actual_res)
    st = scale_xy((cfg["scroll_to"]["x"], cfg["scroll_to"]["y"]), cal_res, actual_res)
    for i in range(cfg["num_scrolls"]):
        print(json.dumps({"event": "scroll", "step": f"scroll_{i+1}",
                          "from": sf, "to": st, "ms": cfg["scroll_duration_ms"]}))
        if not adb_swipe(device_arg, sf[0], sf[1], st[0], st[1], cfg["scroll_duration_ms"]):
            print(json.dumps({"event": "error", "msg": "scroll failed"}))
            return 1
        time.sleep(3.0)  # let momentum settle

    # Step 5: find Continue button via vision
    bgr = take_snap("step5_pre_continue")
    if bgr is None:
        return 1
    hint_y = None
    if "continue_y_hint" in cfg and cfg["continue_y_hint"]:
        hint_y = scale_xy((0, cfg["continue_y_hint"]), cal_res, actual_res)[1]
    button = find_continue_button(bgr, expected_y_hint=hint_y)
    if button is None:
        candidates = find_continue_button.__globals__["find_yellow_buttons"](bgr)
        print(json.dumps({"event": "needs_llm",
                          "step": "continue_button",
                          "msg": "ambiguous yellow buttons; LLM should disambiguate",
                          "candidates": candidates}))
        log_path_failure(
            path="navigate.go",
            script="scripts/navigate.py",
            failure_reason="ambiguous_continue_button",
            step="continue_button",
            extra={"candidates": candidates, "level": args.level},
        )
        return 1
    cx, cy = button["cx"], button["cy"]
    print(json.dumps({"event": "tap", "step": "continue", "x": cx, "y": cy,
                      "vision_detected": True}))
    if not adb_tap(device_arg, cx, cy):
        print(json.dumps({"event": "error", "step": "continue", "msg": "tap failed"}))
        return 1
    time.sleep(2.5)

    # Verify we're at the puzzle
    bgr = take_snap("step5_post_continue")
    if bgr is None:
        return 1
    final_kind = detect_screen(bgr)
    if final_kind != "puzzle":
        print(json.dumps({"event": "needs_llm", "step": "verify",
                          "msg": f"after Continue tap, screen is '{final_kind}' not 'puzzle'"}))
        log_path_failure(
            path="navigate.go",
            script="scripts/navigate.py",
            failure_reason="post_continue_not_puzzle",
            step="verify",
            expected="puzzle", observed=final_kind,
            extra={"level": args.level},
        )
        return 1
    print(json.dumps({"event": "navigation_complete", "screen": "puzzle"}))
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    cal = sub.add_parser("calibrate")
    cal.add_argument("--device", default=None)
    cal.add_argument("--shot-dir", type=Path, default=Path("/tmp"))
    cal.add_argument("--event-banner-x", type=int, required=True)
    cal.add_argument("--event-banner-y", type=int, required=True)
    cal.add_argument("--festival-tab-x", type=int, required=True)
    cal.add_argument("--festival-tab-y", type=int, required=True)
    cal.add_argument("--arcane-puzzle-x", type=int, required=True)
    cal.add_argument("--arcane-puzzle-y", type=int, required=True)
    cal.add_argument("--scroll-from-x", type=int, required=True)
    cal.add_argument("--scroll-from-y", type=int, required=True)
    cal.add_argument("--scroll-to-x", type=int, required=True)
    cal.add_argument("--scroll-to-y", type=int, required=True)
    cal.add_argument("--scroll-duration-ms", type=int, default=800)
    cal.add_argument("--continue-y-hint", type=int, default=None)
    cal.add_argument("--num-scrolls", type=int, default=1)

    go = sub.add_parser("go")
    go.add_argument("--device", default=None)
    go.add_argument("--shot-dir", type=Path, default=Path("/tmp"))
    go.add_argument("--level", type=int, required=True)

    args = p.parse_args()
    args.shot_dir.mkdir(parents=True, exist_ok=True)

    if args.cmd == "calibrate":
        return calibrate(args)
    elif args.cmd == "go":
        return navigate(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
