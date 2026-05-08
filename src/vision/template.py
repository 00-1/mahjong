"""Per-level board templates.

A template fixes the canonical (cx, cy) anchor for every grid position in a
level. We build it once from a clean initial state, then snap subsequent
extractions to those anchors.

Zones:
- main_board: anchors with (row, col). Lower tiles in stacks render at the
  same anchor with one of 9 candidate offsets (origin + 4 diagonal half-tile
  + 4 cardinal half-tile). The offset itself reveals depth >= 2.
- queue: each side has an upper and lower strip; queue heads can appear
  anywhere along the strip's cx range. Match by (side, tier) from cy + cx
  half-plane, not by exact cx.
- tray: 7 slots evenly spaced at the bottom row. Match by slot cx.

Storage: data/levels/<level>/template.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from src.vision.detect import Detection
from src.vision.grid import assign_grid


# Half-tile offsets for depth >= 2 tiles. The exposed lower tile renders at
# one of these positions relative to the original anchor. (0,0) means the
# tile is at depth 1 (no offset).
DEPTH_OFFSETS = [
    (0, 0),      # depth 1
    (76, 81),    # down-right
    (-76, -81),  # up-left
    (76, -81),   # up-right
    (-76, 81),   # down-left
    (76, 0),     # pure right
    (-76, 0),    # pure left
    (0, 81),     # pure down
    (0, -81),    # pure up
]


@dataclass
class Anchor:
    zone: str  # "main_board" | "queue" | "tray"
    row: int  # main_board row; -1 otherwise
    col: int  # main_board col / tray slot index; -1 otherwise
    queue_id: str | None  # "<side>_<tier>" for queue, None otherwise
    cx: int
    cy: int


@dataclass
class SnapResult:
    detection_idx: int
    anchor: Anchor
    distance: float
    offset_x: int
    offset_y: int


def _queue_id_for(cx: int, cy: int, image_w: int, queue_cy_values: list[int]) -> str:
    side = "left" if cx < image_w // 2 else "right"
    if not queue_cy_values:
        return f"{side}_upper"
    upper_cy = min(queue_cy_values)
    lower_cy = max(queue_cy_values)
    if upper_cy == lower_cy:
        return f"{side}_upper"
    tier = "upper" if abs(cy - upper_cy) < abs(cy - lower_cy) else "lower"
    return f"{side}_{tier}"


def build_template(detections: list[Detection], image_w: int) -> list[Anchor]:
    """Build a level template from a clean, full initial state."""
    grid = assign_grid(detections)
    main_rows = sorted({a.row for a in grid if a.zone == "main_board"})
    main_cols = sorted({a.col for a in grid if a.zone == "main_board"})
    main_row_map = {r: i for i, r in enumerate(main_rows)}
    main_col_map = {c: i for i, c in enumerate(main_cols)}
    queue_cy_values = [
        detections[a.detection_idx].cy for a in grid if a.zone == "queue"
    ]

    anchors: list[Anchor] = []
    for a in grid:
        d = detections[a.detection_idx]
        if a.zone == "main_board":
            anchors.append(Anchor(
                zone="main_board",
                row=main_row_map[a.row], col=main_col_map[a.col],
                queue_id=None, cx=d.cx, cy=d.cy,
            ))
        else:
            qid = _queue_id_for(d.cx, d.cy, image_w, queue_cy_values)
            anchors.append(Anchor(
                zone="queue", row=-1, col=-1, queue_id=qid,
                cx=d.cx, cy=d.cy,
            ))

    # Add 7 tray slot anchors evenly spaced along the bottom row.
    # Tray cy is observed empirically at ~2382 in 1220x2712 images; slots at
    # cx in [155, 307, 458, 610, 761, 912, 1064].
    tray_cy = 2382
    tray_cxs = [155, 307, 458, 610, 761, 912, 1064]
    for i, cx in enumerate(tray_cxs):
        anchors.append(Anchor(
            zone="tray", row=-1, col=i, queue_id=None,
            cx=cx, cy=tray_cy,
        ))
    return anchors


def save_template(anchors: list[Anchor], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"anchors": [asdict(a) for a in anchors]}, indent=2,
    ))


def load_template(path: Path) -> list[Anchor] | None:
    if not path.exists():
        return None
    return [Anchor(**a) for a in json.loads(path.read_text())["anchors"]]


def snap_detections(
    detections: list[Detection],
    anchors: list[Anchor],
    image_w: int,
    *,
    main_max_distance: float = 60.0,
    tray_max_distance: float = 60.0,
    queue_cy_tolerance: float = 50.0,
) -> tuple[list[SnapResult], list[int]]:
    """Snap detections to anchors with zone-aware logic.

    main_board: try all DEPTH_OFFSETS; nearest match wins (greedy).
    tray: snap to nearest of 7 slot anchors by cx.
    queue: match by (side, tier) inferred from (cx, cy) — queue heads can
      appear anywhere along their strip's cx range, so we don't require cx
      proximity to the canonical anchor.
    """
    main_anchors = [a for a in anchors if a.zone == "main_board"]
    tray_anchors = [a for a in anchors if a.zone == "tray"]
    queue_anchors = [a for a in anchors if a.zone == "queue"]
    queue_cy_values = sorted({a.cy for a in queue_anchors})

    candidates: list[tuple[float, int, int, tuple[int, int]]] = []  # (dist, det_idx, anchor_idx, offset)
    for di, d in enumerate(detections):
        # Main board candidates with offsets
        for ai, a in enumerate(anchors):
            if a.zone == "main_board":
                for ox, oy in DEPTH_OFFSETS:
                    target_x = a.cx + ox
                    target_y = a.cy + oy
                    dist = ((d.cx - target_x) ** 2 + (d.cy - target_y) ** 2) ** 0.5
                    if dist <= main_max_distance:
                        candidates.append((dist, di, ai, (ox, oy)))
            elif a.zone == "tray":
                dist = ((d.cx - a.cx) ** 2 + (d.cy - a.cy) ** 2) ** 0.5
                if dist <= tray_max_distance:
                    candidates.append((dist, di, ai, (0, 0)))

        # Queue: match by (side, tier) for any detection whose cy is near a queue row.
        # We assign the detection to a *virtual* queue anchor for the matching
        # (side, tier) — distance is purely the cy mismatch.
        if queue_cy_values:
            best_queue_cy = min(queue_cy_values, key=lambda qcy: abs(d.cy - qcy))
            cy_dist = abs(d.cy - best_queue_cy)
            if cy_dist <= queue_cy_tolerance:
                target_qid = _queue_id_for(d.cx, d.cy, image_w, queue_cy_values)
                for ai, a in enumerate(anchors):
                    if a.zone == "queue" and a.queue_id == target_qid:
                        candidates.append((float(cy_dist), di, ai, (0, 0)))
                        break

    # Globally-optimal assignment via Hungarian. For each (detection, anchor)
    # pair we keep only the BEST candidate (smallest distance across offsets);
    # unreachable pairs get a large penalty so they're avoided.
    UNREACHABLE = 1e6
    n_dets = len(detections)
    n_anchors = len(anchors)
    cost = np.full((n_dets, n_anchors), UNREACHABLE, dtype=float)
    best_offset = {}  # (det_idx, anchor_idx) -> (ox, oy)
    for dist, di, ai, off in candidates:
        if dist < cost[di, ai]:
            cost[di, ai] = dist
            best_offset[(di, ai)] = off

    # Pad with virtual "no-match" anchors so assignment can always complete.
    # Each detection can fall back to a virtual anchor with cost slightly
    # smaller than UNREACHABLE — that lets unmatched detections drop out
    # without forcing a bad real match.
    NO_MATCH_COST = UNREACHABLE - 1
    n_virtual = max(0, n_dets)
    if n_anchors < n_dets + n_virtual:
        pad_cols = n_dets + n_virtual - n_anchors
        cost = np.hstack([cost, np.full((n_dets, pad_cols), NO_MATCH_COST)])

    row_ind, col_ind = linear_sum_assignment(cost)
    results: list[SnapResult] = []
    matched: set[int] = set()
    for di, ai in zip(row_ind, col_ind):
        if ai >= n_anchors:
            continue
        if cost[di, ai] >= UNREACHABLE:
            continue
        d = detections[di]
        a = anchors[ai]
        ox, oy = best_offset.get((di, ai), (0, 0))
        results.append(SnapResult(
            detection_idx=di, anchor=a, distance=float(cost[di, ai]),
            offset_x=(d.cx - a.cx) if a.zone != "main_board" else ox,
            offset_y=(d.cy - a.cy) if a.zone != "main_board" else oy,
        ))
        matched.add(di)

    unmatched = [i for i in range(n_dets) if i not in matched]
    return results, unmatched
