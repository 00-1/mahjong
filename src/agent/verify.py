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

Mismatch detection (recorded but doesn't fail verification on its own):
- target_actual_tile_id vs expected_tile_id: did vision classify the tile
  we tapped correctly? If it disagrees, the strategy was operating on
  a wrong model of what's on the board.
- tray_delta_tile_id: which tile ACTUALLY went to the tray. If it
  doesn't match the expected_tile_id, our tap landed on the wrong
  thing OR vision misread the target.
- unexpected_changes: other positions whose tile changed without
  being the intended tap target. Indicates an off-target tap or a
  cascade clear.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TapVerification:
    success: bool
    reason: str  # "ok" | "no_change" | "wrong_target" | "unexpected" | "expected_no_change" | "tile_mismatch"
    notes: str = ""
    # Intended-vs-actual fields (filled where possible). None means the
    # caller didn't provide enough info, or the location wasn't a main
    # board / queue cell.
    expected_tile_id: str | None = None
    target_actual_tile_id: str | None = None  # what was there pre-tap
    tray_added_tile_ids: list[str] = field(default_factory=list)
    tray_removed_tile_ids: list[str] = field(default_factory=list)
    unexpected_position_changes: list[dict] = field(default_factory=list)
    intended_actual_match: bool | None = None  # did target's tile == expected


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


def _diff_tray(before: dict, after: dict) -> tuple[list[str], list[str]]:
    """Tile-id multiset diff of tray contents. (added, removed)."""
    from collections import Counter
    before_c = Counter(_tray_tiles(before))
    after_c = Counter(_tray_tiles(after))
    added: list[str] = []
    removed: list[str] = []
    all_keys = set(before_c) | set(after_c)
    for k in all_keys:
        delta = after_c[k] - before_c[k]
        if delta > 0:
            added.extend([k] * delta)
        elif delta < 0:
            removed.extend([k] * (-delta))
    return added, removed


def _diff_main_positions(before: dict, after: dict) -> list[dict]:
    """All main-board (row, col) positions whose tile_id changed.
    Returns list of dicts with {row, col, before, after}."""
    before_map = {(c["row"], c["col"]): c.get("tile_id") for c in before.get("main_board", []) if c.get("tile_id")}
    after_map = {(c["row"], c["col"]): c.get("tile_id") for c in after.get("main_board", [])}
    # also pick up positions that disappeared (no entry post-tap)
    all_pos = set(before_map) | set(after_map)
    changes = []
    for r, c in all_pos:
        b = before_map.get((r, c))
        a = after_map.get((r, c))
        if b != a:
            changes.append({"row": r, "col": c, "before": b, "after": a})
    return changes


def verify_tap(
    before: dict,
    after: dict,
    expected_location: str,
    expected_tile_id: str,
) -> TapVerification:
    """Did the tap on `expected_location` (whose tile was `expected_tile_id`)
    actually take effect?

    expected_location: "(r,c)" | "queue:<id>" | "tray:<slot>"

    Records intended-vs-actual mismatches even on success — see
    TapVerification field comments. The strategy can then notice
    when vision misclassified the target tile (so its mental model
    is wrong even though the tap "worked")."""
    tray_added, tray_removed = _diff_tray(before, after)
    pos_changes = _diff_main_positions(before, after)

    if expected_location.startswith("("):
        r, c = [int(x) for x in expected_location.strip("()").split(",")]
        before_tile = _state_main_at(before, r, c)
        after_tile = _state_main_at(after, r, c)
        # Did vision misread what's at the target position?
        intended_actual_match = (
            None if (expected_tile_id is None or before_tile is None)
            else (before_tile == expected_tile_id)
        )
        # Other positions that changed unexpectedly (i.e. not the tapped one)
        unexpected = [ch for ch in pos_changes if (ch["row"], ch["col"]) != (r, c)]
        if before_tile == after_tile:
            return TapVerification(
                success=False, reason="no_change",
                notes=f"main_board ({r},{c}) still shows {before_tile}",
                expected_tile_id=expected_tile_id,
                target_actual_tile_id=before_tile,
                intended_actual_match=intended_actual_match,
                tray_added_tile_ids=tray_added,
                tray_removed_tile_ids=tray_removed,
                unexpected_position_changes=unexpected,
            )
        return TapVerification(
            success=True, reason="ok",
            notes=f"main_board ({r},{c}) {before_tile} -> {after_tile}",
            expected_tile_id=expected_tile_id,
            target_actual_tile_id=before_tile,
            intended_actual_match=intended_actual_match,
            tray_added_tile_ids=tray_added,
            tray_removed_tile_ids=tray_removed,
            unexpected_position_changes=unexpected,
        )

    if expected_location.startswith("queue:"):
        qid = expected_location.split(":", 1)[1]
        before_tile = _state_queue_at(before, qid)
        after_tile = _state_queue_at(after, qid)
        intended_actual_match = (
            None if (expected_tile_id is None or before_tile is None)
            else (before_tile == expected_tile_id)
        )
        if before_tile == after_tile:
            return TapVerification(
                success=False, reason="no_change",
                notes=f"queue {qid} still shows {before_tile}",
                expected_tile_id=expected_tile_id,
                target_actual_tile_id=before_tile,
                intended_actual_match=intended_actual_match,
                tray_added_tile_ids=tray_added,
                tray_removed_tile_ids=tray_removed,
                unexpected_position_changes=pos_changes,
            )
        return TapVerification(
            success=True, reason="ok",
            notes=f"queue {qid} {before_tile} -> {after_tile}",
            expected_tile_id=expected_tile_id,
            target_actual_tile_id=before_tile,
            intended_actual_match=intended_actual_match,
            tray_added_tile_ids=tray_added,
            tray_removed_tile_ids=tray_removed,
            unexpected_position_changes=pos_changes,
        )

    return TapVerification(success=False, reason="unexpected",
                           notes=f"unknown location format: {expected_location}",
                           expected_tile_id=expected_tile_id)


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
