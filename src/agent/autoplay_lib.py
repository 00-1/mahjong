"""Helpers for autoplay.py: snap+extract, adaptive wait, win heuristic.

Pulled out of the main script so it can be unit-tested and so a future
session orchestrator can call them too.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


ADB_TIMEOUT = 15


def adb(device_arg: list[str], *args: str, timeout: int = ADB_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(["adb"] + device_arg + list(args), capture_output=True, timeout=timeout)


def adb_screencap(device_arg: list[str], output_path: Path) -> bool:
    try:
        r = adb(device_arg, "exec-out", "screencap", "-p")
        if r.returncode != 0:
            return False
        output_path.write_bytes(r.stdout)
        return output_path.stat().st_size > 1000
    except subprocess.TimeoutExpired:
        return False


def adb_tap(device_arg: list[str], x: int, y: int) -> bool:
    try:
        r = adb(device_arg, "shell", "input", "tap", str(x), str(y))
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def adb_check_device(device_arg: list[str]) -> str | None:
    try:
        r = adb(device_arg, "get-state", timeout=5)
        if r.returncode != 0:
            return None
        return r.stdout.decode().strip()
    except Exception:
        return None


def snap_and_extract(
    device_arg: list[str],
    shot_path: Path,
    level: int,
) -> tuple[dict | None, tuple[int, int] | None]:
    """Take a screenshot, run extraction, return (state_dict, image_size)."""
    if not adb_screencap(device_arg, shot_path):
        return None, None
    extract = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "extract_board.py"),
         str(shot_path), "--level", str(level)],
        capture_output=True, text=True,
    )
    if extract.returncode != 0:
        return None, None
    state_path = (
        ROOT / "data" / "extractions" / f"level_{level:02d}"
        / shot_path.stem / "state.json"
    )
    if not state_path.exists():
        return None, None
    try:
        import cv2
        img = cv2.imread(str(shot_path))
        size = (img.shape[1], img.shape[0]) if img is not None else None
    except Exception:
        size = None
    with open(state_path) as f:
        return json.load(f), size


def state_signature(state: dict) -> tuple:
    """Hashable summary of the parts of state that matter for decision-making.
    Used to detect 'state didn't change' for adaptive wait + loop detection."""
    main = tuple(sorted(
        (c["row"], c["col"], c["tile_id"], c.get("stack_depth"))
        for c in state.get("main_board", []) if c.get("tile_id")
    ))
    queues = tuple(sorted(
        (q["queue_id"], q["tile_id"])
        for q in state.get("queues", []) if q.get("tile_id")
    ))
    tray = tuple(
        t.get("tile_id") for t in state.get("tray", [])
    )
    return (main, queues, tray)


def adaptive_wait_for_change(
    device_arg: list[str],
    shot_dir: Path,
    level: int,
    before_sig: tuple,
    *,
    min_wait: float = 0.3,
    max_wait: float = 3.0,
    poll_interval: float = 0.25,
) -> tuple[dict | None, tuple[int, int] | None, float, Path | None]:
    """Poll for state change after a tap. Returns (after_state, image_size,
    elapsed_sec, shot_path). shot_path is the file whose state was returned
    (state.json is guaranteed to exist for it). If no change after max_wait,
    returns the most recent successful extract — or (None, None, elapsed, None)
    if every extract failed.

    Returning shot_path explicitly avoids a race where the caller would glob
    the shot_dir for the latest .png and pick up an orphan whose extract
    failed, causing a downstream FileNotFoundError on state.json.

    Saves intermediate snap PNGs as autoplay_wait_*.png — they're temporary
    debugging aids; pruned after run end if you want.
    """
    time.sleep(min_wait)
    elapsed = min_wait
    snap_idx = 0
    last_state: dict | None = None
    last_size: tuple[int, int] | None = None
    last_good_shot: Path | None = None
    while elapsed <= max_wait:
        snap_idx += 1
        shot_path = shot_dir / f"autoplay_wait_{int(time.time()*1000)}_{snap_idx}.png"
        state, size = snap_and_extract(device_arg, shot_path, level)
        if state is not None:
            last_state, last_size, last_good_shot = state, size, shot_path
            if state_signature(state) != before_sig:
                return state, size, elapsed, shot_path
        time.sleep(poll_interval)
        elapsed += poll_interval
    return last_state, last_size, elapsed, last_good_shot


def heuristic_outcome(last_state: dict | None,
                      previous_state: dict | None = None) -> str:
    """Given the final state observed before a NOT_A_PUZZLE / abandon,
    guess won vs lost vs abandoned.

    Heuristics (in priority order):
    - If the last state had tray at 7: lost (game over).
    - If last state has 0 visible tiles AND previous state had a near-full
      tray: lost via the "Use Discard or Withdraw" modal flow.
    - If last state had < 3 tiles total AND previous state was near-empty
      with no full tray: probably won.
    - Otherwise: abandoned (couldn't tell).

    Note: we used to call any 'no tiles after several NOT_A_PUZZLE' a win,
    but the post-loss modal also produces 'no tiles' — so we now require
    a previous state showing the puzzle was nearly complete before
    declaring victory.
    """
    if last_state is None:
        return "abandoned"
    tray_filled = sum(1 for t in last_state.get("tray", []) if t.get("tile_id"))
    main_count = len(last_state.get("main_board", []))
    queue_count = len(last_state.get("queues", []))
    total_visible = main_count + queue_count
    if tray_filled >= 7:
        return "lost"

    if previous_state is not None:
        prev_tray = sum(1 for t in previous_state.get("tray", []) if t.get("tile_id"))
        prev_main = len(previous_state.get("main_board", []))
        prev_queue = len(previous_state.get("queues", []))
        prev_total = prev_main + prev_queue

        # Modal-on-tray-full: previous tray was near full, we lost a triplet
        # race, modal appeared blocking the puzzle. NOT a win.
        if prev_tray >= 5 and total_visible == 0:
            return "lost"

        # Genuine clear: previous state had very few tiles, board cleared
        # naturally, level-complete popup appeared.
        if prev_total <= 6 and prev_tray < 3 and total_visible == 0:
            return "won"

    # Fallback: with no context, conservative call
    if total_visible < 3 and tray_filled < 3:
        return "abandoned"  # used to be "won" — too risky without context
    return "abandoned"
