#!/bin/bash
# Capture phone screen and emit a top-cropped JPEG for verification snaps where
# the search panel (bottom ~40%) doesn't need re-reading. Faster Read than
# snap.sh because the image is ~60% the pixel area.
# Phone is 1220x2712. Resize to 33% (403x895), then crop top 80% (≈403x716).
# Output ~40-60 KB JPEG, well-suited for: world-map state checks, mine
# verification (Troop Info + mine info card + Gather label + march lines + the
# search magnifier at small y≈716 are all within the top 80%), Depart-dialog
# state where dialog occupies upper screen.
# Use snap.sh (full screen) when you need to see the bottom-most UI: the
# search panel itself (Furnace tab, level slider, SEARCH button), the bottom
# Select All / Depart button, bottom-nav buttons.
set -e
adb exec-out screencap -p > /data/data/com.termux/files/home/screen.png
magick /data/data/com.termux/files/home/screen.png \
  -resize 33% -gravity north -crop 100%x80%+0+0 +repage -quality 70 \
  /data/data/com.termux/files/home/screen_small.jpg
ls -la /data/data/com.termux/files/home/screen_small.jpg
