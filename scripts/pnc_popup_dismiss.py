#!/usr/bin/env python3
"""Dismiss the chain of PNC popups that appear on launch / after long idle.

Loops: snap → detect → tap close → wait → repeat.
Exits 0 once `detect_popup` returns None (city/world view reached) or
after `--max-rounds` iterations with no recognized popup.

Usage:
    python3 scripts/pnc_popup_dismiss.py
    python3 scripts/pnc_popup_dismiss.py --max-rounds 8 --verbose
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

from src.pnc.state import detect_popup


def adb(*args: str) -> str:
    """Run adb shell <args> and return stdout."""
    return subprocess.run(
        ["adb", "shell", *args],
        capture_output=True, text=True, timeout=30,
    ).stdout


def snap(tmp: Path):
    raw = subprocess.run(
        ["adb", "exec-out", "screencap", "-p"],
        capture_output=True, timeout=15,
    ).stdout
    tmp.write_bytes(raw)
    return cv2.imread(str(tmp))


def emit(event: str, **fields):
    print(json.dumps({
        "event": event,
        "ts": datetime.now().isoformat(timespec="seconds"),
        **fields,
    }), flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-rounds", type=int, default=8,
                   help="Stop after this many rounds with nothing detected (default 8)")
    p.add_argument("--shot-dir", type=Path, default=Path.home() / "snaps")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    args.shot_dir.mkdir(parents=True, exist_ok=True)
    tmp = args.shot_dir / "popup_check.png"

    consecutive_clean = 0
    rounds = 0
    while consecutive_clean < 2 and rounds < args.max_rounds:
        rounds += 1
        bgr = snap(tmp)
        if bgr is None:
            emit("snap_failed", round=rounds)
            time.sleep(2)
            continue

        popup = detect_popup(bgr)
        if popup is None:
            consecutive_clean += 1
            emit("clean", round=rounds, consecutive=consecutive_clean)
            time.sleep(1)
            continue

        consecutive_clean = 0
        emit("popup_detected", round=rounds, name=popup.name,
             close_xy=list(popup.close_xy))

        if popup.name == "limited_offer":
            # No close X — back-key
            adb("input", "keyevent", "4")
        elif popup.name == "battery_saver":
            adb("input", "tap", str(popup.close_xy[0]), str(popup.close_xy[1]))
            # Battery saver dialog backgrounds PNC; re-launch.
            time.sleep(2)
            adb("monkey", "-p", "com.global.pnck",
                "-c", "android.intent.category.LAUNCHER", "1")
            time.sleep(7)
        elif popup.name == "generic_tip_confirm":
            # CONFIRM-only modal (Connection-failed / New-version-found)
            cx, cy = popup.confirm_xy or popup.close_xy
            adb("input", "tap", str(cx), str(cy))
            # Loading splash after CONFIRM can take 25s+
            time.sleep(20)
        else:
            # All others have a close X — tap it
            cx, cy = popup.close_xy
            adb("input", "tap", str(cx), str(cy))
            time.sleep(3)

    emit("done", rounds=rounds, consecutive_clean=consecutive_clean)
    return 0 if consecutive_clean >= 2 else 1


if __name__ == "__main__":
    sys.exit(main())
