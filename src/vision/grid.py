"""Cluster tile detections into a grid and classify zones.

Approach: gap-clustering on Y centers gives row bands, then gap-clustering on
X centers (across all detections) gives column positions. The first few rows
are the main board; rows that sit below a large vertical gap are queue rows.

This is intentionally dumb. Once we have multi-run data, we'll switch to
overlaying detections onto a known-good level template instead of clustering
fresh each time.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.vision.detect import Detection


@dataclass
class GridAssignment:
    detection_idx: int
    row: int
    col: int
    zone: str  # "main_board" or "queue"


def _cluster_1d(values: list[int], gap_threshold: int) -> list[list[int]]:
    """Group sorted values into clusters whenever the gap exceeds threshold.
    Returns list of clusters of original indices."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    clusters: list[list[int]] = []
    current: list[int] = []
    last_v: int | None = None
    for i in order:
        v = values[i]
        if last_v is None or (v - last_v) <= gap_threshold:
            current.append(i)
        else:
            clusters.append(current)
            current = [i]
        last_v = v
    if current:
        clusters.append(current)
    return clusters


def _cluster_centers(values: list[int], typical_size: int) -> list[tuple[int, int]]:
    """Cluster 1D values, return (cluster_id, cluster_center_value) for each input index.

    Uses gap = typical_size * 0.6 — anything within ~60% of a tile width is
    same row/column.
    """
    gap = int(typical_size * 0.6)
    clusters = _cluster_1d(values, gap)
    out = [(0, 0)] * len(values)
    for cid, idxs in enumerate(clusters):
        center = int(np.mean([values[i] for i in idxs]))
        for i in idxs:
            out[i] = (cid, center)
    return out


def assign_grid(detections: list[Detection]) -> list[GridAssignment]:
    if not detections:
        return []

    typical_w = int(np.median([d.w for d in detections]))
    typical_h = int(np.median([d.h for d in detections]))

    cy_values = [d.cy for d in detections]
    cx_values = [d.cx for d in detections]

    row_assignments = _cluster_centers(cy_values, typical_h)
    col_assignments = _cluster_centers(cx_values, typical_w)

    # Decide which row clusters are main_board vs queue: queue rows are separated
    # from main rows by a vertical gap > ~1.2 * tile_h (one tile slot of empty space).
    distinct_rows = sorted({(r, c) for r, c in row_assignments})
    row_centers = [c for _, c in distinct_rows]
    queue_threshold_gap = int(typical_h * 1.2)

    last_main_row_idx: int | None = None
    for i in range(1, len(row_centers)):
        if row_centers[i] - row_centers[i - 1] > queue_threshold_gap:
            last_main_row_idx = i - 1
            break
    if last_main_row_idx is None:
        last_main_row_idx = len(row_centers) - 1

    out: list[GridAssignment] = []
    for idx, ((r, _), (c, _)) in enumerate(zip(row_assignments, col_assignments)):
        zone = "main_board" if r <= last_main_row_idx else "queue"
        out.append(GridAssignment(detection_idx=idx, row=r, col=c, zone=zone))
    return out
