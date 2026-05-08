"""Per-level board templates.

A template fixes the canonical (cx, cy) anchor for every grid position in a
level, plus the queue head positions. We build it once from a clean initial
state, then snap subsequent extractions of the same level to those anchors.

This solves the diagonal-offset problem: when a top tile is removed, the
exposed lower tile renders at a position offset diagonally by ~80px from
the original anchor. Snapping to nearest anchor keeps the (row, col)
assignment stable, and the offset itself becomes a free depth indicator.

Storage: data/levels/<level>/template.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from src.vision.detect import Detection
from src.vision.grid import assign_grid


@dataclass
class Anchor:
    zone: str  # "main_board" or "queue"
    row: int  # main board row (0-indexed); -1 for queue
    col: int  # main board col (0-indexed); -1 for queue
    queue_id: str | None  # e.g., "left_upper"; None for main_board
    cx: int
    cy: int


@dataclass
class SnapResult:
    detection_idx: int
    anchor: Anchor
    distance: float  # euclidean px from detection center to anchor
    offset_x: int  # detection.cx - anchor.cx
    offset_y: int  # detection.cy - anchor.cy


def _queue_id_for(cx: int, cy: int, image_w: int, queue_cy_values: list[int]) -> str:
    side = "left" if cx < image_w // 2 else "right"
    if not queue_cy_values:
        return f"{side}_upper"
    upper_cy = min(queue_cy_values)
    lower_cy = max(queue_cy_values)
    if upper_cy == lower_cy:
        tier = "upper"
    else:
        tier = "upper" if abs(cy - upper_cy) < abs(cy - lower_cy) else "lower"
    return f"{side}_{tier}"


def build_template(detections: list[Detection], image_w: int) -> list[Anchor]:
    """Build a level template from a (presumed clean, full) initial state."""
    grid_assignments = assign_grid(detections)
    main_rows = sorted({a.row for a in grid_assignments if a.zone == "main_board"})
    main_cols = sorted({a.col for a in grid_assignments if a.zone == "main_board"})
    main_row_map = {r: i for i, r in enumerate(main_rows)}
    main_col_map = {c: i for i, c in enumerate(main_cols)}
    queue_cy_values = [
        detections[a.detection_idx].cy
        for a in grid_assignments
        if a.zone == "queue"
    ]

    anchors: list[Anchor] = []
    for a in grid_assignments:
        d = detections[a.detection_idx]
        if a.zone == "main_board":
            anchors.append(Anchor(
                zone="main_board",
                row=main_row_map[a.row],
                col=main_col_map[a.col],
                queue_id=None,
                cx=d.cx,
                cy=d.cy,
            ))
        else:
            qid = _queue_id_for(d.cx, d.cy, image_w, queue_cy_values)
            anchors.append(Anchor(
                zone="queue",
                row=-1,
                col=-1,
                queue_id=qid,
                cx=d.cx,
                cy=d.cy,
            ))
    return anchors


def save_template(anchors: list[Anchor], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"anchors": [asdict(a) for a in anchors]},
        indent=2,
    ))


def load_template(path: Path) -> list[Anchor] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return [Anchor(**a) for a in data["anchors"]]


# Half-tile diagonal offsets for depth >= 2 tiles. When a top tile is removed,
# the exposed lower tile renders at one of these 4 diagonal positions relative
# to the original anchor. Magnitude is approximately tile_size / 2.
DEPTH_OFFSETS = [
    (0, 0),     # depth 1 (no offset)
    (76, 81),   # down-right
    (-76, -81), # up-left
    (76, -81),  # up-right
    (-76, 81),  # down-left
]


def snap_detections(
    detections: list[Detection],
    anchors: list[Anchor],
    max_distance: float = 60.0,
) -> tuple[list[SnapResult], list[int]]:
    """Snap each detection to the nearest (anchor, offset) candidate.

    For each anchor we try all DEPTH_OFFSETS as candidate render positions —
    e.g., a depth-2 tile shows up at anchor + (76, 81). The detection-to-
    candidate distance after correcting for offset reveals the true anchor
    even when adjacent anchors are equidistant in raw position.

    Returns (snap_results, unmatched_indices). Each anchor is matched at most
    once. Greedy by smallest distance.
    """
    candidates: list[tuple[float, int, int, tuple[int, int]]] = []
    for di, d in enumerate(detections):
        for ai, a in enumerate(anchors):
            for ox, oy in DEPTH_OFFSETS:
                # Queue anchors don't get diagonal offsets — queue heads always
                # render at their canonical position regardless of queue depth.
                if a.zone == "queue" and (ox, oy) != (0, 0):
                    continue
                target_x = a.cx + ox
                target_y = a.cy + oy
                dist = ((d.cx - target_x) ** 2 + (d.cy - target_y) ** 2) ** 0.5
                if dist <= max_distance:
                    candidates.append((dist, di, ai, (ox, oy)))
    candidates.sort()

    results: list[SnapResult] = []
    matched_dets: set[int] = set()
    used_anchors: set[int] = set()
    for dist, di, ai, (ox, oy) in candidates:
        if di in matched_dets or ai in used_anchors:
            continue
        d = detections[di]
        a = anchors[ai]
        results.append(SnapResult(
            detection_idx=di,
            anchor=a,
            distance=dist,
            offset_x=ox,
            offset_y=oy,
        ))
        matched_dets.add(di)
        used_anchors.add(ai)

    unmatched = [i for i in range(len(detections)) if i not in matched_dets]
    return results, unmatched
