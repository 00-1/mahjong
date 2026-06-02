"""Identify partially-occluded tiles ("ghost peeks") around top tiles.

For each detected top tile at center (cx, cy) with size (tile_w, tile_h),
we consider 8 candidate offset positions where a depth >= 2 tile might
peek out: 4 diagonal + 4 cardinal half-tile shifts.

For each candidate, we compute the *visible sliver*: the part of the
hypothetical ghost's bbox that's NOT covered by the top tile. We then
template-match this sliver against each library tile's same-shape sliver
to identify which tile (if any) is peeking.

Limitations:
- Slivers smaller than ~25% of a tile are hard to match.
- Adjacent stacks' ghost peeks can overlap; we don't disambiguate yet.
- We only check against an anchor's own offset positions, so a "ghost" we
  see could really be a top tile of an adjacent anchor that we mistakenly
  attribute as this anchor's depth-2.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from src.vision.template import depth_offsets


@dataclass
class PeekIdentification:
    offset: tuple[int, int]  # (ox, oy) where the ghost peeks
    tile_id: str | None  # best library match
    score: float  # match score (lower = better match for SQDIFF, 0..1 normalized)
    sliver_frac: float  # fraction of tile that's visible


def _ghost_visible_mask(top_bbox: tuple[int, int, int, int],
                       ghost_bbox: tuple[int, int, int, int],
                       canvas_shape: tuple[int, int]) -> np.ndarray:
    """Binary mask, same shape as canvas, with 1 where the ghost is visible
    (inside ghost_bbox AND outside top_bbox), 0 elsewhere."""
    h, w = canvas_shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    gx, gy, gw, gh = ghost_bbox
    tx, ty, tw, th = top_bbox
    # Clip ghost bbox to canvas
    gx0, gy0 = max(0, gx), max(0, gy)
    gx1, gy1 = min(w, gx + gw), min(h, gy + gh)
    if gx1 <= gx0 or gy1 <= gy0:
        return mask
    mask[gy0:gy1, gx0:gx1] = 1
    # Subtract top tile region
    tx0, ty0 = max(0, tx), max(0, ty)
    tx1, ty1 = min(w, tx + tw), min(h, ty + th)
    if tx1 > tx0 and ty1 > ty0:
        mask[ty0:ty1, tx0:tx1] = 0
    return mask


def _crop_with_mask(bgr: np.ndarray, ghost_bbox, mask: np.ndarray) -> np.ndarray | None:
    """Crop the ghost bbox region from the image, with non-visible pixels zeroed out."""
    gx, gy, gw, gh = ghost_bbox
    h, w = bgr.shape[:2]
    if gx < 0 or gy < 0 or gx + gw > w or gy + gh > h:
        # Allow partial off-canvas — just crop what's available and pad
        gx0, gy0 = max(0, gx), max(0, gy)
        gx1, gy1 = min(w, gx + gw), min(h, gy + gh)
        crop = np.zeros((gh, gw, 3), dtype=bgr.dtype)
        # Copy the in-canvas part
        cx_off, cy_off = gx0 - gx, gy0 - gy
        if gx1 > gx0 and gy1 > gy0:
            crop[cy_off:cy_off + (gy1 - gy0), cx_off:cx_off + (gx1 - gx0)] = bgr[gy0:gy1, gx0:gx1]
    else:
        crop = bgr[gy:gy + gh, gx:gx + gw].copy()
    # Apply mask (in canvas-space) sliced to the ghost bbox
    mask_slice = np.zeros((gh, gw), dtype=np.uint8)
    mx0, my0 = max(0, -gx), max(0, -gy)
    mh, mw = mask.shape[:2]
    sx0, sy0 = max(0, gx), max(0, gy)
    sx1, sy1 = min(mw, gx + gw), min(mh, gy + gh)
    if sx1 > sx0 and sy1 > sy0:
        mask_slice[my0:my0 + (sy1 - sy0), mx0:mx0 + (sx1 - sx0)] = mask[sy0:sy1, sx0:sx1]
    crop[mask_slice == 0] = 0
    return crop


def _hsv_histogram(bgr_crop: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Compute a 2D HSV histogram (H x S, ignoring V) over masked pixels.
    Robust to partial occlusion and small lighting differences."""
    hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], mask, [16, 8],
                        [0, 180, 0, 256])
    cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
    return hist


