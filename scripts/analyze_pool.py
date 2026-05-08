"""Per-level tile-pool analysis.

For each level, aggregate every observed (anchor or tray-slot or queue-head)
across every extracted state, count tile occurrences, and report the pool
distribution. Tests whether per-level tile counts are stable across runs
(a useful structural prior — if every run of level N has exactly K of each
tile, we can compute remaining tile counts during play).

Outputs:
- top-layer initial-state tile counts per run (compares run-to-run)
- cumulative observed tile counts per level (lower bound on level total)
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
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
            label_index[e["tile_id"]] = e.get("label") or e["tile_id"]

    def lab(tid):
        return label_index.get(tid, tid) if tid else "?"

    # Collect states by level + run
    levels: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for sp in sorted(extractions_dir.glob("**/state.json")):
        s = json.loads(sp.read_text())
        level = sp.parent.parent.name
        run = sp.parent.name.split("_")[1] if sp.parent.name.startswith("run_") else "?"
        screenshot = ROOT / s.get("image", "")
        mtime = screenshot.stat().st_mtime if screenshot.exists() else sp.stat().st_mtime
        levels[level][run].append({"state": s, "stem": sp.parent.name, "mtime": mtime})
    # Sort runs' states by mtime
    for runs in levels.values():
        for states in runs.values():
            states.sort(key=lambda e: e["mtime"])

    for level in sorted(levels):
        click.echo(f"\n=== {level} ===")
        runs = levels[level]

        # Initial-state top-layer counts per run
        click.echo(f"\n  -- initial-state top tile counts per run --")
        initial_counts: dict[str, Counter] = {}
        for run, states in sorted(runs.items()):
            initial = next((e for e in states if "t000" in e["stem"]), None)
            if not initial:
                continue
            s = initial["state"]
            c = Counter()
            for cell in s["main_board"]:
                c[lab(cell["tile_id"])] += 1
            for q in s["queues"]:
                c[lab(q["tile_id"])] += 1
            initial_counts[run] = c

        all_tiles_seen = set()
        for c in initial_counts.values():
            all_tiles_seen.update(c.keys())

        runs_list = sorted(initial_counts.keys())
        header = f"{'tile':<18}" + "".join(f"  run {r:<3}" for r in runs_list) + "  diff?"
        click.echo("  " + header)
        all_same = True
        for tile in sorted(all_tiles_seen):
            cells = "".join(f"  {initial_counts[r].get(tile, 0):<5}" for r in runs_list)
            counts = {initial_counts[r].get(tile, 0) for r in runs_list}
            same = "same" if len(counts) == 1 else "DIFF"
            if len(counts) > 1:
                all_same = False
            click.echo(f"  {tile:<18}{cells}  {same}")
        click.echo(f"  -> initial top-layer counts {'IDENTICAL' if all_same else 'differ'} across runs")

        # Cumulative observed counts (any tile ever observed at any anchor across any state)
        click.echo(f"\n  -- cumulative tile observations across all states --")
        cum = Counter()
        seen_per_anchor = defaultdict(set)  # (zone, row/qid, col) -> set of tile labels seen
        for run, states in runs.items():
            for entry in states:
                s = entry["state"]
                for cell in s["main_board"]:
                    seen_per_anchor[("main", cell["row"], cell["col"])].add(lab(cell["tile_id"]))
                for q in s["queues"]:
                    seen_per_anchor[("queue", q["queue_id"])].add(lab(q["tile_id"]))
                for t in s["tray"]:
                    cum[lab(t["tile_id"])] += 1
        # Sum unique tiles ever seen at each anchor (lower bound on stack depth + width)
        anchor_seen_total = Counter()
        for tiles in seen_per_anchor.values():
            for t in tiles:
                anchor_seen_total[t] += 1

        click.echo(f"  {'tile':<18} {'unique anchors':<14} {'tray seen':<10}")
        for tile in sorted(anchor_seen_total | cum):
            click.echo(f"  {tile:<18} {anchor_seen_total.get(tile, 0):<14} {cum.get(tile, 0):<10}")


if __name__ == "__main__":
    main()
