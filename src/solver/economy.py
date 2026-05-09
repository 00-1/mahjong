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


def _compute_remaining_pool(
    state: dict,
    inventory: dict | None,
    cleared_history: dict | None,
) -> dict[str, int]:
    """How many copies of each tile_id remain unaccounted-for —
    i.e. could plausibly be hiding at d2 of some anchor.

    remaining[tid] = inventory[tid] - cleared - visible_main - visible_queue - tray

    Without an inventory, returns an empty dict (caller should fall
    back to unconditioned priors).
    """
    if not inventory or not inventory.get("tiles"):
        return {}
    remaining: dict[str, int] = {
        tid: int(info.get("count", 3))
        for tid, info in inventory["tiles"].items()
    }
    for c in state.get("main_board", []):
        tid = c.get("tile_id")
        if tid in remaining:
            remaining[tid] = max(0, remaining[tid] - 1)
    for q in state.get("queues", []):
        tid = q.get("tile_id")
        if tid in remaining:
            remaining[tid] = max(0, remaining[tid] - 1)
    for t in state.get("tray", []):
        tid = t.get("tile_id")
        if tid in remaining:
            remaining[tid] = max(0, remaining[tid] - 1)
    for tid, n in (cleared_history or {}).items():
        if tid in remaining:
            remaining[tid] = max(0, remaining[tid] - n)
    return remaining


def bayesian_reveal_posterior(
    state: dict,
    anchor_priors: dict,
    inventory: dict | None,
    cleared_history: dict | None = None,
    target_depth: int = 2,
) -> dict[tuple, dict[str, float]]:
    """Posterior over what tile is at each anchor's `target_depth`,
    conditioned on visible state + cleared history + level inventory.

    Math:
        P(d2 = tid | anchor=A, observations)
            ∝ P_prior(d2 = tid | A) * remaining(tid)
        with normalization over tids consistent with remaining > 0.

    Where:
        P_prior comes from `data/levels/<NN>/anchor_priors.json` d2.
        remaining(tid) = inventory.count - cleared - visible - tray.

    This replaces the 0%-accuracy 4-method visual ensemble. It's
    closed-form, deterministic, computes in <50ms for a typical
    level. Returns posterior distributions per anchor; callers can
    take the MAP estimate or sample.

    Returns: {("main_board", r, c) | ("queue", qid): {tile_id: prob, ...}}
    """
    remaining = _compute_remaining_pool(state, inventory, cleared_history)
    posteriors: dict[tuple, dict[str, float]] = {}
    for anchor_key, anchor_data in anchor_priors.get("anchors", {}).items():
        try:
            r, c = [int(x) for x in anchor_key.strip("()").split(",")]
        except (ValueError, AttributeError):
            continue
        depth_data = anchor_data.get(f"d{target_depth}", {})
        total = depth_data.get("total", 0)
        if total == 0:
            continue
        counts = depth_data.get("tiles", {})
        if not counts:
            continue
        # Compute unnormalized posterior. If inventory is absent we
        # fall back to the prior (remaining acts as a uniform multiplier
        # which cancels in normalization).
        scored: dict[str, float] = {}
        for tid, n in counts.items():
            prior = n / total
            if remaining:
                r_count = remaining.get(tid, 0)
                if r_count <= 0:
                    continue  # tile is exhausted — eliminate
                scored[tid] = prior * r_count
            else:
                scored[tid] = prior
        norm = sum(scored.values())
        if norm <= 0:
            continue
        posteriors[("main_board", r, c)] = {
            tid: p / norm for tid, p in scored.items()
        }
    return posteriors


def verify_bayesian_predictions(
    predictions: dict[tuple, str],
    new_state: dict,
) -> list[dict]:
    """Compare last step's MAP estimates to the now-revealed bright
    tiles in new_state. Returns one comparison per anchor that was
    predicted AND is now visible. Used for accuracy tracking.

    Output entries match the schema of verify_anchor_predictions
    (occult.py) so they can flow through the same downstream
    aggregators."""
    main_lookup = {
        ("main_board", c["row"], c["col"]): c.get("tile_id")
        for c in new_state.get("main_board", [])
    }
    queue_lookup = {
        ("queue", q["queue_id"]): q.get("tile_id")
        for q in new_state.get("queues", [])
    }
    full_lookup = {**main_lookup, **queue_lookup}
    out: list[dict] = []
    for key, predicted_tid in predictions.items():
        actual = full_lookup.get(key)
        if actual is None:
            continue
        out.append({
            "anchor_key": list(key),
            "predicted_tile_id": predicted_tid,
            "actual_tile_id": actual,
            "correct": predicted_tid == actual,
            "method": "bayesian",
        })
    return out


def aggregate_bayesian_accuracy(
    levels_root: Path,
    level: int,
    comparisons: list[dict],
) -> None:
    """Roll up Bayesian-predictor accuracy into
    data/levels/<NN>/bayesian_accuracy.json. Mirrors
    occult_accuracy.json's schema for direct comparison."""
    p = levels_root / f"{level:02d}" / "bayesian_accuracy.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        data = json.loads(p.read_text())
    else:
        data = {
            "level": level, "total": 0, "correct": 0,
            "by_predicted": {}, "by_actual": {},
            "confusion": {},
        }
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
            confkey = f"{c['predicted_tile_id']}->{c['actual_tile_id']}"
            data["confusion"][confkey] = data["confusion"].get(confkey, 0) + 1
    data["accuracy"] = data["correct"] / data["total"] if data["total"] else 0.0
    p.write_text(json.dumps(data, indent=2))


def map_estimates(
    posteriors: dict[tuple, dict[str, float]],
    min_confidence: float = 0.4,
) -> dict[tuple, str]:
    """Reduce per-anchor posterior distributions to a single MAP
    estimate per anchor, suppressing low-confidence anchors.

    min_confidence: only emit a prediction if the top tile's
    posterior probability is at least this. Tunable; 0.4 means we
    only act on a prediction when there's at least 40% certainty.
    """
    out: dict[tuple, str] = {}
    for key, dist in posteriors.items():
        if not dist:
            continue
        best_tid = max(dist, key=dist.get)
        if dist[best_tid] >= min_confidence:
            out[key] = best_tid
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
