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

    Uses gap = typical_size * 0.4 — must be smaller than the half-tile offset
    (~0.566 * tile_h) so that levels with half-tile-staggered row layouts
    (level 6+) get separate rows for the staggered positions.
    """
    gap = int(typical_size * 0.4)
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
    row_assignments = _cluster_centers(cy_values, typical_h)

    # Find the largest gap between row centers — that splits main_board from queues.
    # (Smaller "first big gap" heuristics fail on mid-game states where row spacing
    # is uneven; the largest gap is the most robust signal in a clean initial state.)
    distinct_rows = sorted({(r, c) for r, c in row_assignments})
    row_centers = [c for _, c in distinct_rows]
    if len(row_centers) >= 2:
        gaps = [(row_centers[i] - row_centers[i - 1], i - 1) for i in range(1, len(row_centers))]
        # Only treat a gap as main/queue separator if it's notably larger than typical row spacing
        max_gap, max_gap_idx = max(gaps)
        median_gap = int(np.median([g for g, _ in gaps]))
        if max_gap > median_gap * 1.3:
            last_main_row_idx = max_gap_idx
        else:
            # Fallback: assume queues sit in the bottom 1-2 rows
            last_main_row_idx = max(0, len(row_centers) - 3)
    else:
        last_main_row_idx = len(row_centers) - 1

    # Cluster columns separately for main_board vs queue: queue tile cx values can
    # fall between main-board column centers and break gap-based clustering when
    # mixed in. Compute main-board columns from main-board detections only.
    main_idxs = [i for i, (r, _) in enumerate(row_assignments) if r <= last_main_row_idx]
    main_cx = [detections[i].cx for i in main_idxs]
    main_col_clusters = _cluster_centers(main_cx, typical_w) if main_cx else []

    queue_idxs = [i for i, (r, _) in enumerate(row_assignments) if r > last_main_row_idx]
    queue_cx = [detections[i].cx for i in queue_idxs]
    queue_col_clusters = _cluster_centers(queue_cx, typical_w) if queue_cx else []

    main_col_by_idx = {di: cc for di, cc in zip(main_idxs, main_col_clusters)}
    queue_col_by_idx = {di: cc for di, cc in zip(queue_idxs, queue_col_clusters)}

    out: list[GridAssignment] = []
    for idx, (r, _) in enumerate(row_assignments):
        zone = "main_board" if r <= last_main_row_idx else "queue"
        if zone == "main_board":
            c = main_col_by_idx[idx][0]
        else:
            c = queue_col_by_idx[idx][0]
        out.append(GridAssignment(detection_idx=idx, row=r, col=c, zone=zone))
    return out
