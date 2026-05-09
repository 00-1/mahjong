# Fresh-environment setup checklist

What to do (and what the user must do on the phone) when bootstrapping
this project from a clean Termux install. Everything here was hit
during the 2026-05-09 first-run setup; capturing it so the next
session doesn't have to re-discover it.

## Required user actions on the phone (NOT scriptable)

These need a human at the phone — they can't be done from Termux/adb.

1. **Sign in to a Xiaomi account** on the device (HyperOS/MIUI requirement).
   Without this, the secure-debugging toggles below stay greyed out.
2. **Enable Developer Options.** Settings → My device → All specs → tap
   "MIUI version" / "OS version" 7+ times.
3. In Developer Options:
   - **USB debugging** — on.
   - **USB debugging (Security settings)** — on. *Distinct toggle.*
     Without it, every `adb shell input tap/keyevent/...` returns
     `SecurityException: INJECT_EVENTS permission`. Without it, also
     `adb shell settings put ...` returns
     `SecurityException: WRITE_SECURE_SETTINGS`.
   - **Wireless debugging** — on.
   - **Stay awake (while charging)** — on. Keeps the screen on as long
     as the phone is plugged in. Far simpler than software keepalives.
   - **Disable screen lock** OR pre-unlock for the duration of the
     session. adb cannot dismiss a PIN/pattern lock without root.
4. **Toggle Wireless debugging off then on** AFTER flipping the security
   setting above. The permissions only take effect on a fresh adbd
   handshake. The connect port will rotate — read the new one off the
   Wireless debugging screen and hand it to the agent.
5. (Optional, for unattended runs) **Disable battery optimization for
   Termux**: Settings → Apps → Termux → Battery saver → No restrictions.
   Otherwise Android may suspend the Termux process during long idle
   gaps and the agent loop dies.

### Verifying the security toggle worked

After reconnect, from Termux:

```
adb shell input keyevent 224 && echo OK
```

If you see `OK`, injection works. If you see `SecurityException:
INJECT_EVENTS`, the security toggle is still off OR adbd wasn't
re-handshaken after enabling it — toggle WD off/on and try again.

## Termux package installs

Order matters slightly — `gh` and `git` are needed first to clone the
repo; the rest are needed before any of the Python pipeline runs.

```bash
# Tools
pkg install -y gh git android-tools

# Add the x11-repo (needed for opencv)
pkg install -y x11-repo

# Native Python deps — DO NOT use pip for these on Termux/aarch64
# (pip can't build opencv/numpy/scipy from source there).
pkg install -y opencv-python python-numpy python-pillow python-scipy

# dbus is a transitive runtime dep of the Qt6 stack opencv-python pulls in.
# Without it: `import cv2` fails with
#   ImportError: dlopen failed: library "libdbus-1.so" not found
pkg install -y dbus

# Pure-Python deps via pip. ImageHash needs --no-deps because its
# default dep resolution tries to rebuild scipy/numpy from source.
pip3 install --break-system-packages click
pip3 install --break-system-packages --no-deps ImageHash
```

Verify:

```bash
python3 -c "import cv2, numpy, PIL, scipy, click, imagehash; print('all good', cv2.__version__)"
```

## adb connection (Termux on the same physical device)

Counter-intuitively, **the loopback address is more reliable than the
LAN IP** when Termux is running on the same phone whose adbd you're
talking to.

Symptom seen with LAN IP: `adb pair 192.168.x.x:<port>` returns
`error: protocol fault (couldn't read status message): Success`. The
same command against `127.0.0.1:<port>` succeeds.

Pairing flow:

```bash
# Get pairing port + 6-digit code from the phone's Wireless debugging
# screen → "Pair device with pairing code".
adb pair 127.0.0.1:<pairing-port> <6-digit-code>

# Then read the connect port (different from the pairing port) from the
# main Wireless debugging screen and:
adb connect 127.0.0.1:<connect-port>

# Verify:
adb devices    # should show 127.0.0.1:<connect-port> device
```

The connect port rotates whenever WD is toggled or the phone reboots.
There is no auto-reconnect; the agent has to ask the user for the new
port. The pairing only needs to be done once per fresh adbd identity
(survives port rotation, doesn't survive a factory reset of debugging
authorisations).

## gh auth on a fresh install

```bash
gh auth login --hostname github.com --git-protocol https --web
```

Device flow prints a code (e.g. `724E-D67F`); user enters it at
https://github.com/login/device. Saves the token to
`~/.config/gh/hosts.yml`.

## Screen geometry varies between devices

Existing docs in this repo (`docs/agent_environment.md`,
`docs/navigation/README.md`, `docs/_session_artifacts/...`) were
written for a Poco F6 at **1220 × 2712**. The current session's device
is **1080 × 2400** (different phone). All hardcoded phone-pixel
coordinates in the navigation doc and `pnc_playbook/NOTES.md` are
calibrated for the larger geometry and **will miss on smaller screens**.

Always confirm geometry first:

```bash
adb shell wm size      # e.g. "Physical size: 1080x2400"
```

When porting the existing tap targets, scale by the ratio
`actual_w / 1220` and `actual_h / 2712`. For 1080×2400:

- x_factor ≈ 0.885
- y_factor ≈ 0.885

(Both axes happen to match within rounding — the two phones share a
very similar aspect ratio.)

Per-level template files under `data/levels/<NN>/template.json` are
also resolution-specific. They will need to be re-derived from a
screenshot at the new resolution before `agent.py decide` can run
cleanly. The vision pipeline itself (HSV thresholds, pHash matching)
is resolution-agnostic; only the cached per-level anchor coordinates
are not.

## What this session set up

- gh authed as `00-1`
- Cloned `00-1/mahjong` to `~/mahjong`
- All Python deps from the lists above installed
- adb paired + connected via 127.0.0.1
- Branch `claude/general-session-Yg2yw` checked out

What it did NOT set up (still TODO when the security toggle is on):

- `stay_on_while_plugged_in 7` (needs WRITE_SECURE_SETTINGS)
- Forced portrait via `accelerometer_rotation 0` + `user_rotation 0`
  (same)
- The `~/snap.sh` / `~/say` helpers (those live in
  `docs/_session_artifacts/phone_helpers/`; copy as needed)
