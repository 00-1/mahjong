#!/bin/bash
# Capture a full-resolution crop of a region of interest. No downscaling, so
# every pixel in the output JPEG corresponds 1:1 to a phone pixel — eliminates
# the ~3x error multiplier that snap.sh / snap_top.sh impose by resizing to 33%.
#
# Usage: ~/snap_zoom.sh X Y W H
#   X, Y = top-left corner in PHONE coordinates (0..1219 horizontal, 0..2711 vertical)
#   W, H = width and height of the crop region in phone pixels
#
# Tap math: a click at zoom-image pixel (zx, zy) corresponds to phone tap
# (X + zx, Y + zy). Read the zoom snap, find the button center in the zoom
# image, add the zoom origin to get the real phone tap coord.
#
# Recommended sizes: 400x400 to 600x600 region — keeps JPEG ~30-80 KB at q85,
# which is comparable in context cost to snap.sh / snap_top.sh but full-res.
# Don't crop the whole screen at full res — JPEG will be huge.
#
# Workflow:
#   1. ~/snap_top.sh                       # overview, find rough region
#   2. ~/snap_zoom.sh 800 1400 400 400     # zoom into that region full-res
#   3. Read zoom snap; identify button center at zx, zy
#   4. adb shell input tap $((800+zx)) $((1400+zy))
set -e
if [ $# -ne 4 ]; then
  echo "Usage: $0 X Y W H" >&2
  echo "  example: $0 800 1400 400 400" >&2
  exit 1
fi
x=$1; y=$2; w=$3; h=$4
adb exec-out screencap -p > /data/data/com.termux/files/home/screen.png
magick /data/data/com.termux/files/home/screen.png \
  -crop "${w}x${h}+${x}+${y}" +repage -quality 85 \
  /data/data/com.termux/files/home/screen_small.jpg
ls -la /data/data/com.termux/files/home/screen_small.jpg
echo "zoom origin: ($x, $y)  --  tap = phone(${x}+zx, ${y}+zy)"
