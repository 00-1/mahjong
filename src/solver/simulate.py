"""State simulation for lookahead search.

Given a BoardState and a tap, produce the post-tap state. Used by the
lookahead solver to evaluate move sequences without actually playing.

Deterministic mode: when a tile is tapped, the position becomes empty
(unless we have an occult prediction for what's underneath).

Expectimax mode (with occult predictions): the underlying tile is
sampled probabilistically based on the prediction's confidence.

Triplet auto-clear is modeled: when 3 same-tile slots accumulate in
the tray, all 3 are removed.

Tray full (7) without a triplet → terminal state with status=lost.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from src.model.state import BoardState, MainCell, QueueCell, TraySlot


@dataclass
class SimResult:
    new_state: BoardState
    triplet_cleared: str | None  # tile_id of the cleared triplet, or None
    is_terminal: bool
    terminal_status: str | None  # "won" | "lost" | None


def _state_main_remove(state: BoardState, row: int, col: int) -> MainCell | None:
    """Remove and return the main_board cell at (row, col), or None."""
    for i, c in enumerate(state.main_board):
        if c.row == row and c.col == col:
            return state.main_board.pop(i)
    return None


def _state_queue_remove(state: BoardState, queue_id: str) -> QueueCell | None:
    for i, q in enumerate(state.queues):
        if q.queue_id == queue_id:
            return state.queues.pop(i)
    return None


def _add_to_tray(state: BoardState, tile_id: str) -> tuple[BoardState, str | None]:
    """Add a tile to the tray. If 3 of the same tile are now in tray,
    remove all 3 (auto-clear) and return the cleared tile_id.

    Returns (new_state, cleared_tile_id_or_None)."""
    # Find first empty slot
    occupied = [t for t in state.tray if t.tile_id is not None]
    if len(occupied) >= 7:
        # Tray full — return state unchanged, caller treats as terminal-loss
        return state, None
    # Add the tile
    next_slot = len(occupied)
    state.tray.append(TraySlot(slot=next_slot, bbox=(0, 0, 0, 0), tile_id=tile_id))

    # Check for auto-clear: 3 of same tile_id in tray
    counts = {}
    for t in state.tray:
        if t.tile_id:
            counts[t.tile_id] = counts.get(t.tile_id, 0) + 1
    for tid, n in counts.items():
        if n >= 3:
            # Remove all 3 (well, exactly 3) of this tile_id
            removed = 0
            new_tray = []
            for t in state.tray:
                if t.tile_id == tid and removed < 3:
                    removed += 1
                    continue
                new_tray.append(t)
            # Re-slot
            state.tray = [TraySlot(slot=i, bbox=t.bbox, tile_id=t.tile_id) for i, t in enumerate(new_tray)]
            return state, tid
    return state, None


def simulate_tap(
    state: BoardState,
    location: str,
    occult_predictions: dict | None = None,
) -> SimResult:
    """Simulate tapping a tile at the given logical location.

    location: "(row,col)" | "queue:<id>" | "tray:<slot>"
    occult_predictions: optional dict {(zone, ...key): predicted_tile_id}
      used to fill in what's underneath a tapped tile. If absent, the
      position becomes empty after the tap.
    """
    new = copy.deepcopy(state)

    # Find the tile being tapped
    tapped_tile_id: str | None = None
    revealed_tile_id: str | None = None  # what comes up after the tap

    if location.startswith("("):
        r, c = [int(x) for x in location.strip("()").split(",")]
        cell = _state_main_remove(new, r, c)
        if cell is None or cell.tile_id is None:
            return SimResult(new, None, True, "abandoned")  # invalid tap
        tapped_tile_id = cell.tile_id
        # Reveal logic. We only reveal the SECOND tile at this anchor
        # (i.e. the prediction for "what comes up after the FIRST tap" —
        # cell.stack_depth was 1). For deeper taps (stack_depth >= 2)
        # most anchors don't have a prior, so we leave the position empty.
        # This avoids the bug where the same anchor would keep yielding
        # the predicted tile on every successive tap.
        current_depth = cell.stack_depth or 1
        if occult_predictions and current_depth == 1:
            key = ("main_board", r, c)
            if key in occult_predictions:
                revealed_tile_id = occult_predictions[key]
        if revealed_tile_id is not None:
            new.main_board.append(MainCell(
                row=r, col=c, bbox=cell.bbox,
                tile_id=revealed_tile_id, stack_depth=current_depth + 1,
            ))

    elif location.startswith("queue:"):
        qid = location.split(":", 1)[1]
        q = _state_queue_remove(new, qid)
        if q is None or q.tile_id is None:
            return SimResult(new, None, True, "abandoned")
        tapped_tile_id = q.tile_id
        # Queue: reveal next tile in strip if known. For simulation
        # purposes we treat the queue as "advances to unknown" unless
        # an occult prediction exists for that queue_id.
        if occult_predictions:
            key = ("queue", qid)
            if key in occult_predictions:
                revealed_tile_id = occult_predictions[key]
        if revealed_tile_id is not None:
            new.queues.append(QueueCell(
                queue_id=qid, bbox=q.bbox, tile_id=revealed_tile_id,
            ))

    else:
        return SimResult(new, None, True, "abandoned")

    if tapped_tile_id is None:
        return SimResult(new, None, True, "abandoned")

    # Add the tapped tile to tray, possibly auto-clearing a triplet
    occupied = sum(1 for t in new.tray if t.tile_id is not None)
    if occupied >= 7:
        # Can't tap when tray is full — terminal loss
        return SimResult(new, None, True, "lost")

    new, cleared = _add_to_tray(new, tapped_tile_id)

    # Win check: nothing left on board AND tray empty
    main_remaining = sum(1 for c in new.main_board if c.tile_id is not None)
    queue_remaining = sum(1 for q in new.queues if q.tile_id is not None)
    tray_remaining = sum(1 for t in new.tray if t.tile_id is not None)
    if main_remaining == 0 and queue_remaining == 0 and tray_remaining == 0:
        return SimResult(new, cleared, True, "won")
    # Loss check: tray full AND no triplet possible from tray alone
    if tray_remaining >= 7:
        # Game blocks further taps, level lost
        return SimResult(new, cleared, True, "lost")

    return SimResult(new, cleared, False, None)


def candidate_locations(state: BoardState) -> list[str]:
    """All currently-tappable locations: top-of-stack main_board cells
    and queue heads."""
    locations = []
    for c in state.main_board:
        if c.tile_id is not None:
            locations.append(f"({c.row},{c.col})")
    for q in state.queues:
        if q.tile_id is not None:
            locations.append(f"queue:{q.queue_id}")
    return locations


def tray_filled(state: BoardState) -> int:
    return sum(1 for t in state.tray if t.tile_id is not None)


def tray_count(state: BoardState, tile_id: str) -> int:
    return sum(1 for t in state.tray if t.tile_id == tile_id)
