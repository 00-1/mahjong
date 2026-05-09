"""Tile economy tracker.

For each tile type, tracks supply and demand:
- visible: tiles currently selectable (bright)
- in_tray: tiles already in the tray
- predicted_occult: tiles we believe are at non-bright anchors via
  occult prediction (only counted if confidence is high enough)
- estimated_hidden: minimum count of tiles still hidden, derived from
  the multiple-of-3 invariant

For each tile T, total count must be a multiple of 3 (every triplet
clears 3 of one type). So:
    min_total[T] = 3 * ceil((visible + in_tray + predicted_occult) / 3)
    estimated_hidden[T] = max(0, min_total[T] - visible - in_tray - predicted_occult)

Knowing estimated_hidden lets the solver:
- Prioritize uncovering tile types that are short of the next triplet
- Avoid clearing visible triplets if doing so leaves us with stranded
  tiles below
- Pre-plan multi-step sequences

Per-anchor priors (from data/levels/NN/anchor_priors.json) layer on top:
across many runs, "anchor X has tile Y at depth-2 80% of the time"
gives us a probability distribution for unrevealed depths.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from src.model.state import BoardState


@dataclass
class TileEconomy:
    tile_id: str
    visible: int
    in_tray: int
    predicted_occult: int
    estimated_hidden_min: int
    full_set_min: int  # smallest multiple of 3 >= total observable

    @property
    def observable_total(self) -> int:
        return self.visible + self.in_tray + self.predicted_occult

    def needs_more(self) -> int:
        """How many more of this tile we need to complete a triplet
        (assuming we already have 1 or 2)."""
        in_play = self.visible + self.in_tray
        if in_play == 0:
            return 0
        return (3 - (in_play % 3)) % 3


def compute_economy(
    state: BoardState,
    occult_predictions: dict | None = None,
    confidence_threshold: float = 0.5,
) -> dict[str, TileEconomy]:
    """Compute per-tile-type economy from current state + (optional) occult
    predictions."""
    visible: Counter = Counter()
    for c in state.main_board:
        if c.tile_id:
            visible[c.tile_id] += 1
    for q in state.queues:
        if q.tile_id:
            visible[q.tile_id] += 1

    in_tray: Counter = Counter()
    for t in state.tray:
        if t.tile_id:
            in_tray[t.tile_id] += 1

    predicted_occult: Counter = Counter()
    if occult_predictions:
        for k, p in occult_predictions.items():
            if isinstance(p, str):
                tid, conf = p, 1.0
            elif hasattr(p, "predicted_tile_id"):
                tid = getattr(p, "predicted_tile_id", None)
                conf = getattr(p, "confidence", 0)
            elif isinstance(p, dict):
                tid = p.get("predicted_tile_id")
                conf = p.get("confidence", 0)
            else:
                tid, conf = None, 0
            if tid and conf >= confidence_threshold:
                predicted_occult[tid] += 1

    economies: dict[str, TileEconomy] = {}
    all_tiles = set(visible) | set(in_tray) | set(predicted_occult)
    for tid in all_tiles:
        v = visible.get(tid, 0)
        t = in_tray.get(tid, 0)
        p = predicted_occult.get(tid, 0)
        observable = v + t + p
        full_set = 3 * math.ceil(observable / 3)
        hidden_min = max(0, full_set - observable)
        economies[tid] = TileEconomy(
            tile_id=tid, visible=v, in_tray=t, predicted_occult=p,
            estimated_hidden_min=hidden_min,
            full_set_min=full_set,
        )
    return economies


def load_anchor_priors(levels_root: Path, level: int) -> dict:
    """Load accumulated per-anchor tile observations from past runs."""
    p = levels_root / f"{level:02d}" / "anchor_priors.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def anchor_prior_distribution(
    priors: dict,
    row: int,
    col: int,
    depth: int = 1,
) -> dict[str, float]:
    """Given accumulated priors, return P(tile = T | anchor=(r,c), depth=d)
    as a probability distribution over tile_ids.

    Smooths with a tiny Laplace prior so rarely-seen tiles get nonzero
    probability.
    """
    key = f"({row},{col})"
    anchor_data = priors.get("anchors", {}).get(key, {})
    depth_data = anchor_data.get(f"d{depth}", {})
    counts = depth_data.get("tiles", {})
    total = depth_data.get("total", 0)
    if not counts or total == 0:
        return {}

    # Laplace smoothing with alpha=0.5 for unseen tiles
    alpha = 0.5
    smoothed_total = total + alpha * len(counts)
    return {tid: (n + alpha) / smoothed_total for tid, n in counts.items()}


def predict_anchor_from_priors(
    levels_root: Path,
    level: int,
    row: int,
    col: int,
    depth: int = 1,
    min_total_observations: int = 3,
) -> tuple[str | None, float]:
    """If we have enough prior observations, return the most-likely
    tile_id at this anchor + its probability. Otherwise None.

    min_total_observations: don't trust anchors with fewer than this many
    runs of data (default 3 — needs at least 3 prior runs to be useful).
    """
    priors = load_anchor_priors(levels_root, level)
    key = f"({row},{col})"
    anchor_data = priors.get("anchors", {}).get(key, {})
    depth_data = anchor_data.get(f"d{depth}", {})
    if depth_data.get("total", 0) < min_total_observations:
        return None, 0.0
    dist = anchor_prior_distribution(priors, row, col, depth)
    if not dist:
        return None, 0.0
    best = max(dist, key=dist.get)
    return best, dist[best]


def merge_occult_and_priors(
    occult_predictions: dict | None,
    levels_root: Path,
    level: int,
    confidence_threshold: float = 0.99,
    prior_min_obs: int = 3,
    prior_min_share: float = 0.4,
) -> dict:
    """Build a unified anchor->tile_id prediction map used by simulate_tap
    to model what tile is REVEALED after we tap an anchor.

    Sources, in order of preference per anchor:
      1. Live occult prediction (only if confidence >= confidence_threshold).
      2. d2 anchor prior (the empirical distribution of what tile appears at
         depth 2, i.e. what becomes visible after the first tap on the d1
         top-of-stack tile). Required to have prior_min_obs samples and the
         dominant tile to take prior_min_share of those samples.

    Important: simulate_tap consumes this map keyed by ("main_board", r, c)
    and uses the value as the *revealed* tile (the new top after a tap).
    Thus the right prior depth is d2, not d1. (d1 is the prior on what was
    already on top — the tile we just tapped — which would be a no-op
    "reveal".)

    Default confidence_threshold is intentionally restrictive (0.99). With
    the current ensemble predictor showing 0% accuracy on level 8, we don't
    want any low-confidence live predictions polluting the map. Anchor
    priors are empirically much better (some anchors >80% top-1 share).
    Raise/lower this once the predictor improves."""
    out: dict = {}
    if occult_predictions:
        for k, p in occult_predictions.items():
            tid = getattr(p, "predicted_tile_id", None)
            conf = getattr(p, "confidence", 0)
            if tid is None and isinstance(p, dict):
                tid = p.get("predicted_tile_id")
                conf = p.get("confidence", 0)
            if tid and conf >= confidence_threshold:
                out[k] = tid
    # Fill in from priors for any anchor we don't already have. We use d2:
    # what's revealed AFTER a tap on the current top-of-stack tile.
    priors = load_anchor_priors(levels_root, level)
    for anchor_key, anchor_data in priors.get("anchors", {}).items():
        try:
            r, c = [int(x) for x in anchor_key.strip("()").split(",")]
        except Exception:
            continue
        key = ("main_board", r, c)
        if key in out:
            continue
        d2 = anchor_data.get("d2", {})
        total = d2.get("total", 0)
        counts = d2.get("tiles", {})
        if total < prior_min_obs or not counts:
            continue
        best = max(counts, key=counts.get)
        share = counts[best] / total
        if share < prior_min_share:
            continue
        out[key] = best
    return out


def summary_string(economies: dict[str, TileEconomy], label_fn=None) -> str:
    """Human-readable rendering for logging."""
    if label_fn is None:
        label_fn = lambda t: t  # noqa: E731
    lines = []
    for tid, e in sorted(economies.items(), key=lambda x: -x[1].observable_total):
        lab = label_fn(tid)
        lines.append(
            f"  {lab:<18} v={e.visible} T={e.in_tray} ?{e.predicted_occult} "
            f"hidden>={e.estimated_hidden_min} full_set={e.full_set_min}"
        )
    return "\n".join(lines)
