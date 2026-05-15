#!/usr/bin/env python3
"""Generate `_small.jpg` thumb variants for every PNG fixture that
doesn't already have one.

Why: visual inspection of full-res 1080x2400 PNGs (3-4 MB each) inflates
agent context fast and has triggered "request too large" errors. The
small.jpg variants are ~30-100 KB and human-legible — fine for
visual cross-checks. The full PNG stays as the source of truth for
cv2-based tests (pixel-accurate detection).

Usage:
    python3 scripts/gen_fixture_thumbs.py
    python3 scripts/gen_fixture_thumbs.py --force   # regenerate all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

FIX = Path(__file__).resolve().parents[1] / "tests" / "pnc" / "fixtures"
THUMB_WIDTH = 540
JPEG_QUALITY = 70


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true",
                   help="Regenerate even if thumb already exists")
    args = p.parse_args()

    written = 0
    for png in sorted(FIX.glob("*.png")):
        thumb = FIX / f"{png.stem}_small.jpg"
        if thumb.exists() and not args.force:
            continue
        bgr = cv2.imread(str(png))
        if bgr is None:
            print(f"skip (unreadable): {png.name}")
            continue
        h, w = bgr.shape[:2]
        if w > THUMB_WIDTH:
            target_h = int(h * THUMB_WIDTH / w)
            bgr = cv2.resize(bgr, (THUMB_WIDTH, target_h),
                             interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(thumb), bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        size_kb = thumb.stat().st_size // 1024
        print(f"wrote {thumb.name} ({size_kb}KB)")
        written += 1

    print(f"\n{written} thumb(s) written, fixtures dir: {FIX}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
