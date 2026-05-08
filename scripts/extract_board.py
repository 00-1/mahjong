"""First-pass board extraction.

Detect bright tile faces in a screenshot, dump:
- a debug overlay image with numbered bboxes
- a JSON file listing every detection (bbox + center + area)

Usage:
    python scripts/extract_board.py data/screenshots/level_05/run_01_t000.jpg
    python scripts/extract_board.py path/to/img.jpg --out-dir data/extractions
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.vision.detect import DetectConfig, detect_tile_faces, draw_overlay, write_mask_debug


@click.command()
@click.argument("image_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out-dir", type=click.Path(path_type=Path), default=None,
              help="Output directory (default: alongside the image, under extractions/)")
@click.option("--mask-debug", is_flag=True, help="Also dump the binary mask for tuning")
def main(image_path: Path, out_dir: Path | None, mask_debug: bool) -> None:
    bgr = cv2.imread(str(image_path))
    if bgr is None:
        raise click.ClickException(f"failed to read image: {image_path}")

    cfg = DetectConfig()
    detections = detect_tile_faces(bgr, cfg)

    if out_dir is None:
        out_dir = ROOT / "data" / "extractions" / image_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    overlay = draw_overlay(bgr, detections)
    overlay_path = out_dir / "overlay.jpg"
    cv2.imwrite(str(overlay_path), overlay, [cv2.IMWRITE_JPEG_QUALITY, 85])

    if mask_debug:
        mask_path = out_dir / "mask.png"
        write_mask_debug(bgr, cfg, str(mask_path))

    detections_json = {
        "image": str(image_path.relative_to(ROOT)) if image_path.is_relative_to(ROOT) else str(image_path),
        "image_size": {"w": bgr.shape[1], "h": bgr.shape[0]},
        "config": cfg.__dict__,
        "count": len(detections),
        "detections": [d.as_dict() for d in detections],
    }
    json_path = out_dir / "detections.json"
    json_path.write_text(json.dumps(detections_json, indent=2))

    click.echo(f"detections: {len(detections)}")
    click.echo(f"overlay:    {overlay_path}")
    click.echo(f"json:       {json_path}")
    if mask_debug:
        click.echo(f"mask:       {out_dir / 'mask.png'}")


if __name__ == "__main__":
    main()
