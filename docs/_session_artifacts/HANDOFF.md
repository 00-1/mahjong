# Handoff — Termux Phone Control + PNC + Voice (2026-05-03)

You (the next Claude session) are picking up a long-running setup on a Poco F6 (Android, HyperOS V816 / OS3.0.5.0). Read `~/.claude/projects/-data-data-com-termux-files-home/memory/MEMORY.md` first — that's the persistent memory index. This file is the session-specific summary.

## What works right now
- **adb wireless on loopback.** `adb shell input tap/swipe/keyevent` injection succeeds. Permission unlock came from a combination of (a) Xiaomi account signed in, (b) Developer options → "USB debugging (Security settings)" enabled, and (c) full adb reconnect after toggling. If `input tap` ever returns `SecurityException: INJECT_EVENTS`, that toggle has flipped off.
- **Screenshot capture** via `~/snap.sh` → `~/screen_small.jpg`. Output is JPEG q70 at 33% scale (~50–80 KB) to keep context budget manageable. Earlier 50%-PNG output blew the 32 MB request limit; do NOT revert to PNG.
- **Battery saver disabled for Termux** (Settings path verified working). `Pause app activity if unused` may still be on — left as-is.
- **TTS via `~/say`.** Direct narration helper at `~/say` — call as `~/say "<short message>"`. It runs `espeak → paplay` (PulseAudio's OpenSL ES sink, which keeps audio focus when Termux is backgrounded), detaches via `setsid -f`, returns immediately. The previous Stop-hook approach was removed — it was only reading one entry per turn, often the previous turn's text due to transcript-flush races. Direct `~/say` calls during work are the canonical narration channel; see `feedback_terse_narration.md` in memory.

## adb port rotation (open problem)
Wireless debugging port changes whenever the user toggles WD off/on or the phone reboots. Termux's `adb` binary doesn't have mDNS support compiled in, so `adb mdns services` fails. Workaround for unattended sessions: ask user to leave WD on + stay-awake-while-charging in Developer options. We have NOT solved auto-reconnect; it currently requires the user to read a port off the phone and tell you. Current connection: see `adb devices`. Probably already connected if no recent toggle.

## Main task: Puzzles & Chaos: Frozen Castle resource gathering

**Status (2026-05-03):** end-to-end gather flow verified — march sent, observed in Troop Info as `Marching` then `Gathering`. Maintenance loop in progress: keep 5 marches always out on Lv5 iron furnaces.

Authoritative reference: `~/pnc_explore/NOTES.md`. Read before any clicking. It contains the calibrated tap targets, the cold-launch loading-screen handling, the city-vs-world view check, the Gather → bottom Select All → Depart sequence, and the rule about NOT tapping the upper Select All (which selects heroes).

**Maintenance loop pattern (when a march returns):**
1. Snap world map, read Troop Info (n/5).
2. For each free slot: tap search → tap SEARCH → verify mine clean (10,000 iron, "Gather" label, no dashed march lines) → tap Gather (605, 712) → tap bottom Select All (605, 2585) → tap Depart (605, 2585).
3. Compute next-recheck = `min(remaining gather time) + ~3.5 min travel - 1 min` and schedule a one-shot CronCreate.
4. Return to Termux foreground.

## Runtime keepalives (session-only — do NOT assume they survive a Claude restart)

In the current session we set up:
- `termux-wake-lock` held — keeps the Termux process / Claude JS event loop from being suspended during long idle gaps. Drains battery when unplugged; user is staying plugged in.
- Background loop running `adb shell true` every 600 s — keeps the loopback adb socket warm during long idle gaps so the cron timer doesn't fire into a dead connection. PID lives only in this Claude session; pgrep for it: `pgrep -af "while true.*adb"`.
- One-shot CronCreate scheduled for the next predicted slot-free time. Session-only.

If a fresh Claude session inherits the maintenance task: re-acquire `termux-wake-lock`, restart the keepalive loop, snap to read current march state, compute next recheck, schedule.

## Voice-in / voice-out plan (in progress)

User's goal: hands-free voice while PNC is in foreground, no touching the phone. Decided NOT to pursue chat-with-voice-notes (Slack/Telegram bot) — they want a real call experience.

**Phone-only path** (their preference, not yet implemented):
- Bluetooth headset / earbuds connected to phone
- Termux records mic continuously via PulseAudio source + ffmpeg/sox (need to load `module-sles-source` into the existing PA daemon)
- Local STT via whisper.cpp (free, offline, slow on phone CPU but acceptable for short utterances)
- TTS already works (espeak → paplay)
- Bridge into Claude Code: pipe transcribed text via `tmux send-keys` or write to PTY, since direct stdin injection into the running Claude TUI needs the session to be in tmux/screen
- Estimated 1–2 hours to wire up

**Alternative bookmarked but NOT chosen**: Discord voice bot with user on a laptop. Cleaner architecturally but user only has the phone in this scenario.

## Useful files / paths

| Path | Purpose |
|---|---|
| `~/snap.sh` | Take phone screenshot → `screen_small.jpg` |
| `~/screen.png` | Full-resolution screenshot (transient) |
| `~/screen_small.jpg` | Resized JPEG used by Read tool |
| `~/.claude/settings.json` | User Claude Code settings (hooks live here) |
| `~/.claude/hooks/speak.sh` | Stop hook for TTS |
| `~/.claude/hooks/speak.log` | Log of when the hook fired (timestamp + char count) |
| `~/.claude/hooks/speak.last_uuid` | Last spoken assistant UUID (dedupe) |
| `~/pnc_explore/` | All PNC screenshots + NOTES.md |
| `~/.claude/projects/-data-data-com-termux-files-home/memory/MEMORY.md` | Persistent memory index |
| `~/.claude/projects/-data-data-com-termux-files-home/memory/adb_loopback_setup.md` | Reconnect / troubleshooting reference |

## Working files for the failed UHID experiments (informational only, do not use)
`~/uhid_mouse.c`, `~/uhid_relmouse.c`, `~/uhid_touch.c`, `/data/local/tmp/uhid_*` on device. These were dead ends — Android requires display-binding via hidden APIs that scrcpy server has but a standalone C binary doesn't. Now that `input tap` works, none of this is needed. Safe to ignore or delete later.

## Recommended first actions in the new session

1. Read `MEMORY.md`, then this file, then `~/pnc_explore/NOTES.md`.
2. Verify adb: `adb devices`. If empty, ask user for the new wireless-debugging port.
3. Send one short text response so the user can confirm narration is working in the new session.
4. Ask user what they want to tackle first: complete the PNC gather flow end-to-end, or set up the phone-only voice loop.
