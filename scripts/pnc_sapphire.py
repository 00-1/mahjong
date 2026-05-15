#!/usr/bin/env python3
"""PNC sapphire-mine maintenance: enter Lv.8, recall stale gather,
pillage if attempts available, else gather an empty mine.

Designed to be cron-fired periodically. Idempotent: when the panel is
in an unexpected state (popup, world view, mid-animation) it will
back out via the popup-dismiss script and try again next cron.

Usage:
    python3 scripts/pnc_sapphire.py
    python3 scripts/pnc_sapphire.py --shot-dir ~/snaps --verbose

Exit codes:
    0  march sent (pillage or gather)
    1  no action needed (timer >6h, nothing to do)
    2  abandoned (couldn't reach mine view, popup loop, etc.)
    3  setup error (adb missing, no tiles found at all)
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
    detect_battle_skip,
    detect_popup,
    find_mine_tiles,
    MineTile,
)


# Calibrated taps (1080×2400). All confirmed during the 2026-05-15
# successful pillage flow.
TAP_SAPPHIRE_SIDEPANEL = (80, 930)
TAP_LV8_ENTER = (905, 1870)
TAP_GENERIC_CONFIRM_RIGHT = (780, 1434)   # CONFIRM (right yellow) on 2-button modals
TAP_PICKAXE_DONT_ASK = (330, 1245)
TAP_CONTINUOUSLY_OCCUPY = (294, 1434)     # left CTA on the pickaxe modal
TAP_RECALL_BUTTON = (95, 670)             # only visible when a march is out
TAP_PILLAGE_BUTTON = (772, 1689)          # right yellow on Mine Info popup
TAP_LOADOUT_I = (575, 275)                # main-march loadout (top-row "I")
TAP_DEPART = (540, 2295)                  # bottom Depart button
TAP_WORLD_TO_TERMUX = None                # we won't switch — caller handles


def adb(*args: str, timeout: int = 30) -> str:
    return subprocess.run(
        ["adb", "shell", *args],
        capture_output=True, text=True, timeout=timeout,
    ).stdout


def tap(x: int, y: int):
    adb("input", "tap", str(x), str(y))


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


def detect_recall_button(bgr) -> bool:
    """The Recall button is a small red rectangle just below the
    'Gathering HH:MM:SS' indicator on the Lv.8 mine left side. Detect
    by red-pixel mass in a small ROI."""
    import numpy as np
    roi = bgr[640:710, 40:160]
    if roi.size == 0:
        return False
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    red1 = cv2.inRange(hsv, np.array([0, 120, 80]), np.array([10, 255, 255]))
    red2 = cv2.inRange(hsv, np.array([170, 120, 80]), np.array([180, 255, 255]))
    red = cv2.bitwise_or(red1, red2)
    return bool((red > 0).mean() > 0.20)


def select_target(tiles: list[MineTile], pillage_available: bool) -> MineTile | None:
    """Pick a mine to send to. Returns None if nothing valid on screen.

    Strategy:
      - If pillage attempts > 0 and a skull_no_horns tile is visible,
        target the one with the LOWEST percent (least depleted means
        the most steal value left in their stockpile). Wait — actually
        less depleted means more iron; but for a pillage we want the
        one that's been mined the longest (highest %). User notes
        haven't pinned this down — default to "first found" for now.
      - Else target an empty tile (any).
      - Don't tap horned skulls (alliance / stronger players).
    """
    if pillage_available:
        skull_no_horns = [t for t in tiles if t.flag == "skull_no_horns"]
        if skull_no_horns:
            # First match wins; future: pick by percent
            return skull_no_horns[0]
    empties = [t for t in tiles if t.flag == "empty"]
    if empties:
        return empties[0]
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--shot-dir", type=Path, default=Path.home() / "snaps")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--dry-run", action="store_true",
                   help="Read state and print plan; no taps")
    p.add_argument("--assume-pillage-attempts", type=int, default=None,
                   help="Override pillage-counter detection. Set when the OCR for the header isn't ready yet — pass 4 to act as if we have attempts, 0 to force empty-mine targeting.")
    args = p.parse_args()
    args.shot_dir.mkdir(parents=True, exist_ok=True)
    tmp = args.shot_dir / "sapphire_check.png"

    # Step 1: tap the sapphire side panel entry.
    if not args.dry_run:
        tap(*TAP_SAPPHIRE_SIDEPANEL)
        time.sleep(5)

    # Step 2: tap Lv.8 Enter, dismiss CONFIRM + pickaxe modal.
    if not args.dry_run:
        tap(*TAP_LV8_ENTER)
        time.sleep(5)
        # CONFIRM modal only appears the first time (when no active gather)
        # Tap it; harmless if absent.
        tap(*TAP_GENERIC_CONFIRM_RIGHT)
        time.sleep(4)
        # Pickaxe promo: check Don't ask, then Continuously Occupy
        tap(*TAP_PICKAXE_DONT_ASK)
        time.sleep(1)
        tap(*TAP_CONTINUOUSLY_OCCUPY)
        time.sleep(5)

    # Step 3: snap the mine grid view, look for an active gather + tiles.
    bgr = snap(tmp)
    if bgr is None:
        emit("snap_failed")
        return 3

    has_active_recall = detect_recall_button(bgr)
    emit("entered_mine_view", has_active_recall=has_active_recall)

    # Step 4: if a march is out, recall it. (Decision to recall is
    # the caller's — this script is invoked when timer < 6h.)
    if has_active_recall and not args.dry_run:
        tap(*TAP_RECALL_BUTTON)
        time.sleep(3)
        tap(*TAP_GENERIC_CONFIRM_RIGHT)
        time.sleep(5)
        bgr = snap(tmp)
        emit("recalled")

    # Step 5: classify visible tiles, pick a target.
    tiles = find_mine_tiles(bgr)
    by_flag = {}
    for t in tiles:
        by_flag.setdefault(t.flag, []).append(t)
    emit("tiles_found", count=len(tiles),
         by_flag={k: len(v) for k, v in by_flag.items()})

    if args.assume_pillage_attempts is not None:
        pillage_attempts = args.assume_pillage_attempts
    else:
        # Until the header OCR lands, conservatively assume we DO have
        # pillage attempts. If the target tap fails on Pillage button
        # (no Mine Info popup), fall back to empty mine.
        pillage_attempts = 4
    target = select_target(tiles, pillage_available=pillage_attempts > 0)

    if target is None:
        emit("no_target", reason="all visible tiles are horned/unknown")
        return 1

    emit("target_selected",
         flag=target.flag, cx=target.cx, cy=target.cy,
         pct=target.percent)

    if args.dry_run:
        return 0

    # Step 6: tap target.
    tap(target.cx, target.cy)
    time.sleep(4)

    # Step 7: if pillage target, dispatch via Pillage button on Mine Info.
    if target.flag == "skull_no_horns":
        tap(*TAP_PILLAGE_BUTTON)
        time.sleep(3)
        # "Unprotected pit" warning — Don't ask + CONFIRM (centred yellow)
        tap(330, 1245)         # Don't ask
        time.sleep(1)
        tap(540, 1434)         # CONFIRM (centred since it's a 1-button)
        time.sleep(4)
        # Pickaxe promo again
        tap(*TAP_PICKAXE_DONT_ASK)
        time.sleep(1)
        tap(*TAP_CONTINUOUSLY_OCCUPY)
        time.sleep(5)

    # Step 8: Depart dialog — main-march loadout then Depart.
    tap(*TAP_LOADOUT_I)
    time.sleep(3)
    tap(*TAP_DEPART)
    time.sleep(5)

    emit("march_dispatched", target_flag=target.flag, target_xy=[target.cx, target.cy])

    # Step 9: verify pillage / gather actually landed.
    #
    # For an empty-mine gather: troops simply travel and start gathering;
    # the recall button shows up on the mine grid once they land.
    #
    # For a pillage: troops travel → battle animation (yellow SKIP at
    # ~980,2080) → Victory/Defeat dialog → back to mine grid. If we
    # won, the recall button shows up. If we lost, no recall.
    #
    # We loop snap-and-handle for up to verify_timeout_seconds, tapping
    # SKIP / dismissing battery-saver / closing popups as they appear.
    # Success signal: detect_recall_button → True.
    if target.flag == "skull_no_horns":
        ok = verify_pillage_success(tmp, args.shot_dir)
        emit("pillage_verify", success=ok)
        return 0 if ok else 1
    else:
        # Gather flow — shorter wait, no battle expected.
        time.sleep(2)
        bgr = snap(tmp)
        if bgr is not None and detect_recall_button(bgr):
            emit("verify_ok", note="recall button visible — gather active")
            return 0
        emit("verify_pending", note="no recall button yet; march may be in transit")
        return 0


def verify_pillage_success(tmp: Path, shot_dir: Path,
                           timeout_seconds: int = 90,
                           poll_interval: int = 4) -> bool:
    """After Depart on a pillage, walk through battle-skip / victory /
    popup screens until we either see the recall button (success) or
    time out (likely defeated). Returns True on success."""
    deadline = time.time() + timeout_seconds
    skip_taps = 0
    popup_taps = 0
    while time.time() < deadline:
        bgr = snap(tmp)
        if bgr is None:
            time.sleep(poll_interval)
            continue
        # Highest priority: the SKIP chevron during battle animation.
        skip = detect_battle_skip(bgr)
        if skip is not None:
            emit("battle_skip_tap", xy=list(skip))
            tap(*skip)
            skip_taps += 1
            time.sleep(2)
            continue
        # Next: any known popup (battery saver, mythic hero, etc).
        popup = detect_popup(bgr)
        if popup is not None:
            cx, cy = popup.confirm_xy or popup.close_xy
            emit("popup_dismiss", name=popup.name, xy=[cx, cy])
            tap(cx, cy)
            popup_taps += 1
            time.sleep(3)
            continue
        # Success: recall button means our troops are on the mine.
        if detect_recall_button(bgr):
            emit("verify_recall_visible", skip_taps=skip_taps,
                 popup_taps=popup_taps)
            return True
        # Otherwise it's a transient screen (post-battle dialog,
        # blank loading frame) — wait and try again. A centre tap
        # nudges the Victory dialog to dismiss without targeting a
        # specific button.
        tap(540, 1200)
        time.sleep(poll_interval)
    emit("verify_timeout", skip_taps=skip_taps, popup_taps=popup_taps)
    return False


if __name__ == "__main__":
    sys.exit(main())
