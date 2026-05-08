"""Board state schema and JSON serialization.

A BoardState is the structured snapshot of one screenshot:
- main_board: top-of-stack tiles at integer (row, col) positions
- queues: head tiles of each side-feeding queue
- tray: tiles currently in the bottom 7-slot tray (length 0..7)
- meta: level number, source screenshot path, capture timestamp if known

The schema is intentionally permissive about unknowns: tile_id can be None
(detected but unrecognized), stack_depth can be None (not yet inferred).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class MainCell:
    row: int
    col: int
    bbox: tuple[int, int, int, int]  # x, y, w, h
    tile_id: str | None = None
    stack_depth: int | None = None  # number of tiles below this one (None = unknown)


@dataclass
class QueueCell:
    queue_id: str  # e.g., "left_upper", "left_lower", "right_upper", "right_lower"
    bbox: tuple[int, int, int, int]
    tile_id: str | None = None
    queue_remaining: int | None = None  # estimated tiles still queued (incl. visible head)


@dataclass
class BoardState:
    level: int | None
    image: str  # relative path
    image_size: tuple[int, int]  # w, h
    main_board: list[MainCell] = field(default_factory=list)
    queues: list[QueueCell] = field(default_factory=list)
    tray: list[str | None] = field(default_factory=list)  # tile_ids; None = empty slot
    boost_counts: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())
