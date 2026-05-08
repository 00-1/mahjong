"""Detect AND identify ALL tiles in a screenshot — bright top tiles plus
dim non-selectable tiles. For each, identify which tile art it shows and
mark whether it's currently selectable.

Usage:
    python scripts/identify_all.py data/screenshots/level_07/run_01_t000.jpg --level 7
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.vision.all_tiles import detect_all_tiles, identify_combined
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

    detections = detect_all_tiles(bgr)
    library_samples = load_library_samples(tiles_dir)

    label_index = {}
    idx_path = tiles_dir / "index.json"
    if idx_path.exists():
        for e in json.loads(idx_path.read_text()).get("entries", []):
            label_index[e["tile_id"]] = e.get("label") or e["tile_id"]

    def lab(tid):
        return label_index.get(tid, tid) if tid else "?"

    bright_count = sum(1 for d in detections if d.is_bright)
    dim_count = len(detections) - bright_count
    click.echo(f"Detected {len(detections)} tiles ({bright_count} bright, {dim_count} dim)")
    click.echo()

    overlay = bgr.copy()
    for d in detections:
        crop = bgr[d.y:d.y + d.h, d.x:d.x + d.w]
        tile_id, score, all_scores = identify_combined(crop, library_samples, is_bright=d.is_bright)
        sorted_scores = sorted(all_scores.values())
        runner_up = sorted_scores[1] if len(sorted_scores) > 1 else float("inf")
        confidence = (runner_up - score) / max(0.001, runner_up + score)

        kind = "BRIGHT" if d.is_bright else "dim   "
        click.echo(f"  {kind} ({d.cx:>4},{d.cy:>4}) -> {lab(tile_id):<18} "
                   f"score={score:.3f} conf={confidence:.2f}")

        color = (0, 255, 0) if d.is_bright else (0, 200, 255)
        cv2.rectangle(overlay, (d.x, d.y), (d.x + d.w, d.y + d.h), color, 3)
        text = f"{lab(tile_id)[:10]} {score:.2f}"
        cv2.putText(overlay, text, (d.x + 4, d.y + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    color, 2, cv2.LINE_AA)

    if out_overlay is None:
        out_overlay = (
            ROOT / "data" / "extractions" / f"level_{level:02d}"
            / image_path.stem / "all_tiles_overlay.jpg"
        )
    out_overlay.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_overlay), overlay, [cv2.IMWRITE_JPEG_QUALITY, 85])
    click.echo(f"\noverlay -> {out_overlay}")


if __name__ == "__main__":
    main()
