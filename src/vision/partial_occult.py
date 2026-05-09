"""Partial-occult tile identification via ORB feature matching.

The bright tile-face detector (`detect_tile_faces`) only finds fully-
visible d1 tiles — cream borders + clear faces. d2 tiles peek out
from behind d1 above them but are dimmed, partially-occluded, and
have lower V/S signatures that the bright detector skips.

But they ARE there in pixels. ORB feature matching is robust to
both partial occlusion and brightness changes, so it can identify
the dim tile face from whatever sliver is visible.

Per-screenshot validation showed ORB lands HIGH-confidence matches on
~4 of 7 typical dim positions (matches >= 8, margin >= 3 over second-
best). The rest are too partially-visible to be sure.

This module:
- Pre-extracts ORB features for every library sample (cached).
- For each anchor without a bright detection, crops the region and
  matches against the cache.
- Returns identification + confidence per anchor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from src.vision.library import TileLibrary


# ORB matching is robust to partial occlusion and brightness changes
# but slower than pHash. Tunable params:
ORB_N_FEATURES = 500
ORB_MATCH_DIST_THRESHOLD = 50  # Hamming distance per feature pair
ORB_MIN_MATCHES_HIGH_CONF = 8
ORB_MIN_MARGIN_HIGH_CONF = 3
ORB_MIN_MATCHES_MED_CONF = 5
ORB_MIN_MARGIN_MED_CONF = 2


@dataclass
class PartialOccultDetection:
    anchor_key: tuple  # ("main_board", row, col)
    tile_id: str
    matches: int
    margin: int  # matches - second_best
    confidence: str  # "high" | "med" | "low" | "skip"
    n_keypoints: int


class _ORBLibraryCache:
    """Pre-computed ORB descriptors for every library sample."""

    def __init__(self, library: TileLibrary):
        self.library = library
        self.orb = cv2.ORB_create(
            nfeatures=ORB_N_FEATURES, scaleFactor=1.2, edgeThreshold=10,
        )
        self.bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.descriptors: dict[str, list[np.ndarray]] = {}
        self._build()

    def _build(self) -> None:
        for entry in self.library.entries:
            descs: list[np.ndarray] = []
            for sample_path in entry.samples:
                full = (self.library.root.parent / sample_path
                        if not Path(sample_path).is_absolute()
                        else Path(sample_path))
                img = cv2.imread(str(full))
                if img is None:
                    continue
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                _, des = self.orb.detectAndCompute(gray, None)
                if des is not None:
                    descs.append(des)
            if descs:
                self.descriptors[entry.tile_id] = descs


_cache: _ORBLibraryCache | None = None


def _get_cache(library: TileLibrary) -> _ORBLibraryCache:
    global _cache
    if _cache is None or _cache.library is not library:
        _cache = _ORBLibraryCache(library)
    return _cache


def _crop_around_anchor(bgr: np.ndarray, cx: int, cy: int,
                        tile_w: int, tile_h: int) -> np.ndarray | None:
    """Crop a tile-sized region centered on an anchor, clipped to image."""
    h, w = bgr.shape[:2]
    half_w = tile_w // 2
    half_h = tile_h // 2
    x0, y0 = max(0, cx - half_w), max(0, cy - half_h)
    x1, y1 = min(w, cx + half_w), min(h, cy + half_h)
    if x1 - x0 < tile_w // 2 or y1 - y0 < tile_h // 2:
        return None
    return bgr[y0:y1, x0:x1]


def _is_likely_tile(crop: np.ndarray) -> bool:
    """Quick filter: dim tiles have measurable structure (V std > 30
    AND V mean > 50) vs grass background (low std, V around 70-90)."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    V = hsv[:, :, 2]
    return float(V.std()) > 30 and float(V.mean()) > 50


def detect_partial_occult(
    bgr: np.ndarray,
    library: TileLibrary,
    template,
    bright_anchors: set[tuple],
) -> dict[tuple, PartialOccultDetection]:
    """For each main_board anchor NOT in bright_anchors, attempt to
    identify the dim tile face via ORB feature matching.

    bright_anchors: the set of (zone, row, col) keys already covered
    by the bright detector. We only run partial-occult on the rest.

    Returns: dict of anchor_key -> PartialOccultDetection (only for
    cells that pass the "likely a tile" filter). Confidence levels
    surface so callers can choose how aggressive to be."""
    cache = _get_cache(library)
    out: dict[tuple, PartialOccultDetection] = {}
    for a in template.anchors:
        if a.zone != "main_board":
            continue
        key = ("main_board", a.row, a.col)
        if key in bright_anchors:
            continue
        crop = _crop_around_anchor(bgr, a.cx, a.cy, template.tile_w, template.tile_h)
        if crop is None:
            continue
        if not _is_likely_tile(crop):
            continue  # background grass
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        kp, des = cache.orb.detectAndCompute(gray, None)
        if des is None or len(des) < 5:
            continue

        best_tid: str | None = None
        best_score = 0
        second_score = 0
        for tid, sample_descs in cache.descriptors.items():
            max_for_tid = 0
            for s_des in sample_descs:
                try:
                    matches = cache.bf.match(des, s_des)
                except cv2.error:
                    continue
                good = sum(1 for m in matches if m.distance < ORB_MATCH_DIST_THRESHOLD)
                if good > max_for_tid:
                    max_for_tid = good
            if max_for_tid > best_score:
                second_score = best_score
                best_score = max_for_tid
                best_tid = tid
            elif max_for_tid > second_score:
                second_score = max_for_tid

        if best_tid is None:
            continue
        margin = best_score - second_score
        if best_score >= ORB_MIN_MATCHES_HIGH_CONF and margin >= ORB_MIN_MARGIN_HIGH_CONF:
            conf = "high"
        elif best_score >= ORB_MIN_MATCHES_MED_CONF and margin >= ORB_MIN_MARGIN_MED_CONF:
            conf = "med"
        else:
            conf = "low"
        out[key] = PartialOccultDetection(
            anchor_key=key, tile_id=best_tid, matches=best_score,
            margin=margin, confidence=conf, n_keypoints=len(kp),
        )
    return out
