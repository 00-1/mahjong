"""Reactive solver: given a board state, recommend the next tap.

Goes beyond the basic visible-triplet finder by:
1. Ranking visible triplets by cost (taps needed) and risk (tray fill)
2. Identifying "near-triplets" (2 same tiles visible, 3rd hidden) and
   suggesting taps that explore positions likely to reveal the missing 3rd
3. Tracking tray-fill risk — at high tray fill, prefer taps that complete
   triplets immediately even if other taps look better long-term
4. Avoiding moves that would fill the tray to 7 without immediate clearing

Heuristic scoring per move:
- +10 if the move completes a visible triplet
- +5 if the move makes a near-triplet (2 visible) reachable in 1 more tap
- -2 per tile newly added to tray (without clearing)
- -100 if move pushes tray to 7 without triplet

For now, "tap" is restricted to currently-visible top tiles. Future work
will include lookahead with partial-occlusion info to predict reveals.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from src.model.state import BoardState
from src.solver.triplets import TileFace, find_triplets


@dataclass
class Move:
    location: str  # "(r,c)" | "queue:<id>" | "tray:<slot>"
    tile_id: str
    score: float
    reason: str


def _tappable_faces(state: BoardState) -> list[TileFace]:
    """All currently tappable tile faces (top of stack, including queue heads)."""
    faces: list[TileFace] = []
    for c in state.main_board:
        if c.tile_id is not None:
            faces.append(TileFace(c.tile_id, f"({c.row},{c.col})"))
    for q in state.queues:
        if q.tile_id is not None:
            faces.append(TileFace(q.tile_id, f"queue:{q.queue_id}"))
    return faces


def _tray_count_per_tile(state: BoardState) -> Counter:
    counts: Counter = Counter()
    for t in state.tray:
        if t.tile_id is not None:
            counts[t.tile_id] += 1
    return counts


def _tray_filled_slots(state: BoardState) -> int:
    return sum(1 for t in state.tray if t.tile_id is not None)


def suggest_moves(state: BoardState, label_fn=None) -> list[Move]:
    """Return ranked list of next-tap suggestions.

    Higher score is better. Top suggestion at index 0.
    label_fn: optional function tile_id -> human-friendly label for messages.
    """
    if label_fn is None:
        label_fn = lambda t: t  # noqa: E731
    moves: list[Move] = []
    tray_count = _tray_count_per_tile(state)
    tray_filled = _tray_filled_slots(state)
    tray_remaining = 7 - tray_filled

    triplets = find_triplets(state)
    tappable = _tappable_faces(state)
    visible_count = Counter(f.tile_id for f in tappable) + tray_count

    triplet_tile_ids = {c.tile_id for c in triplets}

    # 1. Moves that complete visible triplets (best). Emit one Move per
    # tap location, but the reason tells the user the FULL triplet sequence.
    for c in triplets:
        non_tray_faces = [f for f in c.faces if not f.location.startswith("tray:")]
        tray_faces = [f for f in c.faces if f.location.startswith("tray:")]
        if not non_tray_faces:
            continue
        sequence_str = " + ".join(f.location for f in non_tray_faces)
        if tray_faces:
            sequence_str += f" (with {len(tray_faces)} already in tray)"
        for f in non_tray_faces:
            score = 10.0
            score -= c.taps_needed - 1  # fewer taps = better
            if c.taps_needed > tray_remaining:
                score -= 100  # can't actually complete — would fill tray
            moves.append(Move(
                location=f.location,
                tile_id=f.tile_id,
                score=score,
                reason=f"3x {label_fn(f.tile_id)}: tap {sequence_str}",
            ))

    # 2. Moves that don't help but don't hurt much (just fill tray)
    for f in tappable:
        if f.tile_id in triplet_tile_ids:
            continue  # already covered above
        already_in_tray = tray_count.get(f.tile_id, 0)
        becomes_in_tray = already_in_tray + 1
        if becomes_in_tray == 3:
            # Tapping this would complete a triplet directly from tray (would
            # have been caught by find_triplets unless it's an off-by-one case)
            score = 8.0
        elif tray_filled + 1 >= 7 and becomes_in_tray < 3:
            score = -100.0  # tap fills tray, no triplet
        else:
            score = -2.0 * (1 + tray_filled / 7)  # higher penalty when tray is fuller
            if visible_count.get(f.tile_id, 0) >= 3:
                score += 3  # at least 3 visible — eventual triplet possible
        moves.append(Move(
            location=f.location,
            tile_id=f.tile_id,
            score=score,
            reason=(
                f"adds to tray; {already_in_tray} already in tray, "
                f"{visible_count.get(f.tile_id, 0)} total visible"
            ),
        ))

    # Dedup: keep best score per (location, tile_id)
    by_key: dict[tuple, Move] = {}
    for m in moves:
        key = (m.location, m.tile_id)
        if key not in by_key or m.score > by_key[key].score:
            by_key[key] = m
    moves = sorted(by_key.values(), key=lambda m: m.score, reverse=True)
    return moves
