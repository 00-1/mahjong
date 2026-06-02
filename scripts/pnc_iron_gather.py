#!/usr/bin/env python3
"""PNC iron-gather cycle: send marches to Lv5 furnaces from free troop slots.

Composes:
  - state.in_world_view: are we on the world map?
  - state.read_troop_count: how many marches are out / free?
  - state.read_search_panel_lv: is the slider on Lv5?
  - calibrated taps from GATHER_RUN_STANDARD.md

Designed to be cron-fired. Idempotent on snap/check failures (returns
non-zero so the caller can decide whether to retry sooner). Real
mutating taps only happen once vision says the screen is in the
expected state.

Usage:
    python3 scripts/pnc_iron_gather.py
    python3 scripts/pnc_iron_gather.py --dry-run --verbose
    python3 scripts/pnc_iron_gather.py --max-sends 2

Exit codes:
    0  at least one march dispatched
    1  no free slots (5/5 already out) — schedule based on shortest timer
    2  abandoned (couldn't reach world view, popup loop, slider stuck)
    3  setup error (adb missing, snap failed)
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

from src.pnc.state import (
    detect_popup,
    in_world_view,
    is_furnace_tab_active,
    read_search_panel_lv,
    read_troop_count,
)


# Calibrated taps (1080×2400). All from GATHER_RUN_STANDARD.md.
TAP_WORLD_NAV = (84, 2310)
TAP_SEARCH_MAGNIFIER = (115, 1950)
TAP_FURNACE_TAB = (940, 1850)             # post-swipe Furnace position
SWIPE_TABS_LEFT = (1000, 1850, 100, 1850, 500)  # reveals Quarry/Furnace
TAP_SLIDER_MINUS = (70, 1980)
TAP_SLIDER_PLUS = (1015, 1980)
TAP_SEARCH_BUTTON = (540, 2280)
TAP_GATHER_MARKER = (520, 650)
TAP_DEPART_CTA = (540, 2295)
TAP_SEARCH_CLOSE_X = (1015, 1530)

TARGET_LV = 5


def adb(*args: str, timeout: int = 30) -> str:
    return subprocess.run(
        ["adb", "shell", *args],
        capture_output=True, text=True, timeout=timeout,
    ).stdout


def tap(x: int, y: int):
    adb("input", "tap", str(x), str(y))


def keyevent(code: int):
    adb("input", "keyevent", str(code))


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


def ensure_world_view(tmp: Path, dry_run: bool) -> bool:
    """Snap; if in city, tap WORLD; re-snap and confirm. Returns True if
    we're on world view at exit, False otherwise."""
    bgr = snap(tmp)
    if bgr is None:
        emit("snap_failed", phase="ensure_world_view")
        return False
    if detect_popup(bgr) is not None:
        emit("popup_blocking", phase="ensure_world_view")
        return False
    if in_world_view(bgr):
        return True
    emit("city_view_detected", action="tap_world")
    if dry_run:
        return True
    tap(*TAP_WORLD_NAV)
    time.sleep(3)
    bgr = snap(tmp)
    if bgr is None:
        return False
    return in_world_view(bgr)


def adjust_slider_to_target(tmp: Path, dry_run: bool) -> int | None:
    """Snap-and-verify the slider sits on TARGET_LV. Adjust with
    plus/minus buttons until it does. Returns final Lv, or None if
    the search panel isn't open."""
    bgr = snap(tmp)
    if bgr is None:
        return None
    lv = read_search_panel_lv(bgr)
    if lv is None:
        emit("search_panel_not_open")
        return None
    emit("slider_observed", lv=lv)
    if lv == TARGET_LV:
        return lv
    if dry_run:
        return lv

    # Step toward the target. Cap at 6 nudges so we don't spin forever.
    for _ in range(6):
        if lv < TARGET_LV:
            tap(*TAP_SLIDER_PLUS)
        elif lv > TARGET_LV:
            tap(*TAP_SLIDER_MINUS)
        else:
            break
        time.sleep(1)
        bgr = snap(tmp)
        if bgr is None:
            return None
        new_lv = read_search_panel_lv(bgr)
        if new_lv is None:
            return None
        if new_lv == lv:
            # Nudge didn't register — bail; caller can retry.
            emit("slider_stuck", at=lv)
            return lv
        lv = new_lv
        emit("slider_nudged", lv=lv)
        if lv == TARGET_LV:
            return lv
    return lv


