"""Diff two BoardStates of the same level and reconstruct the inferred taps.

We can identify the SET of tile-positions that were tapped between two states,
but not the exact order within a triplet (multiple orderings produce the same
end state). What we emit:

- removed_main: positions (row, col) in state_a that have no detection in state_b
- advanced_main: positions whose tile_id changed between states (top tile tapped,
  lower tile now visible)
- advanced_queues: queue heads whose tile_id changed (queue tapped, advanced)

We then group these tap events into triplets by tile identity. If 3 tapped
events all show the same tile_id, they form a triplet.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from src.model.state import BoardState, MainCell, QueueCell


@dataclass
class TapEvent:
    tile_id: str | None  # what was tapped (the *top* tile pre-tap)
    location: str  # "(row,col)" for main_board, "queue:<id>" for queue
    kind: str  # "removed_emptied" | "advanced_main" | "advanced_queue"
    revealed: str | None = None  # tile_id of the lower tile now exposed (None if emptied or unknown)


def _state_from_dict(d: dict) -> BoardState:
    return BoardState(
        level=d["level"],
        image=d["image"],
        image_size=tuple(d["image_size"]),
        main_board=[MainCell(**c) for c in d["main_board"]],
        queues=[QueueCell(**q) for q in d["queues"]],
        tray=d.get("tray", []),
        boost_counts=d.get("boost_counts", {}),
    )


def load_state(path: Path) -> BoardState:
    return _state_from_dict(json.loads(path.read_text()))


def diff_states(a: BoardState, b: BoardState) -> list[TapEvent]:
    """Return the inferred TapEvents that transform state a into state b.
    Assumes a and b are from the same level (same template/anchors)."""
    events: list[TapEvent] = []

    a_main = {(c.row, c.col): c for c in a.main_board}
    b_main = {(c.row, c.col): c for c in b.main_board}

    for pos, cell_a in a_main.items():
        cell_b = b_main.get(pos)
        if cell_b is None:
            events.append(TapEvent(
                tile_id=cell_a.tile_id,
                location=f"({pos[0]},{pos[1]})",
                kind="removed_emptied",
            ))
        elif cell_b.tile_id != cell_a.tile_id:
            events.append(TapEvent(
                tile_id=cell_a.tile_id,
                location=f"({pos[0]},{pos[1]})",
                kind="advanced_main",
                revealed=cell_b.tile_id,
            ))

    a_q = {q.queue_id: q for q in a.queues}
    b_q = {q.queue_id: q for q in b.queues}
    for qid, q_a in a_q.items():
        q_b = b_q.get(qid)
        if q_b is None or q_b.tile_id != q_a.tile_id:
            events.append(TapEvent(
                tile_id=q_a.tile_id,
                location=f"queue:{qid}",
                kind="advanced_queue",
                revealed=q_b.tile_id if q_b else None,
            ))

    return events


@dataclass
class DiffSummary:
    events: list[TapEvent]
    triplets: list[tuple[str, list[TapEvent]]]  # (tile_id, [events])
    orphans: list[TapEvent]  # events not part of a complete triplet


def summarize_diff(events: list[TapEvent]) -> DiffSummary:
    by_tile: dict[str, list[TapEvent]] = defaultdict(list)
    for e in events:
        if e.tile_id:
            by_tile[e.tile_id].append(e)

    triplets: list[tuple[str, list[TapEvent]]] = []
    orphans: list[TapEvent] = []
    for tile_id, evs in by_tile.items():
        # consume in groups of 3
        i = 0
        while i + 3 <= len(evs):
            triplets.append((tile_id, evs[i:i + 3]))
            i += 3
        if i < len(evs):
            orphans.extend(evs[i:])
    return DiffSummary(events=events, triplets=triplets, orphans=orphans)


def label_for(state: BoardState, tile_id_to_label: dict[str, str], tile_id: str | None) -> str:
    if not tile_id:
        return "?"
    return tile_id_to_label.get(tile_id, tile_id)
