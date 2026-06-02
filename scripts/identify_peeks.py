"""For each detected top tile in a state, try to identify what's peeking
out at each surrounding offset position.

Usage:
    python scripts/identify_peeks.py data/screenshots/level_07/run_01_t000.jpg --level 7
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.vision.detect import DetectConfig, detect_tile_faces
from src.vision.peek import identify_peeks_at_anchor, load_library_samples
from src.vision.template import load_template, scale_template, snap_detections


@click.command()
@click.argument("image_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--level", type=int, required=True)
@click.option("--tiles-dir", type=click.Path(path_type=Path), default=ROOT / "data" / "tiles")
@click.option("--score-threshold", type=float, default=0.30,
              help="Max SQDIFF normalized score to accept (lower = stricter)")
def main(image_path: Path, level: int, tiles_dir: Path, score_threshold: float) -> None:
    bgr = cv2.imread(str(image_path))
    if bgr is None:
        raise click.ClickException(f"failed to read {image_path}")
    h, w = bgr.shape[:2]

    cfg = DetectConfig()
    detections = detect_tile_faces(bgr, cfg)

    template_path = ROOT / "data" / "levels" / f"{level:02d}" / "template.json"
    template = load_template(template_path)
    if template is None:
        raise click.ClickException(f"no template for level {level}")
    if (template.image_w, template.image_h) != (w, h):
        template = scale_template(template, w, h)

    snap_results, _ = snap_detections(detections, template, w)

    label_index = {}
    idx_path = tiles_dir / "index.json"
    if idx_path.exists():
        for e in json.loads(idx_path.read_text()).get("entries", []):
            label_index[e["tile_id"]] = e.get("label") or e["tile_id"]

    def lab(tid):
        return label_index.get(tid, tid) if tid else "?"

    library_samples = load_library_samples(tiles_dir)
    click.echo(f"Library has {len(library_samples)} tile samples; trying peek matches...")
    click.echo()

    for r in snap_results:
        if r.anchor.zone != "main_board":
            continue
        d = detections[r.detection_idx]
        peeks = identify_peeks_at_anchor(
            bgr, d.cx, d.cy, template.tile_w, template.tile_h,
            library_samples, score_threshold=score_threshold,
        )
        if not peeks:
            continue
        click.echo(f"({r.anchor.row},{r.anchor.col}) top-tile cx={d.cx} cy={d.cy}:")
        for p in peeks:
            click.echo(f"  offset {p.offset}  ->  {lab(p.tile_id)}  "
                       f"(score {p.score:.4f}, visible {p.sliver_frac:.0%})")


if __name__ == "__main__":
    main()
