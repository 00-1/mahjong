#!/usr/bin/env python3
"""Rebuild data/levels/<NN>/anchor_priors.json from accumulated screenshots.

When the template (data/levels/<NN>/template.json) is rebuilt with
different anchor positions / labels, the existing anchor_priors.json
becomes stale: its (row, col) keys point to physical positions that
no longer match. This script re-extracts every saved screenshot
under data/runs/run_*_lNN/ using the CURRENT template, then
accumulates per-anchor d1/d2 tile-id observations into a fresh
priors file.

Backs up the existing priors file before overwriting.

Usage:
    python scripts/rebuild_anchor_priors.py --level 8
    python scripts/rebuild_anchor_priors.py --all
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2

from src.vision.detect import detect_tile_faces, DetectConfig
from src.vision.template import load_template, scale_template, snap_detections
from src.vision.library import TileLibrary, crop_face_center


def rebuild_for_level(level: int, runs_dir: Path, levels_root: Path,
                      tiles_dir: Path, min_main_for_puzzle: int = 6) -> dict:
    template_path = levels_root / f"{level:02d}" / "template.json"
    if not template_path.exists():
        raise SystemExit(f"No template at {template_path}")
    template = load_template(template_path)
    library = TileLibrary(tiles_dir)
    out_anchors: dict = {}

    pat = re.compile(rf"^run_[\d_]+_l{level:02d}$")
    n_processed = 0
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir() or not pat.match(run_dir.name):
            continue
        for png in sorted(run_dir.glob("t*.png")):
            bgr = cv2.imread(str(png))
            if bgr is None:
                continue
            h, w = bgr.shape[:2]
            t = scale_template(template, w, h)
            dets = detect_tile_faces(bgr, DetectConfig())
            sr, _ = snap_detections(dets, t, w)
            main_n = sum(1 for r in sr if r.anchor.zone == 'main_board')
            if main_n < min_main_for_puzzle:
                continue
            for r in sr:
                if r.anchor.zone != 'main_board':
                    continue
                depth = 1 if (r.offset_x, r.offset_y) == (0, 0) else 2
                d = dets[r.detection_idx]
                crop = crop_face_center(bgr, d.x, d.y, d.w, d.h)
                entry, _, _ = library.lookup_or_add(crop, source=str(png))
                key = f"({r.anchor.row},{r.anchor.col})"
                if key not in out_anchors:
                    out_anchors[key] = {}
                d_label = f"d{depth}"
                if d_label not in out_anchors[key]:
                    out_anchors[key][d_label] = {"total": 0, "tiles": {}}
                out_anchors[key][d_label]["total"] += 1
                out_anchors[key][d_label]["tiles"][entry.tile_id] = \
                    out_anchors[key][d_label]["tiles"].get(entry.tile_id, 0) + 1
            n_processed += 1

    return {
        "level": level,
        "anchors": out_anchors,
        "rebuilt_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "screenshots_processed": n_processed,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--level", type=int, action="append")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--runs-dir", type=Path, default=ROOT / "data" / "runs")
    ap.add_argument("--levels-root", type=Path, default=ROOT / "data" / "levels")
    ap.add_argument("--tiles-dir", type=Path, default=ROOT / "data" / "tiles")
    ap.add_argument("--no-backup", action="store_true",
                    help="Don't preserve the existing priors file")
    args = ap.parse_args()

    if args.all:
        levels = []
        for d in args.levels_root.iterdir() if args.levels_root.exists() else []:
            try:
                levels.append(int(d.name))
            except ValueError:
                pass
        levels.sort()
    elif args.level:
        levels = args.level
    else:
        ap.error("--level NN or --all required")
        return 2

    for level in levels:
        target = args.levels_root / f"{level:02d}" / "anchor_priors.json"
        if target.exists() and not args.no_backup:
            backup = target.parent / f"anchor_priors.json.bak.{int(time.time())}"
            shutil.copy(target, backup)
            print(f"Backed up old priors to {backup}")
        priors = rebuild_for_level(level, args.runs_dir, args.levels_root, args.tiles_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(priors, indent=2))
        n_anchors = len(priors["anchors"])
        total_obs = sum(
            d.get("total", 0)
            for v in priors["anchors"].values()
            for d in v.values()
        )
        print(f"Level {level}: {priors['screenshots_processed']} screenshots, "
              f"{n_anchors} anchors, {total_obs} total observations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
