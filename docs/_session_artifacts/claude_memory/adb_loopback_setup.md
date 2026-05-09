---
name: ADB loopback control of Poco F6
description: How to drive the Poco F6's UI from Termux via wireless-debugging adb on loopback
type: reference
originSessionId: 867f7e23-ba91-4e93-8461-56ec94ed26f0
---
User has set up adb-over-loopback on their Poco F6 (Android, MIUI/HyperOS) so Claude can drive the device from Termux.

**Setup state:**
- `android-tools` installed via pkg (adb at /data/data/com.termux/files/usr/bin/adb)
- `imagemagick` installed for resizing screencaps (Read tool rejects images > 2576px)
- Helper script at `/data/data/com.termux/files/home/snap.sh` runs screencap + resize to `screen_small.png`
- Pairing port rotates each toggle of Wireless debugging; connect port also rotates. User must read both from Settings → Developer options → Wireless debugging.

**Reconnect flow each session:**
1. User enables Wireless debugging on phone
2. `adb pair 127.0.0.1:<PAIR_PORT> <CODE>` (pairing code shown on "Pair device with pairing code" screen)
3. `adb connect 127.0.0.1:<CONNECT_PORT>` (port shown on main Wireless debugging page)
4. May need `adb kill-server && adb start-server` then retry connect — first attempt sometimes fails silently
5. Pairing persists across sessions (guid stored), so re-pairing not needed unless user revokes authorizations

**Screen resolution:** 1220x2712. snap.sh resizes to 50% (610x1356) for Read tool.

**Input injection — RESOLVED (2026-05-03):**
`adb shell input tap/swipe/text/keyevent` now works. The unlock combo on this device:
1. Xiaomi account signed in (was already logged in on this device)
2. Developer options → **USB debugging (Security settings)** enabled
3. After enabling, full adb reconnect (`adb kill-server && adb start-server && adb connect 127.0.0.1:<port>`)

When tap injection fails with `SecurityException: Injecting input events requires INJECT_EVENTS`, the toggle has been turned off (HyperOS sometimes auto-disables it after reboots/updates) — check it first.

**What works without input injection:**
- Screenshots (`screencap`)
- Launching activities/intents (`am start ...`)
- Listing/inspecting packages (`pm list`, `dumpsys`)
- Logcat
- Installing/uninstalling APKs

**Tap injection — historical workaround notes (no longer needed since `input tap` works):**
- `/dev/uhid` is accessible to the `shell` user (uid 2000 is in the `uhid` group, SELinux context allows it). Confirmed by writing UHID_CREATE2 and receiving UHID_START + UHID_OPEN events back from the kernel.
- A standalone UHID mouse from Termux (e.g. `/data/local/tmp/uhid_relmouse` compiled from `/data/data/com.termux/files/home/uhid_relmouse.c`, using scrcpy's exact relative-mouse descriptor) creates the device but **Android does not render a cursor or accept clicks from it**. Hypothesis: scrcpy's server JAR ties the UHID device to a specific display via hidden Android APIs (the `getUhidManager()` flow takes a display unique ID). Standalone code can't easily replicate that.
- `scrcpy --mouse=uhid` (running on-device with Xvfb + DISPLAY=:99) **does** render a cursor on the phone and accept clicks — but xdotool driving fails because scrcpy's relative mouse + auto-recenter pulls the cursor back to window center, so absolute targeting doesn't stick.
- `/dev/input/event*` (e.g. the real Goodix touchscreen at event7) is permission-denied to shell — SELinux blocks the `shell` domain from `input_device` despite Unix group membership.
- `input tap`, `input keyevent`, `cmd input` — all blocked by MIUI INJECT_EVENTS check even though `com.android.shell` has the permission. Enabling Developer options → "USB debugging (Security settings)" did not lift the restriction over wireless adb on this HyperOS build (V816 / OS3.0.5.0). Next thing to try: signing into a Mi account (the toggle silently does nothing without one), then waiting any required cooldown.

**Best remaining path to working taps:**
1. Talk to scrcpy server's control socket directly (documented binary protocol) — bypasses xdotool/Xvfb entirely. Scrcpy already does the display-binding magic.
2. Mi account login → unlocks `input tap` (simplest).

**Helper scripts on disk:**
- `/data/data/com.termux/files/home/snap.sh` — screenshot + 50% resize → `screen_small.png`
- `/data/data/com.termux/files/home/uhid_mouse.c` — absolute-position mouse (no cursor renders)
- `/data/data/com.termux/files/home/uhid_relmouse.c` — relative mouse with scrcpy descriptor (kernel registers, no cursor)
- `/data/data/com.termux/files/home/uhid_touch.c` — single-touch digitizer (kernel registers, no taps)
- `/data/local/tmp/uhid_*` — pushed copies that run as `shell` user via `adb shell`
- `/data/data/com.termux/files/home/scrcpy.log` — last scrcpy run output
