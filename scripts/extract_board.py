"""Extract a structured BoardState from a screenshot.

Pipeline:
1. Detect bright tile faces (HSV threshold + contour filtering).
2. Cluster detection centers into row/column grid.
3. Classify each detection as main_board cell or queue head.
4. Crop the tile face center, look up / register in the tile fingerprint library.
5. Output BoardState JSON + an annotated overlay image.

Usage:
    python scripts/extract_board.py data/screenshots/level_05/run_01_t000.jpg
    python scripts/extract_board.py path/to/img.jpg --level 5
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.model.state import BoardState, MainCell, QueueCell
from src.vision.detect import DetectConfig, detect_tile_faces
from src.vision.grid import assign_grid
from src.vision.library import TileLibrary, crop_face_center


def _queue_id_for(cx: int, cy: int, image_w: int, queue_cy_values: list[int]) -> str:
    """Assign a queue head a stable label based on position.

    Side: left if cx < image_w/2, right otherwise.
    Tier: upper or lower based on its cy relative to the queue rows.
    """
    side = "left" if cx < image_w // 2 else "right"
    upper_cy = min(queue_cy_values)
    lower_cy = max(queue_cy_values)
    if upper_cy == lower_cy:
        tier = "upper"
    else:
        tier = "upper" if abs(cy - upper_cy) < abs(cy - lower_cy) else "lower"
    return f"{side}_{tier}"


def _annotate(bgr, main_cells: list[MainCell], queue_cells: list[QueueCell]):
    out = bgr.copy()
    for cell in main_cells:
        x, y, w, h = cell.bbox
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), 3)
        label = f"({cell.row},{cell.col}) {cell.tile_id or '?'}"
        cv2.putText(out, label, (x + 4, y + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)
    for q in queue_cells:
        x, y, w, h = q.bbox
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 200, 255), 3)
        label = f"q:{q.queue_id} {q.tile_id or '?'}"
        cv2.putText(out, label, (x + 4, y + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 2, cv2.LINE_AA)
    return out


@click.command()
@click.argument("image_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--level", type=int, default=None, help="Level number (manual for now)")
@click.option("--out-dir", type=click.Path(path_type=Path), default=None)
@click.option("--tiles-dir", type=click.Path(path_type=Path),
              default=ROOT / "data" / "tiles")
def main(image_path: Path, level: int | None, out_dir: Path | None, tiles_dir: Path) -> None:
    bgr = cv2.imread(str(image_path))
    if bgr is None:
        raise click.ClickException(f"failed to read image: {image_path}")
    h, w = bgr.shape[:2]

    cfg = DetectConfig()
    detections = detect_tile_faces(bgr, cfg)
    grid_assignments = assign_grid(detections)

    library = TileLibrary(tiles_dir)
    image_rel = str(image_path.relative_to(ROOT)) if image_path.is_relative_to(ROOT) else str(image_path)

    # Re-index rows so that within each zone, rows start at 0
    main_rows = sorted({a.row for a in grid_assignments if a.zone == "main_board"})
    main_row_map = {r: i for i, r in enumerate(main_rows)}
    main_cols_set = sorted({a.col for a in grid_assignments if a.zone == "main_board"})
    main_col_map = {c: i for i, c in enumerate(main_cols_set)}

    main_cells: list[MainCell] = []
    queue_cells: list[QueueCell] = []

    queue_cy_values = [detections[a.detection_idx].cy for a in grid_assignments if a.zone == "queue"]

    for a in grid_assignments:
        d = detections[a.detection_idx]
        crop = crop_face_center(bgr, d.x, d.y, d.w, d.h)
        entry, _, _ = library.lookup_or_add(crop, source=image_rel)
        if a.zone == "main_board":
            main_cells.append(MainCell(
                row=main_row_map[a.row],
                col=main_col_map[a.col],
                bbox=(d.x, d.y, d.w, d.h),
                tile_id=entry.tile_id,
            ))
        else:
            qid = _queue_id_for(d.cx, d.cy, w, queue_cy_values)
            queue_cells.append(QueueCell(
                queue_id=qid,
                bbox=(d.x, d.y, d.w, d.h),
                tile_id=entry.tile_id,
            ))

    main_cells.sort(key=lambda c: (c.row, c.col))
    queue_cells.sort(key=lambda q: q.queue_id)

    state = BoardState(
        level=level,
        image=image_rel,
        image_size=(w, h),
        main_board=main_cells,
        queues=queue_cells,
        tray=[],
        boost_counts={"withdraw": 0, "retreat": 0, "refresh": 0},
    )

    if out_dir is None:
        out_dir = ROOT / "data" / "extractions" / image_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    state_path = out_dir / "state.json"
    state.save(state_path)

    overlay = _annotate(bgr, main_cells, queue_cells)
    overlay_path = out_dir / "overlay.jpg"
    cv2.imwrite(str(overlay_path), overlay, [cv2.IMWRITE_JPEG_QUALITY, 85])

    click.echo(f"main_board cells: {len(main_cells)}")
    click.echo(f"queue heads:      {len(queue_cells)}")
    click.echo(f"library entries:  {len(library.entries)}")
    click.echo(f"state:            {state_path}")
    click.echo(f"overlay:          {overlay_path}")


if __name__ == "__main__":
    main()
