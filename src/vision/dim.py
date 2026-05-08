"""Detect "dim" tiles — non-selectable tiles in the level layout that render
at lower brightness than the bright top tiles.

In levels with stacks of width > 1 (where blocking adjacent tiles makes some
positions un-tappable), the blocked tiles still render visibly but at reduced
brightness. The bright detector misses them; this module catches them.

Strategy:
1. Build a "tile-cream" mask at a looser V threshold (V >= 120 vs 180 for
   bright detector).
2. Subtract the bright-tile regions to leave only dim tile contours.
3. Filter contours by area + aspect ratio just like the bright detector.

For ID, identify each dim tile by color histogram against library samples
(more reliable than pHash since the rendering is dim/faded).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from src.vision.detect import Detection


@dataclass
class DimDetection:
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


def detect_dim_tiles(
    bgr: np.ndarray,
    bright_detections: list[Detection],
    *,
    v_min_dim: int = 120,
    s_max: int = 110,
    min_area_frac: float = 0.0015,
    max_area_frac: float = 0.02,
    min_aspect: float = 0.7,
    max_aspect: float = 1.3,
) -> list[DimDetection]:
    h, w = bgr.shape[:2]
    img_area = h * w

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    V = hsv[..., 2]
    # Use brightness only — dim tiles have colorful art (high S) plus cream
    # border. Bright detector found cream-border contours; this catches whole
    # tile bodies (art included) by brightness alone.
    bright_mask_pixels = (V >= v_min_dim).astype(np.uint8) * 255

    # Suppress bright-tile regions so we only get dim contours
    bright_mask = np.zeros((h, w), dtype=np.uint8)
    pad = 5
    for d in bright_detections:
        cv2.rectangle(bright_mask,
                      (d.x - pad, d.y - pad),
                      (d.x + d.w + pad, d.y + d.h + pad),
                      255, -1)
    bright_mask_pixels[bright_mask > 0] = 0

    # Use larger morphology to bridge gaps in colorful art areas
    k = 11
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    bright_mask_pixels = cv2.morphologyEx(bright_mask_pixels, cv2.MORPH_CLOSE, kernel)
    bright_mask_pixels = cv2.morphologyEx(bright_mask_pixels, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(bright_mask_pixels, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    detections: list[DimDetection] = []
    min_area = min_area_frac * img_area
    max_area = max_area_frac * img_area
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue
        x, y, ww, hh = cv2.boundingRect(cnt)
        aspect = ww / hh if hh else 0
        if aspect < min_aspect or aspect > max_aspect:
            continue
        detections.append(DimDetection(x=x, y=y, w=ww, h=hh))

    detections.sort(key=lambda d: (d.cy, d.cx))
    return detections


def identify_dim_tile(
    bgr: np.ndarray,
    dim: DimDetection,
    library_samples: dict[str, np.ndarray],
) -> tuple[str | None, float]:
    """Identify a dim tile by HSV histogram match against library samples.
    Returns (best_tile_id, score) where lower score = better match."""
    crop = bgr[dim.y:dim.y + dim.h, dim.x:dim.x + dim.w]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
    cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)

    best_id = None
    best_score = float("inf")
    for tile_id, sample in library_samples.items():
        sample_r = cv2.resize(sample, (dim.w, dim.h))
        sample_hsv = cv2.cvtColor(sample_r, cv2.COLOR_BGR2HSV)
        sample_hist = cv2.calcHist([sample_hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
        cv2.normalize(sample_hist, sample_hist, 0, 1, cv2.NORM_MINMAX)
        score = float(cv2.compareHist(hist, sample_hist, cv2.HISTCMP_CHISQR_ALT))
        if score < best_score:
            best_score = score
            best_id = tile_id
    return best_id, best_score
