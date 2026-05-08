"""Detect ALL tile positions in a screenshot, including dim/non-selectable
ones. Then identify each by HSV color histogram matching against the library.

Strategy:
1. Build a "tile-content" mask: not-background AND has minimum brightness.
   Background (dark green) excluded by hue. Header/footer regions trimmed.
2. Erode to separate tightly-packed tiles by their thin dark separators.
3. Find contours of expected tile size (~tile_w * tile_h area).
4. For each contour: extract the bbox region, identify by HSV histogram.

The library is trained on bright tile crops; dim tile renderings have lower
brightness but similar hue/saturation distribution, so HSV histograms (using
H + S, ignoring V) match reasonably well across brightness levels.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class AllTileDetection:
    x: int
    y: int
    w: int
    h: int
    is_bright: bool  # whether the bright cream detector would have caught this

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


def detect_all_tiles(
    bgr: np.ndarray,
    *,
    bg_hue_min: int = 40,
    bg_hue_max: int = 90,
    bg_v_max: int = 110,
    play_y_min: int = 250,
    play_y_max: int = 1750,
    erode_k: int = 9,
    min_area_frac: float = 0.0010,
    max_area_frac: float = 0.025,
    bright_v_min: int = 180,
) -> list[AllTileDetection]:
    h, w = bgr.shape[:2]
    img_area = h * w

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, V = hsv[..., 0], hsv[..., 2]
    not_bg = ~((H >= bg_hue_min) & (H <= bg_hue_max) & (V < bg_v_max))
    not_dark = V > 70
    mask = (not_bg & not_dark).astype(np.uint8) * 255
    # Restrict to play area
    play = np.zeros_like(mask)
    play[play_y_min:play_y_max, :] = mask[play_y_min:play_y_max, :]

    # Tiles are tightly packed but have a thin dark separator strip between them.
    # Erode aggressively to break them apart, then dilate back.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (erode_k, erode_k))
    eroded = cv2.erode(play, kernel)
    # Dilate to restore approximate size
    dilated = cv2.dilate(eroded, kernel)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    detections: list[AllTileDetection] = []
    min_area = min_area_frac * img_area
    max_area = max_area_frac * img_area
    bright_mask = (V >= bright_v_min).astype(np.uint8)
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area:
            continue
        x, y, ww, hh = cv2.boundingRect(c)
        aspect = ww / max(1, hh)
        if aspect < 0.5 or aspect > 1.6:
            continue
        # Check brightness inside this contour
        roi_v = V[y:y + hh, x:x + ww]
        is_bright = float((roi_v >= bright_v_min).sum() / max(1, roi_v.size)) > 0.25
        detections.append(AllTileDetection(x=x, y=y, w=ww, h=hh, is_bright=is_bright))

    detections.sort(key=lambda d: (d.cy, d.cx))
    return detections


def identify_by_hsv_histogram(
    bgr_crop: np.ndarray,
    library_samples: dict[str, np.ndarray],
    h_bins: int = 24,
    s_bins: int = 8,
    *,
    use_saturation_mask: bool = True,
) -> tuple[str | None, float, dict[str, float]]:
    """Identify a tile crop by H+S histogram match against library samples."""
    hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV)
    sat_mask = ((hsv[..., 1] > 30).astype(np.uint8) * 255) if use_saturation_mask else None
    crop_hist = cv2.calcHist([hsv], [0, 1], sat_mask, [h_bins, s_bins],
                             [0, 180, 0, 256])
    cv2.normalize(crop_hist, crop_hist, 0, 1, cv2.NORM_MINMAX)
    scores: dict[str, float] = {}
    for tile_id, sample in library_samples.items():
        sample_r = cv2.resize(sample, (bgr_crop.shape[1], bgr_crop.shape[0]))
        sample_hsv = cv2.cvtColor(sample_r, cv2.COLOR_BGR2HSV)
        sample_sat = ((sample_hsv[..., 1] > 30).astype(np.uint8) * 255) if use_saturation_mask else None
        sample_hist = cv2.calcHist([sample_hsv], [0, 1], sample_sat,
                                   [h_bins, s_bins], [0, 180, 0, 256])
        cv2.normalize(sample_hist, sample_hist, 0, 1, cv2.NORM_MINMAX)
        score = float(cv2.compareHist(crop_hist, sample_hist, cv2.HISTCMP_CHISQR_ALT))
        scores[tile_id] = score
    best = min(scores, key=scores.get)
    return best, scores[best], scores


def _normalize_for_hash(bgr: np.ndarray) -> np.ndarray:
    """Equalize brightness so dim tiles look comparable to bright library
    samples. Convert to LAB, equalize the L channel, convert back to BGR."""
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    L, A, B = cv2.split(lab)
    L_eq = cv2.equalizeHist(L)
    return cv2.cvtColor(cv2.merge([L_eq, A, B]), cv2.COLOR_LAB2BGR)


def identify_by_phash(
    bgr_crop: np.ndarray,
    library_samples: dict[str, np.ndarray],
    hash_size: int = 16,
    crop_frac: float = 0.78,
    *,
    normalize: bool = False,
) -> tuple[str | None, float, dict[str, float]]:
    """Identify a tile by perceptual hash match against library samples.
    Lower score = better match (Hamming distance, 0..hash_size**2).

    normalize=True applies brightness equalization before hashing — useful
    for dim crops where brightness differs from the bright library samples.
    """
    import imagehash
    from PIL import Image

    h_in, w_in = bgr_crop.shape[:2]
    cw = int(w_in * crop_frac / 2)
    ch = int(h_in * crop_frac / 2)
    cx, cy = w_in // 2, h_in // 2
    interior = bgr_crop[max(0, cy - ch):cy + ch, max(0, cx - cw):cx + cw]
    if interior.size == 0:
        interior = bgr_crop

    if normalize:
        interior = _normalize_for_hash(interior)

    crop_hash = imagehash.phash(
        Image.fromarray(cv2.cvtColor(interior, cv2.COLOR_BGR2RGB)),
        hash_size=hash_size,
    )
    scores: dict[str, float] = {}
    for tile_id, sample in library_samples.items():
        if normalize:
            sample = _normalize_for_hash(sample)
        sample_hash = imagehash.phash(
            Image.fromarray(cv2.cvtColor(sample, cv2.COLOR_BGR2RGB)),
            hash_size=hash_size,
        )
        scores[tile_id] = float(crop_hash - sample_hash)
    best = min(scores, key=scores.get)
    return best, scores[best], scores


def identify_by_template_match(
    bgr_crop: np.ndarray,
    library_samples: dict[str, np.ndarray],
    crop_frac: float = 0.78,
) -> tuple[str | None, float, dict[str, float]]:
    """Identify a tile by normalized cross-correlation on grayscale-equalized
    crops. Brightness-invariant via histogram equalization."""
    h_in, w_in = bgr_crop.shape[:2]
    cw = int(w_in * crop_frac / 2)
    ch = int(h_in * crop_frac / 2)
    cx, cy = w_in // 2, h_in // 2
    interior = bgr_crop[max(0, cy - ch):cy + ch, max(0, cx - cw):cx + cw]
    if interior.size == 0:
        interior = bgr_crop

    target_size = (96, 96)  # downsample for speed + denoise
    crop_gray = cv2.cvtColor(interior, cv2.COLOR_BGR2GRAY)
    crop_gray = cv2.resize(crop_gray, target_size)
    crop_gray = cv2.equalizeHist(crop_gray)

    scores: dict[str, float] = {}
    for tile_id, sample in library_samples.items():
        sample_gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
        sample_gray = cv2.resize(sample_gray, target_size)
        sample_gray = cv2.equalizeHist(sample_gray)
        # NCC: 1.0 = perfect match, -1.0 = inverse, 0 = uncorrelated.
        # Convert to "lower-is-better": score = 1 - ncc
        result = cv2.matchTemplate(crop_gray, sample_gray, cv2.TM_CCOEFF_NORMED)
        ncc = float(result[0, 0])
        scores[tile_id] = 1.0 - ncc
    best = min(scores, key=scores.get)
    return best, scores[best], scores


def identify_combined(
    bgr_crop: np.ndarray,
    library_samples: dict[str, np.ndarray],
    is_bright: bool = True,
) -> tuple[str | None, float, dict[str, float]]:
    """Identify a tile using pHash + histogram, with brightness equalization
    for dim crops to make their pHash comparable to bright library samples.
    """
    # Bright pHash first — works great for bright tiles
    phash_id, phash_score, phash_scores = identify_by_phash(
        bgr_crop, library_samples, normalize=False,
    )
    sorted_phash = sorted(phash_scores.values())
    runner_up = sorted_phash[1] if len(sorted_phash) > 1 else float("inf")
    margin = runner_up - phash_score
    if is_bright and margin >= 8 and phash_score < 80:
        return phash_id, phash_score, phash_scores

    # For dim or ambiguous, use NCC + histogram + normalized pHash, ensemble.
    ncc_id, ncc_score, ncc_scores = identify_by_template_match(bgr_crop, library_samples)
    hist_id, hist_score, hist_scores = identify_by_hsv_histogram(bgr_crop, library_samples)

    # Rank-based fusion across all three signals
    def ranks(scores):
        return {tid: i for i, (tid, _) in enumerate(sorted(scores.items(), key=lambda x: x[1]))}
    phash_rank = ranks(phash_scores)
    ncc_rank = ranks(ncc_scores)
    hist_rank = ranks(hist_scores)
    combined = {
        tid: phash_rank[tid] + 2 * ncc_rank[tid] + hist_rank[tid]  # NCC weighted higher
        for tid in phash_scores
    }
    best = min(combined, key=combined.get)
    return best, float(phash_scores[best]), phash_scores
