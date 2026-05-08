"""Smarter solver recommendation: rank all currently-tappable moves by
expected outcome (triplet completion, tray-fill risk, etc.).

Usage:
    python scripts/recommend.py data/extractions/level_08/run_01_t000/state.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.model.diff import load_state
from src.solver.reactive import suggest_moves


@click.command()
@click.argument("state_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--top", type=int, default=10, help="How many top moves to show")
@click.option("--tiles-dir", type=click.Path(path_type=Path), default=ROOT / "data" / "tiles")
def main(state_path: Path, top: int, tiles_dir: Path) -> None:
    label_index = {}
    idx_path = tiles_dir / "index.json"
    if idx_path.exists():
        for e in json.loads(idx_path.read_text()).get("entries", []):
            label_index[e["tile_id"]] = e.get("label") or e["tile_id"]

    def lab(tid):
        return label_index.get(tid, tid) if tid else "?"

    state = load_state(state_path)
    moves = suggest_moves(state, label_fn=lab)
    tray_filled = sum(1 for t in state.tray if t.tile_id is not None)
    click.echo(f"Tray: {tray_filled}/7 filled. {len(moves)} possible moves.\n")

    click.echo(f"{'rank':<5} {'score':>7}  {'location':<20} {'tile':<18} reason")
    for i, m in enumerate(moves[:top]):
        click.echo(f"{i+1:<5} {m.score:>7.2f}  {m.location:<20} {lab(m.tile_id):<18} {m.reason}")


if __name__ == "__main__":
    main()
