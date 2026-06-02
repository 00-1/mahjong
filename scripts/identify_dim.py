"""Detect AND identify dim/non-selectable tiles in a screenshot.

Bright tiles are detected by the standard pipeline. Dim tiles (non-selectable
because they're blocked by neighbors or under another tile) render at lower
brightness and are missed by the bright detector. This script catches them
and identifies each by HSV color histogram match against the library.

Usage:
    python scripts/identify_dim.py data/screenshots/level_07/run_01_t000.jpg --level 7
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
from src.vision.dim import detect_dim_tiles, identify_dim_tile
from src.vision.peek import load_library_samples


@click.command()
@click.argument("image_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--level", type=int, required=True)
@click.option("--tiles-dir", type=click.Path(path_type=Path), default=ROOT / "data" / "tiles")
@click.option("--out-overlay", type=click.Path(path_type=Path), default=None)
def main(image_path: Path, level: int, tiles_dir: Path, out_overlay: Path | None) -> None:
    bgr = cv2.imread(str(image_path))
    if bgr is None:
        raise click.ClickException(f"failed to read {image_path}")

    cfg = DetectConfig()
    bright = detect_tile_faces(bgr, cfg)
    dim = detect_dim_tiles(bgr, bright)

    label_index = {}
    idx_path = tiles_dir / "index.json"
    if idx_path.exists():
        for e in json.loads(idx_path.read_text()).get("entries", []):
            label_index[e["tile_id"]] = e.get("label") or e["tile_id"]

    def lab(tid):
        return label_index.get(tid, tid) if tid else "?"

    library_samples = load_library_samples(tiles_dir)

    click.echo(f"Bright tiles: {len(bright)}")
    click.echo(f"Dim tiles:    {len(dim)}")
    click.echo()

    overlay = bgr.copy()
    for d in bright:
        cv2.rectangle(overlay, (d.x, d.y), (d.x + d.w, d.y + d.h), (0, 255, 0), 3)

    for i, dt in enumerate(dim):
        tile_id, score = identify_dim_tile(bgr, dt, library_samples)
        label = lab(tile_id)
        click.echo(f"  dim @ ({dt.cx},{dt.cy})  -> {label:<18} score={score:.2f}")
        cv2.rectangle(overlay, (dt.x, dt.y), (dt.x + dt.w, dt.y + dt.h), (0, 0, 255), 3)
        cv2.putText(overlay, f"{label[:10]} {score:.1f}",
                    (dt.x + 4, dt.y + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2, cv2.LINE_AA)

    if out_overlay is None:
        out_overlay = ROOT / "data" / "extractions" / f"level_{level:02d}" / image_path.stem / "dim_overlay.jpg"
    out_overlay.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_overlay), overlay, [cv2.IMWRITE_JPEG_QUALITY, 85])
    click.echo(f"\noverlay -> {out_overlay}")


if __name__ == "__main__":
    main()
