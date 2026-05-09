#!/bin/bash
# Capture phone screen and emit a small JPEG (~50-80 KB) for the model to read.
# Phone is 1220x2712. Resize to 33% (~403x896) and save as JPEG q70.
set -e
adb exec-out screencap -p > /data/data/com.termux/files/home/screen.png
magick /data/data/com.termux/files/home/screen.png \
  -resize 33% -quality 70 \
  /data/data/com.termux/files/home/screen_small.jpg
ls -la /data/data/com.termux/files/home/screen_small.jpg
