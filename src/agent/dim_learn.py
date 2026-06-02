"""Dim tile prediction + ground-truth verification for the learning loop.

For each anchor that doesn't currently have a bright top tile, predict
what dim tile (if any) is there using intra-screenshot ID. Save those
predictions per step, then on the next step compare them to actual
bright tiles that appeared (because their blocker was tapped).

Records to:
- data/runs/<run_id>/tNNN.dim_predictions.json
- data/runs/<run_id>/log.jsonl  (events: dim_predict, dim_verify)
- data/levels/NN/dim_accuracy.json (aggregated)
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2

from src.vision.all_tiles import (
    detect_all_tiles,
    identify_combined,
    identify_via_intra_screenshot,
)
from src.vision.peek import load_library_samples
from src.vision.template import load_template, scale_template


@dataclass
class DimPrediction:
    cx: int
    cy: int
    bbox: tuple[int, int, int, int]
    nearest_anchor: dict | None  # {row, col} or {queue_id} or None
    predicted_tile_id: str | None
    confidence_score: float  # lower = more confident match (NCC-style)


def predict_dim(
    bgr_path: Path,
    level: int,
    tiles_dir: Path,
) -> list[DimPrediction]:
    """Detect dim tiles in the screenshot and identify each via intra-screenshot
    matching against bright tiles in the same image."""
    bgr = cv2.imread(str(bgr_path))
    if bgr is None:
        return []
    h, w = bgr.shape[:2]

    template_path = bgr_path.parents[2] / "data" / "levels" / f"{level:02d}" / "template.json"
    # Walk up to find repo root if needed
    if not template_path.exists():
        cur = bgr_path.parent
        while cur.name and not (cur / "data" / "levels" / f"{level:02d}" / "template.json").exists():
            if cur == cur.parent:
                break
            cur = cur.parent
        template_path = cur / "data" / "levels" / f"{level:02d}" / "template.json"

    template = load_template(template_path) if template_path.exists() else None
    if template is not None and (template.image_w, template.image_h) != (w, h):
        template = scale_template(template, w, h)

    # Detect bright + dim tiles
    detections = detect_all_tiles(bgr)
    bright_dets = [d for d in detections if d.is_bright]
    dim_dets = [d for d in detections if not d.is_bright]

    library_samples = load_library_samples(tiles_dir)
    bright_ids: list[str | None] = []
    for d in bright_dets:
        crop = bgr[d.y:d.y + d.h, d.x:d.x + d.w]
        tid, _, _ = identify_combined(crop, library_samples, is_bright=True)
        bright_ids.append(tid)

    predictions: list[DimPrediction] = []
    for d in dim_dets:
        crop = bgr[d.y:d.y + d.h, d.x:d.x + d.w]
        tid, score, _ = identify_via_intra_screenshot(
            bgr, crop, bright_dets, bright_ids, library_samples,
        )
        anchor = _nearest_anchor(d.cx, d.cy, template) if template is not None else None
        predictions.append(DimPrediction(
            cx=d.cx, cy=d.cy,
            bbox=(d.x, d.y, d.w, d.h),
            nearest_anchor=anchor,
            predicted_tile_id=tid,
            confidence_score=float(score),
        ))
    return predictions


def _nearest_anchor(cx: int, cy: int, template, max_dist: float = 100.0) -> dict | None:
    """Snap a dim detection to its nearest template anchor."""
    best = None
    best_d = float("inf")
    for a in template.anchors:
        d = ((cx - a.cx) ** 2 + (cy - a.cy) ** 2) ** 0.5
        if d < best_d and d <= max_dist:
            best_d = d
            best = a
    if best is None:
        return None
    if best.zone == "main_board":
        return {"zone": "main_board", "row": best.row, "col": best.col, "snap_dist": round(best_d, 1)}
    if best.zone == "queue":
        return {"zone": "queue", "queue_id": best.queue_id, "snap_dist": round(best_d, 1)}
    return {"zone": best.zone, "snap_dist": round(best_d, 1)}


def verify_predictions_vs_state(
    predictions: list[DimPrediction],
    new_state: dict,
) -> list[dict]:
    """For each prediction whose anchor now has a bright tile in new_state,
    compare predicted vs actual.

    Returns list of comparison records:
        {anchor: ..., predicted: tile_id, actual: tile_id, correct: bool, confidence: ...}
    """
    main_lookup = {(c["row"], c["col"]): c.get("tile_id") for c in new_state.get("main_board", [])}
    queue_lookup = {q["queue_id"]: q.get("tile_id") for q in new_state.get("queues", [])}

    comparisons = []
    for p in predictions:
        if p.nearest_anchor is None or p.predicted_tile_id is None:
            continue
        anchor = p.nearest_anchor
        actual = None
        if anchor.get("zone") == "main_board":
            actual = main_lookup.get((anchor["row"], anchor["col"]))
        elif anchor.get("zone") == "queue":
            actual = queue_lookup.get(anchor["queue_id"])
        if actual is None:
            continue  # anchor still empty / dim — can't verify yet
        comparisons.append({
            "anchor": anchor,
            "predicted_tile_id": p.predicted_tile_id,
            "actual_tile_id": actual,
            "correct": p.predicted_tile_id == actual,
            "confidence_score": p.confidence_score,
        })
    return comparisons


def aggregate_dim_accuracy(
    levels_root: Path,
    level: int,
    comparisons: list[dict],
) -> None:
    """Update data/levels/NN/dim_accuracy.json with new comparisons."""
    p = levels_root / f"{level:02d}" / "dim_accuracy.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        data = json.loads(p.read_text())
    else:
        data = {
            "level": level,
            "total": 0,
            "correct": 0,
            "by_predicted": {},  # tile_id -> {total, correct}
            "by_actual": {},
            "confusion": {},  # "predicted->actual" -> count
            "by_confidence_bucket": {},  # bucket -> {total, correct}
        }
    if "by_confidence_bucket" not in data:
        data["by_confidence_bucket"] = {}
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
        # Confidence bucket: lower score = more confident
        bucket = "high" if c["confidence_score"] < 0.3 else \
                 "med" if c["confidence_score"] < 0.6 else "low"
        bb = data["by_confidence_bucket"].setdefault(bucket, {"total": 0, "correct": 0})
        bb["total"] += 1
        if c["correct"]:
            bb["correct"] += 1
    data["accuracy"] = data["correct"] / max(1, data["total"])
    for bucket, vals in data["by_confidence_bucket"].items():
        vals["accuracy"] = vals["correct"] / max(1, vals["total"])
    p.write_text(json.dumps(data, indent=2))
