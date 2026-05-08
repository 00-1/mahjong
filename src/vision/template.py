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


# Half-tile offset fractions for depth >= 2 tiles. Multiplied by (tile_w, tile_h)
# at runtime to get pixel offsets — lets the same offsets apply across phone
# resolutions. Empirical magnitudes from level 5 captures were 76px in cx
# (tile_w=143 → fraction 0.531) and 81px in cy (tile_h=143 → fraction 0.566).
# (0, 0) means depth 1 (no offset).
DEPTH_OFFSET_FRACS = [
    (0.0, 0.0),       # depth 1
    (0.531, 0.566),   # down-right
    (-0.531, -0.566), # up-left
    (0.531, -0.566),  # up-right
    (-0.531, 0.566),  # down-left
    (0.531, 0.0),     # pure right
    (-0.531, 0.0),    # pure left
    (0.0, 0.566),     # pure down
    (0.0, -0.566),    # pure up
]


def depth_offsets(tile_w: int, tile_h: int) -> list[tuple[int, int]]:
    """Pixel-space depth offsets for a given tile size."""
    return [(int(fx * tile_w), int(fy * tile_h)) for fx, fy in DEPTH_OFFSET_FRACS]


@dataclass
class Anchor:
    zone: str  # "main_board" | "queue" | "tray"
    row: int  # main_board row; -1 otherwise
    col: int  # main_board col / tray slot index; -1 otherwise
    queue_id: str | None  # "<side>_<tier>" for queue, None otherwise
    cx: int
    cy: int


@dataclass
class Template:
    """A level template plus the image dimensions it was captured at, so we
    can rescale to other phone resolutions on load."""
    image_w: int
    image_h: int
    tile_w: int  # observed median tile width in template image
    tile_h: int  # observed median tile height
    anchors: list[Anchor]


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


def build_template(detections: list[Detection], image_w: int, image_h: int) -> Template:
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
    # Tray cy is observed empirically at ~0.88 * image_h; slots evenly spaced
    # across the full image width.
    tray_cy = int(image_h * 0.879)
    tray_cxs = [int(image_w * frac) for frac in [0.127, 0.252, 0.376, 0.500, 0.624, 0.748, 0.873]]
    for i, cx in enumerate(tray_cxs):
        anchors.append(Anchor(
            zone="tray", row=-1, col=i, queue_id=None,
            cx=cx, cy=tray_cy,
        ))

    tile_w = int(np.median([d.w for d in detections])) if detections else 143
    tile_h = int(np.median([d.h for d in detections])) if detections else 143
    return Template(image_w=image_w, image_h=image_h, tile_w=tile_w, tile_h=tile_h, anchors=anchors)


def save_template(template: Template, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "image_w": template.image_w,
        "image_h": template.image_h,
        "tile_w": template.tile_w,
        "tile_h": template.tile_h,
        "anchors": [asdict(a) for a in template.anchors],
    }, indent=2))


def load_template(path: Path) -> Template | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return Template(
        image_w=data["image_w"],
        image_h=data["image_h"],
        tile_w=data["tile_w"],
        tile_h=data["tile_h"],
        anchors=[Anchor(**a) for a in data["anchors"]],
    )


def scale_template(template: Template, target_w: int, target_h: int) -> Template:
    """Rescale a template to a target image resolution. Useful when the template
    was captured on a different phone than the current screenshot."""
    if (template.image_w, template.image_h) == (target_w, target_h):
        return template
    sx = target_w / template.image_w
    sy = target_h / template.image_h
    scaled_anchors = [
        Anchor(
            zone=a.zone, row=a.row, col=a.col, queue_id=a.queue_id,
            cx=int(a.cx * sx), cy=int(a.cy * sy),
        )
        for a in template.anchors
    ]
    return Template(
        image_w=target_w, image_h=target_h,
        tile_w=int(template.tile_w * sx),
        tile_h=int(template.tile_h * sy),
        anchors=scaled_anchors,
    )


def snap_detections(
    detections: list[Detection],
    template: Template,
    image_w: int,
    *,
    main_max_distance: float = 60.0,
    tray_max_distance: float = 60.0,
    queue_cy_tolerance: float = 50.0,
) -> tuple[list[SnapResult], list[int]]:
    """Snap detections to template anchors with zone-aware logic.

    main_board: try all DEPTH_OFFSETS; nearest match wins (greedy).
    tray: snap to nearest of 7 slot anchors by cx.
    queue: match by (side, tier) inferred from (cx, cy) — queue heads can
      appear anywhere along their strip's cx range, so we don't require cx
      proximity to the canonical anchor.
    """
    anchors = template.anchors
    queue_anchors = [a for a in anchors if a.zone == "queue"]
    queue_cy_values = sorted({a.cy for a in queue_anchors})
    offsets = depth_offsets(template.tile_w, template.tile_h)

    candidates: list[tuple[float, int, int, tuple[int, int]]] = []  # (dist, det_idx, anchor_idx, offset)
    for di, d in enumerate(detections):
        for ai, a in enumerate(anchors):
            if a.zone == "main_board":
                for ox, oy in offsets:
                    target_x = a.cx + ox
                    target_y = a.cy + oy
                    dist = ((d.cx - target_x) ** 2 + (d.cy - target_y) ** 2) ** 0.5
                    if dist <= main_max_distance:
                        candidates.append((dist, di, ai, (ox, oy)))
            elif a.zone == "tray":
                dist = ((d.cx - a.cx) ** 2 + (d.cy - a.cy) ** 2) ** 0.5
                if dist <= tray_max_distance:
                    candidates.append((dist, di, ai, (0, 0)))

        if queue_cy_values:
            best_queue_cy = min(queue_cy_values, key=lambda qcy: abs(d.cy - qcy))
            cy_dist = abs(d.cy - best_queue_cy)
            if cy_dist <= queue_cy_tolerance:
                target_qid = _queue_id_for(d.cx, d.cy, image_w, queue_cy_values)
                for ai, a in enumerate(anchors):
                    if a.zone == "queue" and a.queue_id == target_qid:
                        candidates.append((float(cy_dist), di, ai, (0, 0)))
                        break

    UNREACHABLE = 1e6
    n_dets = len(detections)
    n_anchors = len(anchors)
    cost = np.full((n_dets, n_anchors), UNREACHABLE, dtype=float)
    best_offset = {}
    for dist, di, ai, off in candidates:
        if dist < cost[di, ai]:
            cost[di, ai] = dist
            best_offset[(di, ai)] = off

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
