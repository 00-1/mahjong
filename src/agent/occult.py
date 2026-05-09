"""Anchor-driven occult (dim/hidden) tile prediction.

Strategic prior: prediction quality matters more than detection coverage.
For each level-template anchor that doesn't currently have a bright tile,
we ACTIVELY SAMPLE the screen at the anchor + 8 lean-offset positions,
ask "what tile is here?" via a multi-method ensemble, and emit a
prediction with calibrated confidence.

Compared to the original `dim_learn.predict_dim`:
- Doesn't depend on the dim detector finding the tile (which has
  recall problems)
- Tries every plausible offset position, not just where a contour was
- Uses ORB keypoint matching in addition to pHash / NCC / hue, which
  gives shape signal independent of brightness — important for the
  orange/yellow color cluster where color alone is ambiguous

The output is a dict {anchor_key: BestPrediction}. Anchor_key is
("main_board", row, col) or ("queue", queue_id).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np

from src.vision.all_tiles import (
    _dominant_hue,
    identify_by_phash,
    identify_by_template_match,
    identify_by_hsv_histogram,
)
from src.vision.peek import load_library_samples
from src.vision.template import depth_offsets, load_template, scale_template


@dataclass
class OccultPrediction:
    anchor_key: tuple  # ("main_board", row, col) or ("queue", queue_id)
    sample_cx: int  # where on screen we sampled
    sample_cy: int
    offset: tuple[int, int]  # (ox, oy) tested
    predicted_tile_id: str | None
    confidence: float  # 0..1, higher = more confident
    method_scores: dict  # per-method breakdown for analysis


def _orb_match_score(
    crop: np.ndarray,
    sample: np.ndarray,
    orb: cv2.ORB,
    bf: cv2.BFMatcher,
    nfeatures: int = 100,
) -> float:
    """ORB keypoint matching. Returns a score in [0, 1] roughly correlating
    with shape similarity, brightness-invariant.

    Shape signal: count "good" matches (Lowe ratio test) normalized by
    min keypoint count.
    """
    crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    sample_gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    # Equalize for invariance to brightness shift
    crop_gray = cv2.equalizeHist(crop_gray)
    sample_gray = cv2.equalizeHist(sample_gray)

    kp1, des1 = orb.detectAndCompute(crop_gray, None)
    kp2, des2 = orb.detectAndCompute(sample_gray, None)
    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        return 0.0

    matches = bf.knnMatch(des1, des2, k=2)
    good = 0
    for pair in matches:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < 0.75 * n.distance:
            good += 1
    return good / max(4, min(len(kp1), len(kp2)))


def _hue_distance(h1: float | None, h2: float | None) -> float | None:
    if h1 is None or h2 is None:
        return None
    d = abs(h1 - h2)
    return min(d, 180 - d)


def predict_at_position(
    bgr: np.ndarray,
    cx: int, cy: int,
    tile_w: int, tile_h: int,
    library_samples: dict[str, np.ndarray],
    library_hues: dict[str, float | None],
    orb: cv2.ORB,
    bf: cv2.BFMatcher,
) -> tuple[str | None, float, dict]:
    """Sample a tile-sized crop and identify what tile (if any) is there.

    Returns (tile_id, confidence_in_[0,1], method_breakdown).
    Returns (None, 0.0, {...}) if no tile detected at this position.
    """
    h, w = bgr.shape[:2]
    half_w, half_h = tile_w // 2, tile_h // 2
    x0, y0 = cx - half_w, cy - half_h
    x1, y1 = cx + half_w, cy + half_h
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None, 0.0, {"reason": "out_of_bounds"}
    crop = bgr[y0:y1, x0:x1]

    # Pre-filter: is there even a tile here?
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    v_mean = float(hsv[..., 2].mean())
    sat_frac = float((hsv[..., 1] > 60).mean())
    cream_frac = float(((hsv[..., 2] >= 130) & (hsv[..., 1] <= 90)).mean())
    if v_mean < 70 and sat_frac < 0.08:
        return None, 0.0, {"reason": "background", "v_mean": v_mean, "sat_frac": sat_frac}
    if cream_frac < 0.05 and sat_frac < 0.10:
        return None, 0.0, {"reason": "no_tile_signature",
                           "cream_frac": cream_frac, "sat_frac": sat_frac}

    # Method 1: pHash with brightness normalization
    phash_id, phash_score, phash_scores = identify_by_phash(
        crop, library_samples, normalize=True,
    )

    # Method 2: NCC on grayscale-equalized crops
    ncc_id, ncc_score, ncc_scores = identify_by_template_match(crop, library_samples)

    # Method 3: HSV histogram
    hist_id, hist_score, hist_scores = identify_by_hsv_histogram(crop, library_samples)

    # Method 4: ORB keypoints (best signal for shape disambiguation)
    crop_hue = _dominant_hue(crop)
    orb_scores = {}
    # Only run ORB on hue-filtered candidates to keep it cheap (it's slow)
    for tid, sample in library_samples.items():
        if crop_hue is not None:
            ref_hue = library_hues.get(tid)
            hd = _hue_distance(crop_hue, ref_hue)
            if hd is not None and hd > 25:
                orb_scores[tid] = 0.0
                continue
        orb_scores[tid] = _orb_match_score(crop, sample, orb, bf)

    # Rank fusion
    def ranks(scores, ascending=True):
        items = sorted(scores.items(), key=lambda x: x[1] if ascending else -x[1])
        return {tid: i for i, (tid, _) in enumerate(items)}

    phash_rank = ranks(phash_scores, ascending=True)
    ncc_rank = ranks(ncc_scores, ascending=True)
    hist_rank = ranks(hist_scores, ascending=True)
    orb_rank = ranks(orb_scores, ascending=False)  # higher orb = better

    combined = {}
    for tid in library_samples:
        # Weighted: ORB (shape) and pHash matter more than color overlap
        combined[tid] = (
            phash_rank[tid] * 1.5
            + ncc_rank[tid] * 1.0
            + hist_rank[tid] * 0.5
            + orb_rank[tid] * 1.5
        )
    best_id = min(combined, key=combined.get)
    best_score = combined[best_id]

    # Confidence = margin to runner-up, normalized by spread
    sorted_combined = sorted(combined.values())
    runner_up = sorted_combined[1] if len(sorted_combined) > 1 else best_score + 1
    margin = (runner_up - best_score) / max(1, sorted_combined[-1] - sorted_combined[0])
    # Boost if ORB agrees
    orb_top_id = max(orb_scores, key=orb_scores.get)
    orb_top_score = orb_scores[orb_top_id]
    if orb_top_id == best_id and orb_top_score > 0.10:
        confidence_boost = 0.15
    else:
        confidence_boost = 0.0
    # Penalty if cream/sat ratios were borderline
    quality_penalty = 0.0
    if cream_frac < 0.10:
        quality_penalty += 0.15
    if sat_frac < 0.10:
        quality_penalty += 0.10

    confidence = max(0.0, min(1.0, margin + confidence_boost - quality_penalty))

    return best_id, confidence, {
        "phash_top": phash_id, "phash_score": phash_score,
        "ncc_top": ncc_id, "ncc_score": ncc_score,
        "hist_top": hist_id, "hist_score": hist_score,
        "orb_top": orb_top_id, "orb_top_score": round(orb_top_score, 3),
        "v_mean": round(v_mean, 1), "sat_frac": round(sat_frac, 3),
        "cream_frac": round(cream_frac, 3),
        "margin": round(margin, 3),
    }


def predict_occult_at_anchors(
    bgr: np.ndarray,
    template,
    bright_anchors: set,
    library_samples: dict[str, np.ndarray],
    *,
    try_offsets: bool = True,
) -> dict[tuple, OccultPrediction]:
    """For each anchor not in bright_anchors, sample at anchor + 9 offsets,
    pick the highest-confidence prediction.

    bright_anchors: set of anchor keys (e.g. ("main_board", 2, 5)) that
      already have bright detections — skip those.
    """
    # Pre-compute library hues for fast filtering
    library_hues = {tid: _dominant_hue(s) for tid, s in library_samples.items()}
    orb = cv2.ORB_create(nfeatures=200)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

    offsets = depth_offsets(template.tile_w, template.tile_h) if try_offsets else [(0, 0)]

    predictions: dict[tuple, OccultPrediction] = {}
    for a in template.anchors:
        if a.zone == "main_board":
            key = ("main_board", a.row, a.col)
        elif a.zone == "queue":
            key = ("queue", a.queue_id)
        else:
            continue
        if key in bright_anchors:
            continue

        best_pred: OccultPrediction | None = None
        for ox, oy in offsets:
            tid, conf, methods = predict_at_position(
                bgr, a.cx + ox, a.cy + oy,
                template.tile_w, template.tile_h,
                library_samples, library_hues, orb, bf,
            )
            if tid is None:
                continue
            if best_pred is None or conf > best_pred.confidence:
                best_pred = OccultPrediction(
                    anchor_key=key,
                    sample_cx=a.cx + ox,
                    sample_cy=a.cy + oy,
                    offset=(ox, oy),
                    predicted_tile_id=tid,
                    confidence=conf,
                    method_scores=methods,
                )
        if best_pred is not None:
            predictions[key] = best_pred
    return predictions


def verify_anchor_predictions(
    predictions: dict[tuple, OccultPrediction],
    new_state: dict,
) -> list[dict]:
    """Compare anchor-keyed predictions to new_state's bright tiles.
    For each anchor that was occult and is now bright, record outcome."""
    main_lookup = {
        ("main_board", c["row"], c["col"]): c.get("tile_id")
        for c in new_state.get("main_board", [])
    }
    queue_lookup = {
        ("queue", q["queue_id"]): q.get("tile_id")
        for q in new_state.get("queues", [])
    }
    full_lookup = {**main_lookup, **queue_lookup}

    out = []
    for key, pred in predictions.items():
        actual = full_lookup.get(key)
        if actual is None:
            continue
        out.append({
            "anchor_key": list(key),
            "predicted_tile_id": pred.predicted_tile_id,
            "actual_tile_id": actual,
            "correct": pred.predicted_tile_id == actual,
            "confidence": pred.confidence,
            "offset": list(pred.offset),
            "methods": pred.method_scores,
        })
    return out


def aggregate_occult_accuracy(
    levels_root: Path,
    level: int,
    comparisons: list[dict],
) -> None:
    """Update data/levels/NN/occult_accuracy.json with verification outcomes."""
    p = levels_root / f"{level:02d}" / "occult_accuracy.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        data = json.loads(p.read_text())
    else:
        data = {
            "level": level, "total": 0, "correct": 0,
            "by_predicted": {}, "by_actual": {},
            "confusion": {},
            "by_confidence_bucket": {},
            "method_top_agrees_when_correct": 0,
            "method_top_agrees_when_wrong": 0,
        }
    for k in ["by_confidence_bucket"]:
        if k not in data:
            data[k] = {}
    for c in comparisons:
        data["total"] += 1
        if c["correct"]:
            data["correct"] += 1
        bp = data["by_predicted"].setdefault(c["predicted_tile_id"], {"total": 0, "correct": 0})
        bp["total"] += 1
        if c["correct"]:
            bp["correct"] += 1
        ba = data["by_actual"].setdefault(c["actual_tile_id"], {"total": 0, "correct": 0})
        ba["total"] += 1
        if c["correct"]:
            ba["correct"] += 1
        if not c["correct"]:
            key = f"{c['predicted_tile_id']}->{c['actual_tile_id']}"
            data["confusion"][key] = data["confusion"].get(key, 0) + 1
        conf = c.get("confidence", 0)
        bucket = "high" if conf >= 0.5 else "med" if conf >= 0.25 else "low"
        bb = data["by_confidence_bucket"].setdefault(bucket, {"total": 0, "correct": 0})
        bb["total"] += 1
        if c["correct"]:
            bb["correct"] += 1
        # Method-agreement diagnostic
        ms = c.get("methods", {})
        if all(ms.get(k) == c["predicted_tile_id"] for k in ["phash_top", "ncc_top", "orb_top"]):
            if c["correct"]:
                data["method_top_agrees_when_correct"] += 1
            else:
                data["method_top_agrees_when_wrong"] += 1
    data["accuracy"] = data["correct"] / max(1, data["total"])
    for bucket, vals in data["by_confidence_bucket"].items():
        vals["accuracy"] = vals["correct"] / max(1, vals["total"])
    p.write_text(json.dumps(data, indent=2))


def update_anchor_priors(
    levels_root: Path,
    level: int,
    state: dict,
) -> None:
    """Track which tiles appear at each anchor (across runs) at each depth.
    Builds a per-anchor distribution that the solver can use as prior."""
    p = levels_root / f"{level:02d}" / "anchor_priors.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        data = json.loads(p.read_text())
    else:
        data = {"level": level, "anchors": {}}

    for c in state.get("main_board", []):
        tid = c.get("tile_id")
        if not tid:
            continue
        depth = c.get("stack_depth") or 1
        key = f"({c['row']},{c['col']})"
        anchor_data = data["anchors"].setdefault(key, {})
        depth_key = f"d{depth}"
        depth_data = anchor_data.setdefault(depth_key, {"total": 0, "tiles": {}})
        depth_data["total"] += 1
        depth_data["tiles"][tid] = depth_data["tiles"].get(tid, 0) + 1
    p.write_text(json.dumps(data, indent=2))