def identify_peeks_at_anchor(
    bgr: np.ndarray,
    top_cx: int,
    top_cy: int,
    tile_w: int,
    tile_h: int,
    library_samples: dict[str, np.ndarray],
    score_threshold: float = 0.4,  # for chi-squared distance — lower is better
    min_sliver_frac: float = 0.20,
) -> list[PeekIdentification]:
    """Try each of the 8 ghost offset positions around (top_cx, top_cy).
    For each, identify which library tile best matches the visible sliver."""
    half_w, half_h = tile_w // 2, tile_h // 2
    top_bbox = (top_cx - half_w, top_cy - half_h, tile_w, tile_h)
    canvas_h, canvas_w = bgr.shape[:2]

    results: list[PeekIdentification] = []
    for ox, oy in depth_offsets(tile_w, tile_h):
        if (ox, oy) == (0, 0):
            continue
        ghost_cx, ghost_cy = top_cx + ox, top_cy + oy
        ghost_bbox = (ghost_cx - half_w, ghost_cy - half_h, tile_w, tile_h)
        mask = _ghost_visible_mask(top_bbox, ghost_bbox, (canvas_h, canvas_w))

        # Visible fraction of the ghost bbox (after top-tile occlusion)
        visible_pixels = int(mask[
            max(0, ghost_bbox[1]):ghost_bbox[1] + tile_h,
            max(0, ghost_bbox[0]):ghost_bbox[0] + tile_w,
        ].sum())
        sliver_frac = visible_pixels / max(1, tile_w * tile_h)
        if sliver_frac < min_sliver_frac:
            continue

        ghost_crop = _crop_with_mask(bgr, ghost_bbox, mask)
        if ghost_crop is None:
            continue

        # Quick filter: if the ghost crop is mostly dark (background green),
        # there's no tile face there — skip
        hsv = cv2.cvtColor(ghost_crop, cv2.COLOR_BGR2HSV)
        # Only count pixels in the visible sliver region
        sliver_mask = (
            cv2.cvtColor(ghost_crop, cv2.COLOR_BGR2GRAY) > 0
        ).astype(np.uint8)
        sliver_pixels = int(sliver_mask.sum())
        if sliver_pixels == 0:
            continue
        bright = (hsv[..., 2] > 130) & (sliver_mask == 1)
        bright_frac = bright.sum() / max(1, sliver_pixels)
        if bright_frac < 0.20:
            # Mostly dark = no tile peeking out
            continue

        # Build local mask for this ghost crop (1 where ghost is visible)
        ghost_mask_local = np.zeros((tile_h, tile_w), dtype=np.uint8)
        mx0 = max(0, ghost_bbox[0])
        my0 = max(0, ghost_bbox[1])
        mh, mw = mask.shape[:2]
        sx1 = min(mw, ghost_bbox[0] + tile_w)
        sy1 = min(mh, ghost_bbox[1] + tile_h)
        local_x0 = mx0 - ghost_bbox[0]
        local_y0 = my0 - ghost_bbox[1]
        if sx1 > mx0 and sy1 > my0:
            ghost_mask_local[local_y0:local_y0 + (sy1 - my0),
                             local_x0:local_x0 + (sx1 - mx0)] = mask[my0:sy1, mx0:sx1]

        # Match by HSV histogram comparison on the visible sliver only.
        # Color is robust to partial views; chi-squared distance is small for
        # similar distributions.
        ghost_hist = _hsv_histogram(ghost_crop, ghost_mask_local * 255)
        best_tile = None
        best_score = float("inf")
        for tile_id, sample in library_samples.items():
            if sample.shape[:2] != ghost_crop.shape[:2]:
                sample_r = cv2.resize(sample, (ghost_crop.shape[1], ghost_crop.shape[0]))
            else:
                sample_r = sample
            sample_hist = _hsv_histogram(sample_r, ghost_mask_local * 255)
            score = float(cv2.compareHist(ghost_hist, sample_hist, cv2.HISTCMP_CHISQR_ALT))
            if score < best_score:
                best_score = score
                best_tile = tile_id

        if best_tile is not None and best_score <= score_threshold:
            results.append(PeekIdentification(
                offset=(ox, oy),
                tile_id=best_tile,
                score=best_score,
                sliver_frac=sliver_frac,
            ))
    return results


def load_library_samples(tiles_dir: Path) -> dict[str, np.ndarray]:
    """Load one representative sample per tile from the library."""
    import json
    idx_path = tiles_dir / "index.json"
    data = json.loads(idx_path.read_text())
    samples: dict[str, np.ndarray] = {}
    for e in data["entries"]:
        if not e["samples"]:
            continue
        sample_path = tiles_dir.parent / e["samples"][0]
        img = cv2.imread(str(sample_path))
        if img is not None:
            samples[e["tile_id"]] = img
    return samples