def send_one_march(tmp: Path, dry_run: bool) -> bool:
    """Run the four-tap send sequence once. Returns True if we believe
    a march left (confirmed by re-snapping and seeing fewer-than-5
    rows? for now we only verify the dialog dismissed)."""
    if dry_run:
        emit("would_send_march")
        return True
    # Guard: (540,2280) is BAG when the search panel is closed.
    # Re-verify the panel is still open right before tapping SEARCH.
    bgr = snap(tmp)
    if bgr is not None and read_search_panel_lv(bgr) is None:
        emit("search_panel_closed_before_search_tap", action="reopening")
        tap(*TAP_SEARCH_MAGNIFIER)
        time.sleep(2)
    tap(*TAP_SEARCH_BUTTON)
    time.sleep(3)
    tap(*TAP_GATHER_MARKER)
    time.sleep(3)
    tap(*TAP_DEPART_CTA)   # Select All
    time.sleep(2)
    tap(*TAP_DEPART_CTA)   # Depart
    time.sleep(4)
    return True


def open_search_panel(tmp: Path, dry_run: bool) -> bool:
    """Open the search panel if not already up. The magnifier is a
    TOGGLE — tapping it when the panel is already visible CLOSES it,
    so we snap first and only tap if needed."""
    if dry_run:
        return True
    bgr = snap(tmp)
    if bgr is not None and read_search_panel_lv(bgr) is not None:
        return True   # already open, leave it
    tap(*TAP_SEARCH_MAGNIFIER)
    time.sleep(3)
    bgr = snap(tmp)
    if bgr is None:
        return False
    return read_search_panel_lv(bgr) is not None


def ensure_furnace_tab(tmp: Path, dry_run: bool) -> bool:
    """If the Furnace tab isn't selected (e.g. post-app-restart defaults
    to Monster Lv40), swipe the tab row left and tap Furnace at its
    post-swipe position. Returns True if Furnace is selected on exit."""
    bgr = snap(tmp)
    if bgr is None:
        return False
    if is_furnace_tab_active(bgr):
        return True
    emit("ensuring_furnace_tab", note="not on Furnace; swiping tab row")
    if dry_run:
        return True
    adb("input", "swipe", *[str(v) for v in SWIPE_TABS_LEFT])
    time.sleep(2)
    tap(*TAP_FURNACE_TAB)
    time.sleep(3)
    bgr = snap(tmp)
    return bgr is not None and is_furnace_tab_active(bgr)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--shot-dir", type=Path, default=Path.home() / "snaps")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--dry-run", action="store_true",
                   help="Read state and print plan; no taps")
    p.add_argument("--max-sends", type=int, default=5,
                   help="Cap on marches to dispatch this cycle (default 5)")
    args = p.parse_args()
    args.shot_dir.mkdir(parents=True, exist_ok=True)
    tmp = args.shot_dir / "iron_check.png"

    # Step 1: ensure world view.
    if not ensure_world_view(tmp, args.dry_run):
        emit("abandon", reason="not_on_world_view")
        return 2

    # Step 2: count free slots.
    bgr = snap(tmp)
    if bgr is None:
        emit("snap_failed", phase="troop_count")
        return 3
    info = read_troop_count(bgr)
    emit("troop_count", n_active=info.n_active, n_total=info.n_total)
    if info.n_active is None:
        emit("abandon", reason="cant_read_troop_panel")
        return 2
    free = info.n_total - info.n_active
    if free <= 0:
        emit("no_free_slots", note="all 5 marches out — recheck on shortest timer")
        return 1

    sends_planned = min(free, args.max_sends)
    emit("plan", free_slots=free, sends_planned=sends_planned)

    # Step 3: open search panel, ensure Furnace tab, verify slider on Lv5.
    if not open_search_panel(tmp, args.dry_run):
        emit("abandon", reason="search_panel_didnt_open")
        return 2

    if not ensure_furnace_tab(tmp, args.dry_run):
        emit("abandon", reason="couldnt_select_furnace_tab")
        return 2

    lv = adjust_slider_to_target(tmp, args.dry_run)
    if lv != TARGET_LV and not args.dry_run:
        emit("abandon", reason="couldnt_reach_target_lv", final_lv=lv)
        return 2

    # Step 4: send marches.
    sends_done = 0
    for i in range(sends_planned):
        emit("sending_march", n=i + 1, of=sends_planned)
        if send_one_march(tmp, args.dry_run):
            sends_done += 1
            # After Depart, the panel may close itself. Re-open before
            # the next SEARCH to avoid the (540, 2280) → BAG mistap.
            if i + 1 < sends_planned and not args.dry_run:
                if not open_search_panel(tmp, args.dry_run):
                    emit("partial", note="search panel didn't reopen mid-cycle")
                    break
        else:
            emit("send_failed", n=i + 1)
            break

    emit("done", sends_done=sends_done, sends_planned=sends_planned)
    return 0 if sends_done > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
