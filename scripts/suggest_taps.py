"""Suggest the next tap(s) for a given board state.

Reads an extracted state.json, lists all currently-completable triplets
(sets of 3 visible faces of the same tile), and recommends the cheapest
ones first (fewest new taps needed).

Usage:
    python scripts/suggest_taps.py data/extractions/level_06/run_01_t000/state.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.model.diff import load_state
from src.solver.triplets import find_triplets


@click.command()
@click.argument("state_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--tiles-dir", type=click.Path(path_type=Path), default=ROOT / "data" / "tiles")
def main(state_path: Path, tiles_dir: Path) -> None:
    label_index = {}
    idx_path = tiles_dir / "index.json"
    if idx_path.exists():
        for e in json.loads(idx_path.read_text()).get("entries", []):
            label_index[e["tile_id"]] = e.get("label") or e["tile_id"]

    def lab(tid):
        return label_index.get(tid, tid) if tid else "?"

    state = load_state(state_path)
    candidates = find_triplets(state)

    tray_count = sum(1 for t in state.tray if t.tile_id is not None)
    click.echo(f"Tray: {tray_count}/7 slots filled")
    if tray_count >= 7:
        click.echo("  [!] tray is full — no more taps possible (loss condition).")
        click.echo("      The triplets below would have been reachable but aren't anymore.\n")
    click.echo(f"Found {len(candidates)} completable triplets:\n")
    for c in candidates:
        # If tray full, only triplets that can be completed *purely* from tray
        # (taps_needed == 0) are still actionable. With 7 distinct tray slots
        # this is impossible, but include the flag for completeness.
        unreachable = tray_count >= 7 and c.taps_needed > 0
        flag = "  [!] tray full — UNREACHABLE" if unreachable else ""
        click.echo(f"  3x {lab(c.tile_id)} ({c.taps_needed} taps needed){flag}:")
        for f in c.faces:
            click.echo(f"    - {f.location}")
    if not candidates:
        click.echo("  (none — all visible tiles unique or in counts <3)")


if __name__ == "__main__":
    main()
