# PNC gather cycle — standard run (1080×2400 device)

The procedure that worked unattended overnight 2026-05-09 → 2026-05-10
on the Poco X3 NFC (Android 12, 1080×2400). 10 cycles over ~7h15m,
~20 marches dispatched to Lv5 furnaces, no aborts, no foreign-realm
misfires. Lock this in as the standard.

## Calibrated tap coordinates (1080×2400)

| Element | (x, y) | Notes |
|---|---|---|
| WORLD bottom-nav button | (84, 2310) | Toggles city ↔ world |
| Search magnifier | (115, 1950) | Bottom-left, world-map only |
| Furnace tab (after horiz-swipe) | (900, 1845) | Tap centre of icon, not the label below it. Sometimes a second tap is needed if the first hits the label |
| Tab-row scroll | swipe `1000 1850 → 100 1850, 500ms` | Reveals Quarry/Furnace from default Monster |
| Lv-slider minus button | (70, 1980) | Drops by 1 per tap. *This is the reliable control.* Earlier guesses of (45/55/60, 1985/2000) miss the button entirely |
| Lv-slider plus button | (1015, 1980) | Nudge up by 1 (e.g. Lv4 → Lv5) |
| Lv-slider thumb (drag) | from `(905, 1985)` to `~(550, 1985)`, 1500ms+ | *Unreliable.* Sometimes registers (drops to Lv4), often does nothing. Use the minus button instead and only fall back to drag if minus also misbehaves |
| SEARCH button | (540, 2280) | Bottom of search panel. Re-tap to cycle to next nearest mine |
| Gather marker | (520, 650) | Small troop figure above the "Gather" text. Camera auto-centres after SEARCH |
| Bottom Select All / Depart | (540, 2295) | The big yellow CTA at the very bottom of the Depart dialog. Same coords for both — "Select All" becomes "Depart" after troops fill |
| Search-panel close (X) | (1015, 1530) | Top-right of the search bottom-sheet |
| Cancel exit-game prompt | (294, 1434) | When `keyevent 4` triggers "Exit the game?" |
| Mythic Hero promo close (X) | (1005, 390) | Top-right of the popup card after a connection-restore |
| Connection-failed CONFIRM | (540, 1440) | Reconnect dialog after PNC loses network |

**Slider control (revised after 2026-05-11 session):** prefer the
minus button at **(70, 1980)** and the plus button at **(1015, 1980)**.
Each tap moves the slider by exactly 1 level. To go Lv7 (default) →
Lv5: minus minus. Or to fix a stuck-at-Lv6 state: minus minus → plus.

The drag-thumb path used to work in the prior session but was flaky
this run — multiple long drags at 1500ms and 2500ms both no-op'd
when the slider was at Lv6. Reach for the buttons first.

### MANDATORY: verify slider every cycle (added 2026-05-12)

The slider **drifts down between cycles** — observed multiple times in
the 2026-05-12 session. Sometimes by 1 (Lv5 → Lv4), sometimes by 4
(Lv5 → Lv1). Cause unclear, possibly a stray tap during Depart
animation that lands on the minus button, possibly state isn't truly
preserved when the panel reopens.

