# Agent environment setup (Termux on Android)

The play agent runs in Termux on an Android phone, calling `agent.py` over a
local Python install and driving the device via adb-on-loopback (or LAN).
This doc captures setup gotchas that are not in `requirements.txt`.

## Python deps: prefer `pkg install` over `pip install` for native modules

On Termux ARM with Python 3.13, **pip cannot build `opencv-python` or
`numpy` from source** — both fail on missing build tools (ninja, the
right C++ headers). Wheels for these packages on ARM/Termux do not exist
on PyPI for current Python versions.

Instead, use Termux's package manager (which has prebuilt native binaries
for ARM):

```
pkg install -y opencv-python python-numpy python-pillow python-scipy
pip3 install click ImageHash
```

`opencv-python`, `numpy`, `Pillow`, `scipy` come from `pkg`.
`click`, `ImageHash` are pure-Python and install fine via pip.

After install, verify:

```
python3 -c "import cv2, numpy, PIL; print(cv2.__version__, numpy.__version__, PIL.__version__)"
```

## adb connection (wireless debugging)

Phone is connected via wireless debugging on its LAN IP, not USB. Steps:

1. Enable Developer Options → Wireless debugging on the phone.
2. Note the IP:port (the port rotates whenever WD is toggled or the phone
   reboots, so don't hardcode it).
3. `adb connect <ip>:<port>` from Termux.
4. `adb devices` should show the device.

If adb drops mid-run (port refused), the WD port has rotated. Ask the
user for the new port; reconnect; resume.

Loopback mode (`127.0.0.1:<port>`) sometimes works if Termux is on the
same device, but the LAN address is more reliable across the WD-restart
cycle.

## Keep the phone awake

Two settings to apply at the start of every session:

```
adb shell settings put global stay_on_while_plugged_in 7
```
(Stays awake while charging on AC, USB, or wireless. Bitmask: 1 + 2 + 4 = 7.)

If the lock screen still kicks in, the device has a PIN/pattern. You
**cannot** unlock it via adb without root. The user has to pre-unlock the
phone for the agent run; or disable the lock screen / lower the security
level for an extended unattended session.

For a periodic keepalive (in case the screen still dims), use:

```
nohup sh -c 'while true; do adb shell input keyevent 224 >/dev/null 2>&1; sleep 30; done' >/dev/null 2>&1 & disown
```

`KEYCODE_WAKEUP=224` wakes the screen without simulating a touch.

**DO NOT use edge-swipe keepalives** like `input swipe 5 Y1 5 Y2 ...`. On
HyperOS / MIUI those trigger the system Back gesture and will silently
sabotage every tap that's followed by a back-detected swipe.

See `docs/navigation/README.md` for the gory details.

## Screen capture for `agent.py decide`

Native phone resolution is 1220×2712 (verify with `adb shell wm size`).
`adb exec-out screencap -p > shot.png` produces a full-resolution PNG;
that's what `agent.py decide --screenshot shot.png` expects.

Helpers in `~/`:
- `~/snap.sh` — full screen, 33% downscale, JPEG q70 (~50–80 KB). For
  context-budget-friendly diagnostic snaps in the chat. **Not** for
  agent.py — agent.py prefers full-res.
- `~/snap_top.sh` — top 80% only, also 33% downscale. Useful for
  world-map state where the bottom search panel doesn't need re-reading.
- `~/snap_zoom.sh X Y W H` — full-res crop of an arbitrary rectangle.
  Use this to measure precise button positions when downscaled snaps
  blur adjacent UI elements together.

For the agent loop, use `adb exec-out screencap -p > /tmp/shot.png`
directly — full resolution, no downscale, fastest path.

## Orientation

The phone may rotate to landscape mid-session if a swipe gesture is
mis-interpreted. Force portrait at session start:

```
adb shell settings put system accelerometer_rotation 0
adb shell settings put system user_rotation 0
```

Verify with `adb shell wm size` (should print `1220x2712` not `2712x1220`).

## Background daemons

The agent's background processes (keepalive loops, scheduled crons) live
in this Claude session's process tree. They die when Claude exits.
For true persistence across Claude restarts, write a Termux Boot script
or use `cron` from `tsu`/`pkg install cronie`.

## Screenshots in the agent chat context

Claude Code multi-image requests error at 2000px dimension. Always read
`*_small.jpg` siblings (produced by `snap_small.sh`, scaled to 540px wide)
rather than full PNGs. Never accumulate more than ~3 images per context
window; run `/compact` or start a new session if snaps pile up.

## Iron-gather cron cycles

Run `popup_dismiss` then `iron_gather` directly — do **not** use
`pnc_cron_tick.py` as the outer wrapper for gather-only sessions. The tick
script calls `ensure_world_view` which may incorrectly detect city-view
and tap HOME (84, 2310), which on this device opens the Rewards Center /
Monthly Card store overlay. The iron_gather script handles the world-view
transition itself safely.

The Monthly Card and Rewards Center full-screen overlays are not registered
in `detect_popup`. If they appear, dismiss with `adb shell input keyevent 4`
(Back key) before retrying.

Battery saver dialog (Android system, not PNC): tap "Got it" at (314, 2100)
on a 1080×2400 device. Appears at <20% and again at <10% battery.

## Known fragile points (ordered by frequency hit)

1. **Wireless debugging port rotates** — every WD toggle or reboot.
2. **Background keepalive sabotaging the agent** — see edge-swipe note above.
3. **Phone auto-locks even with stay-awake set** — happens during long
   idle gaps. Lock screen dismissal needs user PIN; agent can't bypass.
4. **`pip install opencv-python` failure on ARM/Termux** — use `pkg`.
5. **Level-list scroll bounce** — if Continue tap doesn't seem to do
   anything, suspect (a) edge-swipe keepalive, (b) tap arrived during
   scroll momentum settle, or (c) the panel snapped to a different scroll
   position than the snap captured. Wait 3 s after a scroll, snap,
   immediately tap based on the snap, no other adb input in between.
6. **`screen_keepalive.sh` must be running** — start it with
   `nohup bash ~/screen_keepalive.sh >/dev/null 2>&1 &` at session start.
   Without it the screen sleeps, HyperOS drops the wireless ADB connection,
   and the game process can be suspended mid-cycle.
