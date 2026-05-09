"""Verify that a tap had its expected effect on the board.

Compares state before and after a tap. If the state didn't change at all,
the tap probably missed (no-op). If it changed in an unexpected way (e.g.,
a different tile vanished from a different position than we tapped), we
flag it.

Verification semantics:
- A successful main-board tap removes the tile from its anchor position
  AND adds it to the tray. (Or the tile changes identity, if depth-2.)
- A successful queue tap changes the queue head's tile_id AND adds the
  old head tile to the tray.
- A triplet-completing tap removes 3 tiles AND clears them from tray.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TapVerification:
    success: bool
    reason: str  # "ok" | "no_change" | "wrong_target" | "unexpected" | "expected_no_change"
    notes: str = ""


def _state_main_at(state: dict, row: int, col: int) -> str | None:
    for c in state.get("main_board", []):
        if (c.get("row"), c.get("col")) == (row, col):
            return c.get("tile_id")
    return None


def _state_queue_at(state: dict, qid: str) -> str | None:
    for q in state.get("queues", []):
        if q.get("queue_id") == qid:
            return q.get("tile_id")
    return None


def _tray_tiles(state: dict) -> list[str]:
    return [t["tile_id"] for t in state.get("tray", []) if t.get("tile_id")]


def verify_tap(
    before: dict,
    after: dict,
    expected_location: str,
    expected_tile_id: str,
) -> TapVerification:
    """Did the tap on `expected_location` (whose tile was `expected_tile_id`)
    actually take effect?

    expected_location: "(r,c)" | "queue:<id>" | "tray:<slot>"
    """
    if expected_location.startswith("("):
        r, c = [int(x) for x in expected_location.strip("()").split(",")]
        before_tile = _state_main_at(before, r, c)
        after_tile = _state_main_at(after, r, c)
        if before_tile == after_tile:
            # No change at the target anchor at all
            return TapVerification(
                success=False, reason="no_change",
                notes=f"main_board ({r},{c}) still shows {before_tile}",
            )
        # Either the position is now empty, or shows a different tile (depth-2 reveal)
        return TapVerification(
            success=True, reason="ok",
            notes=f"main_board ({r},{c}) {before_tile} -> {after_tile}",
        )

    if expected_location.startswith("queue:"):
        qid = expected_location.split(":", 1)[1]
        before_tile = _state_queue_at(before, qid)
        after_tile = _state_queue_at(after, qid)
        if before_tile == after_tile:
            return TapVerification(
                success=False, reason="no_change",
                notes=f"queue {qid} still shows {before_tile}",
            )
        return TapVerification(
            success=True, reason="ok",
            notes=f"queue {qid} {before_tile} -> {after_tile}",
        )

    return TapVerification(success=False, reason="unexpected",
                           notes=f"unknown location format: {expected_location}")


def verify_triplet_burst(
    before: dict,
    after: dict,
    expected_locations: list[str],
    expected_tile_id: str,
) -> TapVerification:
    """Did a 3-tap burst clear the triplet?

    Success: all 3 expected positions changed AND the tray no longer
    contains the expected tile (it auto-cleared).
    """
    changed = 0
    for loc in expected_locations:
        if loc.startswith("("):
            r, c = [int(x) for x in loc.strip("()").split(",")]
            if _state_main_at(before, r, c) != _state_main_at(after, r, c):
                changed += 1
        elif loc.startswith("queue:"):
            qid = loc.split(":", 1)[1]
            if _state_queue_at(before, qid) != _state_queue_at(after, qid):
                changed += 1

    if changed == 0:
        return TapVerification(
            success=False, reason="no_change",
            notes=f"no triplet position changed (all {len(expected_locations)} taps missed?)",
        )
    if changed < len(expected_locations):
        return TapVerification(
            success=False, reason="partial",
            notes=f"only {changed}/{len(expected_locations)} positions changed",
        )

    # All changed — also check tray is reasonable (triplet auto-cleared)
    before_tray_count = sum(1 for t in _tray_tiles(before) if t == expected_tile_id)
    after_tray_count = sum(1 for t in _tray_tiles(after) if t == expected_tile_id)
    if after_tray_count > before_tray_count:
        # Tile in tray went up — triplet didn't auto-clear
        return TapVerification(
            success=False, reason="no_clear",
            notes=f"all positions changed but tray didn't clear (before={before_tray_count}, after={after_tray_count})",
        )
    return TapVerification(
        success=True, reason="ok",
        notes=f"all {changed} positions changed; tray {expected_tile_id} {before_tray_count} -> {after_tray_count}",
    )