Consequence of skipping the verify: **silent send failure**. Depart
fires, no error, but no march goes out. One full cycle this session
wasted 4 attempted sends this way (slider had drifted to Lv1, our
castle/troops can't fill a Lv1 furnace so the dialog quietly aborts).
Iron stockpile doesn't move; troop count stays the same as last cycle.

So: **after every (115, 1950) magnifier tap, before firing the
SEARCH button**, snap a crop of `(y=1900..2050, x=0..1080)` and
verify "Lv.5" is visible. If not, plus-button-tap up to it:

```bash
adb shell input tap 115 1950          # open search panel
sleep 5
adb exec-out screencap -p > /tmp/slider_check.png
# crop y=1900..2050, x=0..1080 and read the Lv.N indicator
# If Lv < 5: tap plus (1015, 1980) by (5 - current_lv) times.
# If Lv > 5: tap minus (70, 1980) by (current_lv - 5) times.
adb shell input tap 540 2280          # SEARCH button — now safe
```

If you skip this step and the slider has drifted, you'll send into a
mine your troops can't fill, the cycle "completes" reporting success,
but no march goes out. Next recheck will find you back at 1/5 or fewer
than expected.

## DO NOT tap (540, 2280) when no search panel is up

The SEARCH-button coord lies on top of the **BAG bottom-nav button**
in city/world view when the search bottom-sheet is closed. Mistapping
once during a recheck dumped us into the Resources tab of BAG and
took two `keyevent 4` rounds to recover (one of which triggered the
"Exit the game?" prompt).

Always assert the search panel is visible (a header reading "SEARCH"
near y≈1530 + the resource-type tab row at y≈1850) **before** firing
the SEARCH-button tap. If you're not sure the panel is open, snap
first — or just tap the search magnifier at (115, 1950) again, which
is idempotent.

A safer pattern for re-cycling SEARCH inside an existing send loop:

```bash
# After Depart returns to the world map, the search panel may or may
# not still be visible. Open it explicitly before the next SEARCH:
adb shell input tap 115 1950   # search magnifier (idempotent)
sleep 3
adb shell input tap 540 2280   # SEARCH button — now safe
```

## Occupied-mine recovery

After SEARCH, sometimes the panel that opens is the
**Scout / Info / Attack** action diamond instead of the Gather
marker. That means the mine is currently being gathered by another
player. The fix is to **back out and re-search** — there's no Gather
button to tap on this panel:

```bash
adb shell input keyevent 4    # close the action diamond
sleep 2
adb shell input tap 115 1950  # re-open search
sleep 3
adb shell input tap 540 2280  # SEARCH again — cycles to next mine
```

If the next SEARCH lands on the same mine repeatedly (3+ tries
returning identical X/Y in the header), the area genuinely has no
clean mines at the current Lv — try Lv4 or Lv6 instead, or switch to
a different resource (Farm/Lumberyard/Quarry) for one cycle.

## The four-tap send sequence

After SEARCH lands on a clean Lv5 mine (10,000 iron + "Gather" label,
no march lines):

```bash
adb shell input tap 540 2280   # SEARCH (re-cycles if needed)
sleep 3
adb shell input tap 520 650    # Gather marker
sleep 3
adb shell input tap 540 2295   # bottom Select All
sleep 2
adb shell input tap 540 2295   # Depart
sleep 4
```

Sleeps are not optional — the game animates between every step. The
4-second post-Depart sleep gives the dialog time to dismiss before the
next snap. Loop this block per free slot.

## Cron-driven recheck cadence

The successful schedule was **next-recheck = max(soonest_return + 5 min,
8 min from now)** when soonest_return was a "Gathering" timer (mine
cycle), and **+60 min** when all short timers were "Speedup" (in-transit,
not yet gathering).

What did NOT work: scheduling 60 min out when several short
"Gathering" timers were ~10 min apart. Three to four short marches
returning together meant we hit 1/5 (cycles #6 and #8 in this
session) and burned ~30 min of empty-slot time before the next
recheck.

Heuristic to apply:
- If ≥2 short "Gathering" timers ≤15 min: schedule cron for
  `max(soonest_return) + 2 min`. They land in a cluster; one cycle
  catches all the freed slots.
- If only one short timer or all "Speedup" (transit): schedule for
  `soonest_return + 3 min`, capped at 60 min.
- If 5/5 with no short timers: schedule for 60 min.

Always pin the cron to a non-:00/:30 minute (use the actual minute
you computed, don't round).

## Modal/popup recovery (one-off)

Things that landed during this run and how to dismiss:

- **Alliance chat panel auto-opens at launch**: `adb shell input
  keyevent 4` twice. First closes any context menu, second closes the
  panel itself. A third back triggers "Exit the game?" — use Cancel at
  (294, 1434) if it does.
- **"Connection failed. Do you want to reconnect?"**: tap CONFIRM at
  (540, 1440). After reconnect, a Mythic Hero / event promo card
  often blocks city view — close X at (1005, 390).
- **Foreign-realm safety**: if the search-result mine card shows
  `K<not-our-realm>` (e.g. `K232 (RUS)`), the march will still send,
  but it's slower travel. Acceptable for one-offs. To force home
  realm, tap SEARCH again to cycle to a closer mine.
- **Android "Turn on Battery saver" prompt** (added 2026-05-12): Android
  system dialog that pops over the PNC screen when battery dips below
  the configured threshold or the phone has been unplugged a while.
  Two buttons: **"Got it"** (left, declines) and **"Battery saver"**
  (right, enables — which will break adb input injection on some
  HyperOS builds; do NOT tap). Tap **Got it** at **(285, 2310)**, then
  re-launch PNC via `monkey` since the dialog backgrounded it.
- **"Connection failed. Do you want to reconnect?"** popping up *after*
  the previous recovery is its own thing — the Battery-saver dialog
  often disconnects PNC's session. Tap **CONFIRM** at **(540, 1440)**
  and give it ~8 s to reconnect before snapping. May be followed by a
  Mythic Hero / event promo card (close X at (1005, 390)) or a chat
  panel (`keyevent 4` ×2).

## What this session ran in practice

- Initial launch from Termux → city view → tap WORLD → snap troop
  info → search/Furnace/Lv5 → SEARCH → 4-tap send sequence per free
  slot → close panel → return to Termux → CronCreate next-recheck.
- Per-cycle wall-clock: ~60 s (snap, count, send 1–4 marches, schedule
  cron, return to Termux).
- 10 cycles, 0 aborts, ~+1.45M iron.

## Reference: announce-before-act + return-to-Termux

Both are mandatory per the existing playbook:
- `~/say "PNC gather recheck"` BEFORE any tap (gives the user a heads-up
  if they're touching the phone).
- `adb shell am start -n com.termux/.app.TermuxActivity` AFTER the cycle
  completes (so the user can see chat / next cron status).
