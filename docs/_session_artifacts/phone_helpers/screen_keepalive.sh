#!/data/data/com.termux/files/usr/bin/bash
# Periodic WAKEUP to keep phone screen alive without simulating a touch gesture.
# Avoids the edge-swipe approach that triggers HyperOS back-gesture detection.
while true; do
  adb shell input keyevent 224 >/dev/null 2>&1
  sleep 30
done
