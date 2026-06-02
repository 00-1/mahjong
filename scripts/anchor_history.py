"""Per-anchor history: for each anchor in each level, list all observed
(state, tile_id, offset) tuples. Useful for spotting per-anchor patterns
like fixed stack lean directions or recurring tile assignments.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[1]


@click.command()
@click.option("--level", type=int, default=None, help="Filter to a single level")
@click.option("--extractions-dir", type=click.Path(path_type=Path), default=ROOT / "data" / "extractions")
@click.option("--tiles-dir", type=click.Path(path_type=Path), default=ROOT / "data" / "tiles")
def main(level: int | None, extractions_dir: Path, tiles_dir: Path) -> None:
    label_index = {}
    idx_path = tiles_dir / "index.json"
    if idx_path.exists():
        for e in json.loads(idx_path.read_text()).get("entries", []):
            label_index[e["tile_id"]] = e.get("label") or e["tile_id"]

    def lab(tid):
        return label_index.get(tid, tid) if tid else "?"

    # Group states by level
    levels: dict[str, list[dict]] = defaultdict(list)
    for sp in sorted(extractions_dir.glob("**/state.json")):
        s = json.loads(sp.read_text())
        level_dir = sp.parent.parent.name
        screenshot = ROOT / s.get("image", "")
        mtime = screenshot.stat().st_mtime if screenshot.exists() else sp.stat().st_mtime
        levels[level_dir].append({
            "state": s, "stem": sp.parent.name, "mtime": mtime,
        })

    # Load templates per level for canonical anchor positions
    template_anchors: dict[str, dict[tuple, tuple[int, int]]] = {}
    for level_dir in levels:
        lvl_num = int(level_dir.split("_")[1])
        tp = ROOT / "data" / "levels" / f"{lvl_num:02d}" / "template.json"
        if tp.exists():
            t = json.loads(tp.read_text())
            template_anchors[level_dir] = {
                (a["row"], a["col"]): (a["cx"], a["cy"])
                for a in t["anchors"] if a["zone"] == "main_board"
            }

    target_level = f"level_{level:02d}" if level else None
    for level_dir in sorted(levels):
        if target_level and level_dir != target_level:
            continue
        states = sorted(levels[level_dir], key=lambda e: e["mtime"])
        anchors_pos = template_anchors.get(level_dir, {})

        # For each anchor, build observation list
        per_anchor: dict[tuple, list[dict]] = defaultdict(list)
        for entry in states:
            run = entry["stem"].split("_")[1]
            for c in entry["state"]["main_board"]:
                key = (c["row"], c["col"])
                ax, ay = anchors_pos.get(key, (0, 0))
                cx = c["bbox"][0] + c["bbox"][2] // 2
                cy = c["bbox"][1] + c["bbox"][3] // 2
                per_anchor[key].append({
                    "run": run, "stem": entry["stem"],
                    "tile": lab(c["tile_id"]),
                    "depth": c["stack_depth"],
                    "offset": (cx - ax, cy - ay),
                })

        click.echo(f"\n=== {level_dir} ===")
        click.echo(f"  {len(per_anchor)} anchors with observations\n")

        # For each anchor, summarize: distinct tiles seen, distinct offsets seen
        click.echo(f"  {'pos':<7} {'distinct tiles':<14} {'distinct offsets':<16} tiles")
        for key in sorted(per_anchor):
            obs = per_anchor[key]
            tiles = sorted({o["tile"] for o in obs})
            offsets = sorted({o["offset"] for o in obs})
            tile_str = ", ".join(tiles)
            off_str = ", ".join(str(o) for o in offsets)
            click.echo(f"  {str(key):<7} {len(tiles):<14} {len(offsets):<16} {tile_str}")
            click.echo(f"  {'':<7} {'':<14} {'':<16} offsets: {off_str}")


if __name__ == "__main__":
    main()
