"""Main solver UI: take a screenshot, recommend the best next tap.

Usage:
    python scripts/play.py screenshot.jpg --level 8

Pipeline:
1. Extract bright top tiles + identify each
2. Identify dim/partial tiles via intra-screenshot reference matching
3. Suggest ranked moves with risk scoring
4. Save an annotated image with the top move highlighted

Outputs:
    data/extractions/level_NN/<stem>/play_overlay.jpg  — annotated screenshot
    stdout                                              — top moves with reasons
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collections import Counter

from src.model.diff import load_state
from src.solver.reactive import plan_triplets, suggest_moves
from src.vision.all_tiles import (
    detect_all_tiles, identify_combined, identify_via_intra_screenshot,
)
from src.vision.peek import load_library_samples


@click.command()
@click.argument("image_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--level", type=int, required=True)
@click.option("--top", type=int, default=5, help="How many top moves to show")
@click.option("--tiles-dir", type=click.Path(path_type=Path), default=ROOT / "data" / "tiles")
def main(image_path: Path, level: int, top: int, tiles_dir: Path) -> None:
    label_index = {}
    idx_path = tiles_dir / "index.json"
    if idx_path.exists():
        for e in json.loads(idx_path.read_text()).get("entries", []):
            label_index[e["tile_id"]] = e.get("label") or e["tile_id"]

    def lab(tid):
        return label_index.get(tid, tid) if tid else "?"

    # Run the standard extract pipeline first to get a structured state
    import subprocess
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "extract_board.py"),
         str(image_path), "--level", str(level)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        click.echo(result.stderr, err=True)
        raise click.ClickException("extraction failed")
    out_dir = ROOT / "data" / "extractions" / f"level_{level:02d}" / image_path.stem
    state_path = out_dir / "state.json"
    state = load_state(state_path)

    # Tile inventory: bright + dim + tray, count per tile type
    bgr_for_inventory = cv2.imread(str(image_path))
    library_samples = load_library_samples(tiles_dir)
    detections = detect_all_tiles(bgr_for_inventory)
    bright_dets = [d for d in detections if d.is_bright]
    dim_dets = [d for d in detections if not d.is_bright]
    bright_ids: list[str | None] = []
    for d in bright_dets:
        crop = bgr_for_inventory[d.y:d.y + d.h, d.x:d.x + d.w]
        tid, _, _ = identify_combined(crop, library_samples, is_bright=True)
        bright_ids.append(tid)
    dim_ids: list[tuple[str | None, float]] = []
    for d in dim_dets:
        crop = bgr_for_inventory[d.y:d.y + d.h, d.x:d.x + d.w]
        tid, sc, _ = identify_via_intra_screenshot(
            bgr_for_inventory, crop, bright_dets, bright_ids, library_samples,
        )
        dim_ids.append((tid, sc))

    bright_inventory: Counter = Counter()
    dim_inventory: Counter = Counter()
    tray_inventory: Counter = Counter()
    for tid in bright_ids:
        if tid:
            bright_inventory[tid] += 1
    for tid, sc in dim_ids:
        if tid and sc < 0.6:  # only count high-confidence dim IDs
            dim_inventory[tid] += 1
    for t in state.tray:
        if t.tile_id is not None:
            tray_inventory[t.tile_id] += 1
    inventory = bright_inventory + dim_inventory + tray_inventory

    # Get move recommendations
    moves = suggest_moves(state, label_fn=lab)
    plans = plan_triplets(state)

    tray_filled = sum(1 for t in state.tray if t.tile_id is not None)

    if plans:
        click.echo(f"\n=== Triplet plan ({len(plans)} ready triplets) ===")
        running_tray = tray_filled
        for plan in plans:
            running_tray += plan.taps_needed - 3  # net change after triplet clears
            tap_str = " -> ".join(plan.tap_locations)
            tray_note = f" [+{plan.tray_already} from tray]" if plan.tray_already else ""
            click.echo(f"  3x {lab(plan.tile_id)}: {tap_str}{tray_note}")
        click.echo()
    else:
        click.echo("\n=== No completable triplets right now ===\n")
    click.echo(f"Tray: {tray_filled}/7. {len(moves)} moves available.")
    click.echo(f"Visible tile inventory ({sum(inventory.values())} tiles, "
               f"{len(bright_dets)} bright + {len(dim_dets)} dim + {tray_filled} tray):")
    for tid, count in sorted(inventory.items(), key=lambda x: -x[1]):
        # Hidden tile floor: smallest multiple of 3 >= visible_count, minus
        # visible. Tells us minimum tiles still hidden in the level.
        min_total = ((count + 2) // 3) * 3
        hidden_min = min_total - count
        b = bright_inventory.get(tid, 0)
        d = dim_inventory.get(tid, 0)
        t = tray_inventory.get(tid, 0)
        # "Tappable now" = bright + tray. Triplet completable when bright + tray >= 3.
        tappable_now = b + t
        if tappable_now >= 3:
            note = "(triplet ready: tap " + str(b) + " bright)"
        elif b + d + t >= 3:
            blocked = (3 - tappable_now)
            note = f"(triplet possible if {blocked} dim unblocked)"
        elif hidden_min > 0:
            note = f"(>= {hidden_min} hidden)"
        else:
            note = ""
        breakdown = f"{b}b" + (f"+{d}d" if d else "") + (f"+{t}T" if t else "")
        click.echo(f"  {lab(tid):<18} {count}  ({breakdown})  {note}")
    click.echo()
    click.echo(f"{'rank':<5} {'score':>7}  {'location':<20} {'tile':<18} reason")
    for i, m in enumerate(moves[:top]):
        click.echo(f"{i+1:<5} {m.score:>7.2f}  {m.location:<20} {lab(m.tile_id):<18} {m.reason}")

    # Annotate the screenshot with top move(s) highlighted
    bgr = cv2.imread(str(image_path))

    # Mark dim/blocked tiles with their identification (low-opacity)
    for d, (tid, sc) in zip(dim_dets, dim_ids):
        if tid is None:
            continue
        color = (255, 100, 100)  # blue-ish for dim tiles
        cv2.rectangle(bgr, (d.x, d.y), (d.x + d.w, d.y + d.h), color, 2)
        confidence = "?" if sc > 0.6 else ""
        cv2.putText(bgr, f"{lab(tid)[:8]}{confidence}", (d.x + 4, d.y + d.h - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)

    def find_bbox(loc: str):
        if loc.startswith("("):
            r, c = [int(x) for x in loc.strip("()").split(",")]
            for cell in state.main_board:
                if (cell.row, cell.col) == (r, c):
                    return cell.bbox
        elif loc.startswith("queue:"):
            qid = loc.split(":", 1)[1]
            for q in state.queues:
                if q.queue_id == qid:
                    return q.bbox
        return None

    # If the top recommendation is a triplet, highlight ALL members with the
    # same color and a sequence label. Otherwise highlight the top N individually.
    drawn = set()
    if moves:
        top_move = moves[0]
        # All moves with same tile_id and same triplet-completion score are
        # part of the same triplet — draw them together
        triplet_locs = [
            m.location for m in moves
            if m.tile_id == top_move.tile_id
            and abs(m.score - top_move.score) < 0.1
            and m.score >= 7
        ]
        if len(triplet_locs) >= 1 and top_move.score >= 7:
            for j, loc in enumerate(triplet_locs):
                bbox = find_bbox(loc)
                if bbox is None:
                    continue
                x, y, w, h = bbox
                cv2.rectangle(bgr, (x - 4, y - 4), (x + w + 4, y + h + 4), (0, 255, 0), 8)
                cv2.putText(bgr, f"TAP {j+1}", (x + 8, y + h - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA)
                drawn.add(loc)
            cv2.putText(bgr, f"3x {lab(top_move.tile_id)} triplet",
                        (40, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3, cv2.LINE_AA)

    # Draw runners-up with dim cyan
    for i, m in enumerate(moves[:top]):
        if m.location in drawn:
            continue
        bbox = find_bbox(m.location)
        if bbox is None:
            continue
        x, y, w, h = bbox
        color = (180, 180, 0)
        cv2.rectangle(bgr, (x - 2, y - 2), (x + w + 2, y + h + 2), color, 3)
        cv2.putText(bgr, f"#{i+1} {lab(m.tile_id)}", (x, y - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)

    overlay_path = out_dir / "play_overlay.jpg"
    cv2.imwrite(str(overlay_path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 88])
    click.echo(f"\nannotated -> {overlay_path}")


if __name__ == "__main__":
    main()
