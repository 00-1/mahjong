#!/usr/bin/env python3
"""Build per-level tile inventory from accumulated run data.

For each level directory we find under data/runs/ (matching
`run_*_l<NN>`), aggregate the maximum number of unique
(anchor, depth) instances + queue observations of each tile_id
across runs that played long enough to be informative
(>= --min-states states). Round up to the nearest multiple of 3
to get the inferred true count.

Output: data/levels/<NN>/inventory.json — consumed by the solver's
state_value (dead-tray detection) and by the determinization
sampler when we have one.

Usage:
    python scripts/build_inventory.py --level 8
    python scripts/build_inventory.py --all
    python scripts/build_inventory.py --level 8 --min-states 5 --verbose
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def collect_run_inventory(run_dir: Path) -> tuple[Counter, int]:
    """For one run, return (per-tile-id max instance count, n_states)."""
    states = sorted(run_dir.glob("t*.state.json"))
    if not states:
        return Counter(), 0
    # Per-anchor unique (depth, tile_id) tuples seen anywhere in the run.
    # Each unique (depth, tile_id) at an anchor = 1 physical tile.
    anchor_obs: dict[tuple[int, int], set[tuple[int, str]]] = defaultdict(set)
    queue_obs: dict[str, set[str]] = defaultdict(set)
    for sf in states:
        try:
            s = json.loads(sf.read_text())
        except Exception:
            continue
        for c in s.get("main_board", []):
            tid = c.get("tile_id")
            if tid:
                depth = c.get("stack_depth") or 1
                anchor_obs[(c["row"], c["col"])].add((depth, tid))
        for q in s.get("queues", []):
            tid = q.get("tile_id")
            if tid:
                queue_obs[q["queue_id"]].add(tid)
    inventory: Counter = Counter()
    for obs in anchor_obs.values():
        for _, tid in obs:
            inventory[tid] += 1
    for obs in queue_obs.values():
        for tid in obs:
            inventory[tid] += 1
    return inventory, len(states)


def build_level_inventory(
    level: int,
    runs_dir: Path,
    min_states: int = 5,
    verbose: bool = False,
) -> dict:
    """Aggregate across runs of one level. Returns inventory dict ready to
    be written to data/levels/<NN>/inventory.json."""
    pat = re.compile(rf"^run_[\d_]+_l{level:02d}$")
    runs_used: list[str] = []
    runs_skipped: list[tuple[str, int]] = []
    per_tile_max: Counter = Counter()
    total_inv_per_run: list[int] = []
    for rd in sorted(runs_dir.iterdir()):
        if not rd.is_dir() or not pat.match(rd.name):
            continue
        inv, n = collect_run_inventory(rd)
        if n < min_states:
            runs_skipped.append((rd.name, n))
            continue
        runs_used.append(rd.name)
        total_inv_per_run.append(sum(inv.values()))
        for tid, cnt in inv.items():
            if cnt > per_tile_max[tid]:
                per_tile_max[tid] = cnt

    tiles: dict[str, dict] = {}
    for tid, max_cnt in per_tile_max.items():
        # Round up to nearest multiple of 3 (every triplet clears 3).
        inferred = max(3, 3 * math.ceil(max_cnt / 3))
        # Confidence: 6+ instances unambiguous. 4-5 needs more data
        # (could be a 6-instance tile we haven't fully seen). 1-3
        # might be 3 or 6 still. 1-2 is most uncertain.
        if max_cnt >= 6:
            confidence = "confirmed"
        elif max_cnt >= 4:
            confidence = "high"      # max 4-5 -> probably 6
        elif max_cnt == 3:
            confidence = "medium"    # plateau exactly at 3 — likely 3 but could be 6
        else:
            confidence = "low"
        tiles[tid] = {
            "count": inferred,
            "max_observed": max_cnt,
            "confidence": confidence,
        }

    out = {
        "level": level,
        "runs_used": runs_used,
        "runs_skipped": [{"name": n, "states": s} for n, s in runs_skipped],
        "min_states_threshold": min_states,
        "estimated_total_tiles": sum(t["count"] for t in tiles.values()),
        "tiles": tiles,
    }

    if verbose:
        print(f"\nLevel {level}: {len(runs_used)} runs used, "
              f"{len(runs_skipped)} skipped (< {min_states} states)")
        print(f"  Estimated total tiles: {out['estimated_total_tiles']}")
        for tid in sorted(tiles, key=lambda t: -tiles[t]["count"]):
            t = tiles[tid]
            print(f"  {tid:10s} count={t['count']:>2d} "
                  f"max_obs={t['max_observed']:>2d} "
                  f"({t['confidence']})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--level", type=int, action="append",
                    help="Level to build inventory for. Repeat or use --all.")
    ap.add_argument("--all", action="store_true",
                    help="Build inventory for every level with run data.")
    ap.add_argument("--runs-dir", type=Path, default=ROOT / "data" / "runs")
    ap.add_argument("--levels-root", type=Path, default=ROOT / "data" / "levels")
    ap.add_argument("--min-states", type=int, default=5,
                    help="Skip runs with fewer states (likely abandoned/exception). "
                         "Default 5.")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print without writing inventory.json")
    args = ap.parse_args()

    levels: list[int] = []
    if args.all:
        seen = set()
        for rd in args.runs_dir.iterdir() if args.runs_dir.exists() else []:
            m = re.match(r"^run_[\d_]+_l(\d{2})$", rd.name)
            if m:
                seen.add(int(m.group(1)))
        levels = sorted(seen)
    elif args.level:
        levels = args.level
    else:
        ap.error("specify --level NN or --all")
        return 2

    for level in levels:
        out = build_level_inventory(
            level, args.runs_dir, args.min_states, args.verbose,
        )
        target = args.levels_root / f"{level:02d}" / "inventory.json"
        if args.dry_run:
            print(json.dumps(out, indent=2))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(out, indent=2))
        print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
