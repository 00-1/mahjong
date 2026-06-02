"""Estimate stack depth from a single screenshot by reading "ghost" tiles
peeking out from behind the top tile face.

A depth-1 stack has only the visible top tile and dark green background
around its corners. A depth >= 2 stack has another tile face offset by
half-a-tile diagonally, peeking out from one of the four corners just
outside the top tile's bbox.

We sample 4 small patches just past the top tile's outer corners and check
how much "tile cream" (high V, low S in HSV) each contains. If any corner
exceeds a threshold, classify depth >= 2 and remember the offset direction
(which is the stack's render lean).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


# Same thresholds as the tile detector
TILE_V_MIN = 180
TILE_S_MAX = 90

# Patch size for sampling each corner (px). 30x30 is plenty; we just need a
# representative read of corner cream-content.
PATCH = 30

# Distance from tile bbox edge to patch center (px). Equal to half the diagonal
# offset of a half-tile: detected ghost centers sit at offset (~76, ~81).
# A small post-edge gap places the patch on the visible part of the ghost.
PATCH_OFFSET = 8

CREAM_FRAC_THRESHOLD = 0.4  # min fraction of "cream" pixels to call depth >= 2


@dataclass
class DepthEstimate:
    depth_at_least: int  # 1 or 2 (we can only distinguish those for now)
    lean: tuple[int, int] | None  # (sign_x, sign_y) of the stack offset; None if depth=1
    corner_cream: dict[str, float]  # cream fraction at each corner ("br", "bl", "tr", "tl")


def _cream_mask(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    _, S, V = cv2.split(hsv)
    return ((V >= TILE_V_MIN) & (S <= TILE_S_MAX)).astype(np.uint8)


def _patch_cream_frac(mask: np.ndarray, cx: int, cy: int) -> float:
    h, w = mask.shape[:2]
    half = PATCH // 2
    x0, x1 = max(0, cx - half), min(w, cx + half)
    y0, y1 = max(0, cy - half), min(h, cy + half)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    patch = mask[y0:y1, x0:x1]
    return float(patch.mean())


def estimate_depth_at_anchor(
    bgr: np.ndarray,
    anchor_cx: int,
    anchor_cy: int,
    tile_w: int,
    tile_h: int,
) -> DepthEstimate:
    """Sample 4 diagonal corners just outside the tile bbox and call depth>=2
    if any has high cream content."""
    mask = _cream_mask(bgr)
    half_w = tile_w // 2
    half_h = tile_h // 2
    corners = {
        "br": (anchor_cx + half_w + PATCH_OFFSET, anchor_cy + half_h + PATCH_OFFSET, +1, +1),
        "bl": (anchor_cx - half_w - PATCH_OFFSET, anchor_cy + half_h + PATCH_OFFSET, -1, +1),
        "tr": (anchor_cx + half_w + PATCH_OFFSET, anchor_cy - half_h - PATCH_OFFSET, +1, -1),
        "tl": (anchor_cx - half_w - PATCH_OFFSET, anchor_cy - half_h - PATCH_OFFSET, -1, -1),
    }
    fractions = {key: _patch_cream_frac(mask, x, y) for key, (x, y, _, _) in corners.items()}
    best_key = max(fractions, key=fractions.get)
    if fractions[best_key] >= CREAM_FRAC_THRESHOLD:
        sx, sy = corners[best_key][2], corners[best_key][3]
        return DepthEstimate(depth_at_least=2, lean=(sx, sy), corner_cream=fractions)
    return DepthEstimate(depth_at_least=1, lean=None, corner_cream=fractions)
