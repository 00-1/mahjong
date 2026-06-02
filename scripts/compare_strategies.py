#!/usr/bin/env python3
"""Replay a saved run under multiple solver configs and compare decisions.

Validates strategy improvements without needing live phone access.
Reads the saved t<NNN>.state.json files from a run, runs each through
both greedy + lookahead solvers, reports where they differ.

Usage:
    python scripts/compare_strategies.py <run_id>
    python scripts/compare_strategies.py <run_id> --depth 5
    python scripts/compare_strategies.py --all-lost
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.model.diff import load_state
from src.solver.lookahead import lookahead_recommend
from src.solver.reactive import suggest_moves


def load_labels(tiles_dir: Path) -> dict:
    idx = tiles_dir / "index.json"
    if not idx.exists():
        return {}
    return {
        e["tile_id"]: e.get("label") or e["tile_id"]
        for e in json.loads(idx.read_text()).get("entries", [])
    }


def compare_run(run_dir: Path, depth: int, label_fn) -> dict:
    states = sorted(run_dir.glob("t*.state.json"))
    if not states:
        return {"run_id": run_dir.name, "error": "no states"}

    decisions_greedy = []
    decisions_lookahead = []
    divergences = []

    for sf in states:
        step = int(sf.stem[1:].split(".")[0])
        state = load_state(sf)
        # Greedy: top of suggest_moves
        greedy_moves = suggest_moves(state, label_fn=label_fn)
        if not greedy_moves:
            continue
        greedy_top = greedy_moves[0]
        # Lookahead
        try:
            la = lookahead_recommend(state, depth=depth)
        except Exception as e:
            la = {"best_location": "", "expected_value": float("-inf")}

        greedy_loc = greedy_top.location
        la_loc = la["best_location"]
        same = greedy_loc == la_loc

        decisions_greedy.append({"step": step, "loc": greedy_loc, "score": greedy_top.score})
        decisions_lookahead.append({"step": step, "loc": la_loc, "value": la["expected_value"]})

        if not same:
            divergences.append({
                "step": step,
                "greedy": {"loc": greedy_loc, "tile": label_fn(greedy_top.tile_id),
                           "score": round(greedy_top.score, 2),
                           "reason": greedy_top.reason},
                "lookahead": {"loc": la_loc, "expected_value": round(la["expected_value"], 2),
                              "plan": la.get("plan", []),
                              "triplets_in_plan": la.get("triplets_in_plan", 0)},
            })

    return {
        "run_id": run_dir.name,
        "level": json.loads((run_dir / "meta.json").read_text())["level"]
                  if (run_dir / "meta.json").exists() else None,
        "states_processed": len(decisions_greedy),
        "divergences_count": len(divergences),
        "divergences": divergences,
        "outcome": json.loads((run_dir / "outcome.json").read_text()).get("status")
                   if (run_dir / "outcome.json").exists() else None,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run_id", nargs="?", default=None)
    p.add_argument("--all", action="store_true")
    p.add_argument("--all-lost", action="store_true",
                   help="Process all 'lost' runs (per outcome heuristic)")
    p.add_argument("--depth", type=int, default=3)
    p.add_argument("--runs-dir", type=Path, default=ROOT / "data" / "runs")
    p.add_argument("--tiles-dir", type=Path, default=ROOT / "data" / "tiles")
    p.add_argument("--summary-only", action="store_true",
                   help="Print only divergence count + first divergence per run")
    args = p.parse_args()

    label_index = load_labels(args.tiles_dir)
    label_fn = lambda t: label_index.get(t, t) if t else "?"  # noqa: E731

    if args.run_id:
        targets = [args.runs_dir / args.run_id]
    elif args.all_lost:
        targets = []
        for d in sorted(args.runs_dir.iterdir() if args.runs_dir.exists() else []):
            if not d.is_dir():
                continue
            outcome_path = d / "outcome.json"
            if not outcome_path.exists():
                continue
            outcome = json.loads(outcome_path.read_text())
            if outcome.get("status") in ("lost", "abandoned"):
                targets.append(d)
    else:
        targets = [d for d in sorted(args.runs_dir.iterdir() if args.runs_dir.exists() else []) if d.is_dir()]

    aggregate = {"runs": 0, "total_states": 0, "total_divergences": 0}
    for rd in targets:
        if not rd.is_dir():
            continue
        result = compare_run(rd, args.depth, label_fn)
        if "error" in result:
            continue
        aggregate["runs"] += 1
        aggregate["total_states"] += result["states_processed"]
        aggregate["total_divergences"] += result["divergences_count"]

        if args.summary_only:
            first_div = result["divergences"][0] if result["divergences"] else None
            print(json.dumps({
                "run_id": result["run_id"],
                "level": result.get("level"),
                "outcome": result.get("outcome"),
                "states": result["states_processed"],
                "divergences": result["divergences_count"],
                "first_divergence": first_div,
            }, default=str))
        else:
            print(json.dumps(result, indent=2, default=str))

    if aggregate["runs"] > 1:
        print()
        print(json.dumps({"summary": aggregate,
                          "divergence_rate": aggregate["total_divergences"] / max(1, aggregate["total_states"])}))


if __name__ == "__main__":
    main()
