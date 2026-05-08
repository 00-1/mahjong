"""Diff two extracted board states and print the inferred tap sequence.

Usage:
    python scripts/diff_states.py data/extractions/run_01_t000/state.json data/extractions/run_01_t009/state.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.model.diff import diff_states, load_state, summarize_diff


@click.command()
@click.argument("state_a", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("state_b", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--tiles-dir", type=click.Path(path_type=Path), default=ROOT / "data" / "tiles")
def main(state_a: Path, state_b: Path, tiles_dir: Path) -> None:
    a = load_state(state_a)
    b = load_state(state_b)

    label_index = {}
    idx_path = tiles_dir / "index.json"
    if idx_path.exists():
        for e in json.loads(idx_path.read_text()).get("entries", []):
            if e.get("label"):
                label_index[e["tile_id"]] = e["label"]

    def lab(tid):
        return label_index.get(tid, tid) if tid else "?"

    events = diff_states(a, b)
    summary = summarize_diff(events)

    click.echo(f"Diff: {state_a.name} -> {state_b.name}")
    click.echo(f"  {len(events)} tap events; {len(summary.triplets)} complete triplets; {len(summary.orphans)} orphans")
    click.echo()

    for tile_id, evs in sorted(summary.triplets):
        click.echo(f"Triplet: 3x {lab(tile_id)}")
        for ev in evs:
            extra = f" -> revealed {lab(ev.revealed)}" if ev.revealed else ""
            click.echo(f"  - {ev.kind} at {ev.location}{extra}")
        click.echo()

    if summary.orphans:
        click.echo("Orphan events (not part of a complete triplet — partial diff?):")
        for ev in summary.orphans:
            click.echo(f"  - {lab(ev.tile_id)} {ev.kind} at {ev.location}")


if __name__ == "__main__":
    main()
