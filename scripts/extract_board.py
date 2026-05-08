"""Extract a structured BoardState from a screenshot.

Pipeline:
1. Detect bright tile faces (HSV threshold + contour filtering).
2. If a level template exists, snap each detection to the nearest anchor.
   Otherwise, build the template from this screenshot's clustering and save
   it (assumes this image is a clean initial state).
3. Crop each tile face center, look up / register in the tile fingerprint
   library.
4. Output BoardState JSON + an annotated overlay image.

Usage:
    python scripts/extract_board.py data/screenshots/level_05/run_01_t000.jpg --level 5
    python scripts/extract_board.py path/to/img.jpg --level 8
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.model.state import BoardState, MainCell, QueueCell, TraySlot
from src.vision.detect import DetectConfig, detect_tile_faces
from src.vision.library import TileLibrary, crop_face_center
from src.vision.template import build_template, load_template, save_template, scale_template, snap_detections


# Offset magnitudes greater than this px imply the detection is from a depth>=2
# tile (the exposed lower tile of a stack, drawn diagonally offset from the
# top of the stack)
DEPTH_OFFSET_PX = 30


def _annotate(bgr, main_cells, queue_cells, tray_slots, unmatched_dets):
    out = bgr.copy()
    for cell in main_cells:
        x, y, w, h = cell.bbox
        color = (0, 255, 0) if (cell.stack_depth or 1) <= 1 else (0, 200, 255)
        cv2.rectangle(out, (x, y), (x + w, y + h), color, 3)
        depth_str = f"d{cell.stack_depth}" if cell.stack_depth else ""
        label = f"({cell.row},{cell.col}) {cell.tile_id or '?'} {depth_str}"
        cv2.putText(out, label, (x + 4, y + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2, cv2.LINE_AA)
    for q in queue_cells:
        x, y, w, h = q.bbox
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 200, 255), 3)
        cv2.putText(out, f"q:{q.queue_id} {q.tile_id or '?'}", (x + 4, y + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 2, cv2.LINE_AA)
    for t in tray_slots:
        x, y, w, h = t.bbox
        cv2.rectangle(out, (x, y), (x + w, y + h), (255, 200, 0), 3)
        cv2.putText(out, f"t{t.slot} {t.tile_id or '?'}", (x + 4, y + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 2, cv2.LINE_AA)
    for d in unmatched_dets:
        cv2.rectangle(out, (d.x, d.y), (d.x + d.w, d.y + d.h), (0, 0, 255), 3)
        cv2.putText(out, "UNMATCHED", (d.x + 4, d.y + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2, cv2.LINE_AA)
    return out


@click.command()
@click.argument("image_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--level", type=int, required=True, help="Level number (used to find/save template)")
@click.option("--out-dir", type=click.Path(path_type=Path), default=None)
@click.option("--tiles-dir", type=click.Path(path_type=Path), default=ROOT / "data" / "tiles")
@click.option("--rebuild-template", is_flag=True, help="Force rebuild the level template from this screenshot")
def main(image_path: Path, level: int, out_dir: Path | None, tiles_dir: Path, rebuild_template: bool) -> None:
    bgr = cv2.imread(str(image_path))
    if bgr is None:
        raise click.ClickException(f"failed to read image: {image_path}")
    h, w = bgr.shape[:2]

    cfg = DetectConfig()
    detections = detect_tile_faces(bgr, cfg)

    template_path = ROOT / "data" / "levels" / f"{level:02d}" / "template.json"
    template = None if rebuild_template else load_template(template_path)
    if template is None:
        template = build_template(detections, w, h)
        save_template(template, template_path)
        click.echo(f"built template from this image ({len(template.anchors)} anchors)")
    elif (template.image_w, template.image_h) != (w, h):
        click.echo(f"scaling template from {template.image_w}x{template.image_h} to {w}x{h}")
        template = scale_template(template, w, h)

    snap_results, unmatched_idxs = snap_detections(detections, template, w)
    unmatched = [detections[i] for i in unmatched_idxs]

    library = TileLibrary(tiles_dir)
    image_rel = str(image_path.relative_to(ROOT)) if image_path.is_relative_to(ROOT) else str(image_path)

    main_cells: list[MainCell] = []
    queue_cells: list[QueueCell] = []
    tray_slots: list[TraySlot] = []

    for r in snap_results:
        d = detections[r.detection_idx]
        crop = crop_face_center(bgr, d.x, d.y, d.w, d.h)
        entry, _, _ = library.lookup_or_add(crop, source=image_rel)

        if r.anchor.zone == "main_board":
            depth = 1 if (r.offset_x, r.offset_y) == (0, 0) else 2
            main_cells.append(MainCell(
                row=r.anchor.row,
                col=r.anchor.col,
                bbox=(d.x, d.y, d.w, d.h),
                tile_id=entry.tile_id,
                stack_depth=depth,
            ))
        elif r.anchor.zone == "queue":
            queue_cells.append(QueueCell(
                queue_id=r.anchor.queue_id,
                bbox=(d.x, d.y, d.w, d.h),
                tile_id=entry.tile_id,
            ))
        elif r.anchor.zone == "tray":
            tray_slots.append(TraySlot(
                slot=r.anchor.col,
                bbox=(d.x, d.y, d.w, d.h),
                tile_id=entry.tile_id,
            ))

    main_cells.sort(key=lambda c: (c.row, c.col))
    queue_cells.sort(key=lambda q: q.queue_id)
    tray_slots.sort(key=lambda t: t.slot)

    state = BoardState(
        level=level,
        image=image_rel,
        image_size=(w, h),
        main_board=main_cells,
        queues=queue_cells,
        tray=tray_slots,
        boost_counts={"withdraw": 0, "retreat": 0, "refresh": 0},
    )

    if out_dir is None:
        out_dir = ROOT / "data" / "extractions" / image_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    state.save(out_dir / "state.json")
    overlay = _annotate(bgr, main_cells, queue_cells, tray_slots, unmatched)
    cv2.imwrite(str(out_dir / "overlay.jpg"), overlay, [cv2.IMWRITE_JPEG_QUALITY, 85])

    click.echo(f"main_board cells: {len(main_cells)}")
    click.echo(f"queue heads:      {len(queue_cells)}")
    click.echo(f"tray slots:       {len(tray_slots)}")
    click.echo(f"unmatched:        {len(unmatched)}")
    click.echo(f"library entries:  {len(library.entries)}")
    click.echo(f"state:            {out_dir / 'state.json'}")
    click.echo(f"overlay:          {out_dir / 'overlay.jpg'}")


if __name__ == "__main__":
    main()
