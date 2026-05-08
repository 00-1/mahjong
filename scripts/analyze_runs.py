"""Cross-run analysis: aggregate all observed (anchor, tile, depth, offset)
tuples across every extracted state, and surface any per-anchor patterns
that hold across runs.

Tests several hypotheses:
- Tile-on-position fixed across runs
- Depth-2 tile fixed per anchor across runs (user's "later layers preset" idea)
- Stack lean direction fixed per anchor across runs
- Stack depth (how deep) fixed per anchor across runs
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[1]


@click.command()
@click.option("--extractions-dir", type=click.Path(path_type=Path), default=ROOT / "data" / "extractions")
@click.option("--tiles-dir", type=click.Path(path_type=Path), default=ROOT / "data" / "tiles")
def main(extractions_dir: Path, tiles_dir: Path) -> None:
    label_index = {}
    idx_path = tiles_dir / "index.json"
    if idx_path.exists():
        for e in json.loads(idx_path.read_text()).get("entries", []):
            if e.get("label"):
                label_index[e["tile_id"]] = e["label"]

    def lab(tid):
        return label_index.get(tid, tid) if tid else "?"

    # Group state files by run (run_NN_*). Sort by file mtime so within-run
    # observations are chronological (revealing depth-2 before depth-3).
    states = []
    for sp in sorted(extractions_dir.glob("*/state.json")):
        s = json.loads(sp.read_text())
        stem = sp.parent.name
        run = stem.split("_")[1] if stem.startswith("run_") else "?"
        # Use the source screenshot's mtime if available, else state.json's
        screenshot = ROOT / s.get("image", "")
        mtime = screenshot.stat().st_mtime if screenshot.exists() else sp.stat().st_mtime
        states.append({"stem": stem, "run": run, "state": s, "mtime": mtime})
    states.sort(key=lambda e: (e["run"], e["mtime"]))

    # For each anchor, collect observations across states.
    # observation = (run, stem, tile_label, depth_marker, offset, source_state_idx)
    obs_by_anchor: dict[tuple, list[dict]] = defaultdict(list)
    for entry in states:
        s = entry["state"]
        for c in s["main_board"]:
            key = (c["row"], c["col"])
            x, y, w, h = c["bbox"]
            cx, cy = x + w // 2, y + h // 2
            obs_by_anchor[key].append({
                "run": entry["run"],
                "stem": entry["stem"],
                "tile": lab(c["tile_id"]),
                "depth": c["stack_depth"],
                "cx": cx, "cy": cy,
            })

    # Print per-anchor history
    click.echo(f"{'anchor':<7} | {'state':<22} | {'tile':<18} {'d':<3} | {'cx':<5} {'cy':<5}")
    click.echo("-" * 80)
    for key in sorted(obs_by_anchor):
        for obs in sorted(obs_by_anchor[key], key=lambda o: (o["run"], o["stem"])):
            click.echo(f"{str(key):<7} | {obs['stem']:<22} | {obs['tile']:<18} {obs['depth']!s:<3} | {obs['cx']:<5} {obs['cy']:<5}")
        click.echo("")

    # Hypothesis tests
    click.echo("\n=== Hypothesis tests ===\n")

    # Group observations by run for each anchor
    runs_seen = sorted({e["run"] for e in states})
    click.echo(f"Runs in dataset: {runs_seen}")

    # Test 1: Top tile per run (do runs have the same initial top tile?)
    click.echo("\n--- Test 1: Initial-state top tile per anchor across runs ---")
    initial_states_by_run = {}
    for entry in states:
        if entry["stem"].endswith("t000"):
            initial_states_by_run[entry["run"]] = entry["state"]
    if len(initial_states_by_run) >= 2:
        all_anchors = set()
        for s in initial_states_by_run.values():
            for c in s["main_board"]:
                all_anchors.add((c["row"], c["col"]))
        same_count = 0
        diff_count = 0
        for anchor in sorted(all_anchors):
            tiles_per_run = {}
            for run, s in initial_states_by_run.items():
                for c in s["main_board"]:
                    if (c["row"], c["col"]) == anchor:
                        tiles_per_run[run] = lab(c["tile_id"])
            if len(set(tiles_per_run.values())) == 1:
                same_count += 1
            else:
                diff_count += 1
        click.echo(f"  {same_count} same, {diff_count} different across runs")

    # Test 2: Depth-2 reveal per anchor across runs (chronologically first
    # depth>=2 observation per run is the depth-2 tile)
    click.echo("\n--- Test 2: Depth-2 tile per anchor across runs ---")
    d2_by_anchor_run: dict[tuple, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for entry in states:
        for c in entry["state"]["main_board"]:
            if c.get("stack_depth", 1) >= 2:
                d2_by_anchor_run[(c["row"], c["col"])][entry["run"]].append(lab(c["tile_id"]))

    same_count = 0
    diff_count = 0
    for anchor in sorted(d2_by_anchor_run):
        per_run = d2_by_anchor_run[anchor]
        if len(per_run) < 2:
            continue
        # First observation per run = depth-2 (since states sorted by mtime).
        # Later observations in same run might be depth-3, 4, etc.
        first_per_run = {run: tiles[0] for run, tiles in per_run.items()}
        if len(set(first_per_run.values())) == 1:
            click.echo(f"  {anchor}: SAME ({first_per_run})")
            same_count += 1
        else:
            click.echo(f"  {anchor}: DIFF ({first_per_run})")
            diff_count += 1
    click.echo(f"  -> {same_count} same, {diff_count} different at depth-2 across runs")

    # Test 3: Stack lean direction per anchor across runs (the offset signature
    # of the depth-2 reveal). A fixed lean direction would also support the
    # "structural priors" idea even if the tile identity is random.
    click.echo("\n--- Test 3: Depth-2 lean direction per anchor across runs ---")
    leans_by_anchor: dict[tuple, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for entry in states:
        for c in entry["state"]["main_board"]:
            if c.get("stack_depth", 1) < 2:
                continue
            x, y, w, h = c["bbox"]
            cx, cy = x + w // 2, y + h // 2
            anchor_key = (c["row"], c["col"])
            # Compute offset from canonical anchor (use the first state's d=1 cx/cy
            # for that anchor as the canonical position)
            leans_by_anchor[anchor_key][entry["run"]].add((cx, cy))

    # For comparison we need the canonical anchor positions. Pull from any d=1 obs.
    canonical_anchor: dict[tuple, tuple[int, int]] = {}
    for entry in states:
        for c in entry["state"]["main_board"]:
            if c.get("stack_depth", 1) == 1:
                key = (c["row"], c["col"])
                if key not in canonical_anchor:
                    x, y, w, h = c["bbox"]
                    canonical_anchor[key] = (x + w // 2, y + h // 2)

    same_count = 0
    diff_count = 0
    for anchor in sorted(leans_by_anchor):
        if anchor not in canonical_anchor:
            continue
        ax, ay = canonical_anchor[anchor]
        per_run = leans_by_anchor[anchor]
        if len(per_run) < 2:
            continue
        leans_per_run = {}
        for run, positions in per_run.items():
            # Take the smallest-offset position (most likely depth-2 reveal)
            best = min(positions, key=lambda p: (p[0]-ax)**2 + (p[1]-ay)**2)
            leans_per_run[run] = (best[0]-ax, best[1]-ay)
        if len(set(leans_per_run.values())) == 1:
            click.echo(f"  {anchor}: SAME ({leans_per_run})")
            same_count += 1
        else:
            click.echo(f"  {anchor}: DIFF ({leans_per_run})")
            diff_count += 1
    click.echo(f"  -> {same_count} same, {diff_count} different lean across runs")


if __name__ == "__main__":
    main()
