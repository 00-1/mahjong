# Session artifacts

Snapshot of files that lived **outside** this repo but accumulated during the
long session that ended up working on the Arcane Puzzle agent. The user asked
to commit "everything we've been working on locally, even non-mahjong work" —
this folder is that commit.

Most of this is not load-bearing for the puzzle solver. It's preserved here so:
1. The phone-helper scripts (`snap.sh` etc.) that the agent_environment doc
   references actually have a referenceable source.
2. The PNC march-automation playbook, which taught us the
   tap-precision / lock-screen / port-rotation lessons that fed into the
   puzzle-agent setup, has a home before it gets lost when a session resets.
3. Future Claude sessions reading this branch can see what was already
   learned about driving this specific phone with adb.

## Layout

```
phone_helpers/
  snap.sh              full-screen snap, 33% downscale q70 JPEG
  snap_top.sh          top 80% crop, same downscale
  snap_zoom.sh X Y W H full-resolution rectangle crop
  say                  espeak → paplay narration helper
  screen_keepalive.sh  keyevent 224 every 30 s — see warning below

pnc_playbook/
  NOTES.md             the live playbook from the PNC march-automation work.
                       Calibrated tap targets, fade/sleep table, snap helper
                       guide, march flow, alliance furnace flow, etc.
                       NOT directly relevant to the puzzle but a working
                       reference for *how to drive PNC's UI via adb*.

claude_memory/
  MEMORY.md            index
  user_environment.md  Poco F6, HyperOS, ARM Termux
  adb_loopback_setup.md  adb on 127.0.0.1 / LAN, port-rotation gotchas
  feedback_*.md        per-session preferences (terse narration, use ~/say,
                       use judgment when driving UIs, return to Termux at
                       end of run, narrate before tapping)
  reference_pnc.md     pointer to the live PNC playbook

HANDOFF.md             cross-session handoff doc — "you, the next Claude,
                       are picking up this work; here's what works"
```

## Important warning carried over from PNC work

The screen keepalive in `phone_helpers/screen_keepalive.sh` uses
`adb shell input keyevent 224` (KEYCODE_WAKEUP) every 30 s. **Do not** swap
that for the older edge-swipe pattern (`input swipe 5 Y1 5 Y2 ...`) — on
HyperOS / MIUI those swipes trigger the system **Back gesture** and will
silently sabotage every tap that's followed by an edge-swipe-detected back.
This was hours of confusion until figured out. See
`../navigation/README.md` for the full story.

## What's NOT in here

- The PNC screenshot archive (`~/pnc_explore/*.png`) — large, not useful
  for the puzzle agent; left on the user's home directory.
- Live cron schedules / wake-locks / PulseAudio state — runtime-only.
