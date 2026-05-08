"""Find triplet-completion tap suggestions from a current board state.

Given a BoardState, the solver returns a list of TripletCandidates, each
representing a set of 3 tile-faces (mix of main_board, queue head, and
tray slots) of the same tile_id that, if all 3 are tapped (in any order),
would complete a triplet — clearing all 3 tiles and emptying their tray
slots.

Constraint: the candidates only include currently *tappable* tile-faces
(top of stack). They don't try to plan multi-step sequences that involve
revealing depth-2 tiles. That's a future extension.

Strategy heuristic: prefer candidates that
- include tiles already in tray (saves taps)
- have 3 candidates with no choice (only one set of 3)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from src.model.state import BoardState


@dataclass
class TileFace:
    tile_id: str
    location: str  # "(r,c)" | "queue:<id>" | "tray:<slot>"


@dataclass
class TripletCandidate:
    tile_id: str
    faces: list[TileFace]
    # Number of taps needed to complete the triplet — equals 3 minus tray
    # faces that are already in the tray.
    taps_needed: int


def find_triplets(state: BoardState) -> list[TripletCandidate]:
    """Find all currently tappable triplets (3 visible faces of the same
    tile, where 'visible' means a top-of-stack main cell, a queue head, or
    a tray slot)."""
    by_tile: dict[str, list[TileFace]] = defaultdict(list)

    for c in state.main_board:
        if c.tile_id is None:
            continue
        by_tile[c.tile_id].append(TileFace(c.tile_id, f"({c.row},{c.col})"))
    for q in state.queues:
        if q.tile_id is None:
            continue
        by_tile[q.tile_id].append(TileFace(q.tile_id, f"queue:{q.queue_id}"))
    for t in state.tray:
        if t.tile_id is None:
            continue
        by_tile[t.tile_id].append(TileFace(t.tile_id, f"tray:{t.slot}"))

    candidates: list[TripletCandidate] = []
    for tile_id, faces in by_tile.items():
        if len(faces) < 3:
            continue
        # If exactly 3, one candidate. If more, all subsets of 3 — but to
        # keep output tractable we just emit the single "all three of the
        # first three" choice. Caller can re-rank if needed.
        if len(faces) == 3:
            tray_count = sum(1 for f in faces if f.location.startswith("tray:"))
            candidates.append(TripletCandidate(
                tile_id=tile_id,
                faces=faces,
                taps_needed=3 - tray_count,
            ))
        else:
            # >3 visible: enumerate which 3 to use. Prefer ones that include
            # tray faces (no extra tap needed) and are otherwise main_board
            # over queue (queue advancement is fine but main is direct).
            tray_faces = [f for f in faces if f.location.startswith("tray:")]
            non_tray = [f for f in faces if not f.location.startswith("tray:")]
            # Best subset = all tray faces, fill remainder from main/queue
            chosen = tray_faces[:3]
            chosen += non_tray[: 3 - len(chosen)]
            tray_count = sum(1 for f in chosen if f.location.startswith("tray:"))
            candidates.append(TripletCandidate(
                tile_id=tile_id,
                faces=chosen,
                taps_needed=3 - tray_count,
            ))

    candidates.sort(key=lambda c: (c.taps_needed, c.tile_id))
    return candidates
