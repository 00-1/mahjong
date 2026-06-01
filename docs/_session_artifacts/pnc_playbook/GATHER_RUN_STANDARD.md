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

### MANDATORY: snap-and-verify the slider every cycle (revised 2026-05-13)

The slider's opening state is **non-deterministic**. Four distinct
behaviours observed across two days of cron-driven cycles:

| Opening state | When seen | Fix |
|---|---|---|
| **Lv5** (preserved) | Steady-state, most cron-driven re-opens once the loop has settled | none — proceed |
| **Lv3** (Furnace default-ish) | Common drift on 2026-05-12 afternoon — 11 cycles in a row | plus×2 at (1015, 1980) |
| **Lv7** (Furnace max default) | First cycle after a long idle gap, or first cycle of a fresh session | minus×2 at (70, 1980) |
| **Monster Lv40** (absolute default) | After a PNC version update or full game restart — Furnace tab itself isn't selected | full re-scroll, see "Post-version-update reset" below |

Consequence of skipping the verify: **silent send failure**. Depart
fires, no error, but no march goes out. Earlier sessions wasted 4
attempted sends per cycle this way (slider had drifted to Lv1, and the
sender just kept tapping Depart on Lv1 furnaces our troops can't fill).

There is no shortcut. **Always snap-and-verify** before the SEARCH
button:

```bash
adb shell input tap 115 1950          # open search panel
sleep 5
adb exec-out screencap -p > ~/snaps/slider_check.png
# Crop y=1900..2050, x=0..1080 of the screencap and read the Lv.N
# indicator (the gold "Lv.N" text just above the slider thumb).
# If "Lv.5" — proceed.
# If "Lv.N" with N < 5: tap plus (1015, 1980) by (5 - N) times,
#                       sleep 1 between taps.
# If "Lv.N" with N > 5: tap minus (70, 1980) by (N - 5) times,
#                       sleep 1 between taps.
# If "Monster" or "Lv.40": tab isn't on Furnace — see Post-update.
adb shell input tap 540 2280          # SEARCH button — now safe
```

The previous version of this doc recommended "always +2" as a
shortcut for the Lv3 case. That's wrong: it overshoots to Lv7 when
the slider was already at Lv5 (saw this on 2026-05-13). Always
verify. The screencap round-trip costs <500 ms — far less than the
cost of a silently-failed cycle.

### Post-version-update reset

If PNC pushes an update mid-session, the search panel will open with
the **Monster** tab selected at **Lv40** (the absolute defaults), not
the Furnace+Lv5 state from before. Recovery is the full re-scroll:

```bash
adb shell input swipe 1000 1850 100 1850 500   # scroll tab row left
sleep 3
adb shell input tap 900 1845                   # Furnace tab
sleep 3
# now snap-verify slider — likely Lv3 (default for Furnace), plus to 5
```

Update prompts surface as "New version found, please install the
latest update assets" with a CONFIRM button at (540, 1440). After
confirm, expect ~30 s of loading splash before the city view appears.

## Post-version-update / first-launch tab state (added 2026-05-17)

After a PNC update, app restart, or any time the search panel hasn't
been used recently, the panel opens on the **Monster tab at Lv.40**
(absolute defaults). The Furnace tab is to the right of the visible
tabs; reaching it requires the horizontal tab-row swipe.

Recovery captured live 2026-05-17:

```bash
adb shell input tap 115 1950          # magnifier opens search panel
sleep 4
adb shell input swipe 1000 1850 100 1850 500   # scroll tabs left
sleep 3
adb shell input tap 940 1850          # Furnace tab
sleep 3
# Slider on Furnace defaults to Lv.5 directly — no nudge needed on
# this device (verified with fixtures world_5of5_with_marching_2026-05-17).
adb shell input tap 540 2280          # SEARCH
```

`pnc_iron_gather.py` currently assumes the panel is already on Furnace.
Open work item: add tab detection (Monster vs Furnace) and the swipe
sequence so the script self-heals on the post-update reset path.

## search magnifier (115, 1950) is a TOGGLE — check before tapping

The magnifier opens the search panel when closed, but CLOSES it when
already open. The iron-gather script's `open_search_panel` was naively
tapping the magnifier as the first action; if the panel was left
open from a previous run, this closed it and the subsequent
`read_search_panel_lv` returned `None` → abandon.

Fix landed in commit (2026-05-17): snap first, return early if
`read_search_panel_lv` already detects an open panel, only tap the
magnifier when the panel is closed.

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

## Lv5 furnace gather time

Observed: **~1:58** (not 2:00). Timer rows show `Gathering 01:58:xx`
immediately after troops arrive at the furnace. Schedule accordingly.

Formula: `march_arrival_time + 1:56` gives a ~2 min early-arrival buffer.
Rounding up to `+ 2:00` leaves troops idle 2–4 min per cycle (confirmed
2026-06-01: cron at +2:04 arrived after troops had been back ~3 min).

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
- **"Relocate" popup** (added 2026-06-01): appears when another player uses a teleport near our
  castle; opens the Relocate confirmation dialog. `keyevent KEYCODE_BACK` escalates to the
  Relocate confirmation (CANCEL / 200,000-gold Relocate). Tap **CANCEL** at ~**(155, 648)**
  in 540px snap coords to dismiss. Do NOT press BACK again — it may open the Resource Trade screen.
- **Resource Trade screen** (added 2026-06-01): can open unexpectedly when BACK or stray taps
  land on another player's castle. Shows "RESOURCE TRADE" header, transport sliders, CONFIRM
  button. BACK key does NOT dismiss it reliably from this state. Tap the **back arrow** at
  ~**(40, 68)** in 540px snap coords to exit cleanly.
- **"New version found, please install the latest update assets"**
  (added 2026-05-12, recurred 2026-05-14): PNC update prompt with
  CONFIRM at **(540, 1440)**. Wait ~25 s for the loading splash
  ("Checking version number… 100%"). Will land on city view via the
  Mythic Hero / Curio / Alliance Duel popup chain (see below).
- **"Curio" / Rusty Alloy popup** (added 2026-05-13): crafting-status
  card with a GO button. Close X at **(1005, 435)**. Surfaces after
  PNC updates and after long-idle relaunches.
- **"Alliance Duel Begins" popup** (added 2026-05-14): K255 vs K277
  hero-growth scoreboard with quest reminders. Close X at top-right,
  approximately **(990, 585)** (slightly lower than the Mythic Hero /
  Curio Xs because the Duel popup is taller). Surfaces after game
  updates / first-launch-of-day.

The full popup chain after a PNC update is, in order:
`Connection-failed → New-version-found → splash → Mythic Hero →
Alliance Duel → Curio`. Not all four always appear, but they always
appear in that order. Plan for ~30 s of dismissal taps before the
city view is actually usable.

## What this session ran in practice

- Initial launch from Termux → city view → tap WORLD → snap troop
  info → search/Furnace/Lv5 → SEARCH → 4-tap send sequence per free
  slot → close panel → return to Termux → CronCreate next-recheck.
- Per-cycle wall-clock: ~60 s (snap, count, send 1–4 marches, schedule
  cron, return to Termux).
- 10 cycles, 0 aborts, ~+1.45M iron.

## Scripts (added 2026-05-09)

The procedure above is now mostly mechanised. Three scripts compose the
flow; each is image-recognition driven (validated against fixtures in
`tests/pnc/fixtures/`) — none rely on blind tap timing alone.

| Script | Purpose | Exit codes |
|---|---|---|
| `scripts/pnc_popup_dismiss.py` | Walk the launch-popup chain (Connection / Mythic Hero / Curio / Alliance Duel / Battery Saver). Loops until two consecutive clean snaps. | 0 = clean, 1 = unrecognised popup persisted |
| `scripts/pnc_iron_gather.py` | One iron-gather cycle. Ensures world view, reads troop count, opens search, snap-verifies the slider on Lv5 (nudge-with-buttons if not), runs the 4-tap send sequence per free slot. | 0 = ≥1 march sent, 1 = 5/5 already, 2 = abandoned, 3 = setup error |
| `scripts/pnc_sapphire.py` | Sapphire-mine cycle: enter Lv8, recall stale gather, classify visible tiles, pillage skull-no-horns if attempts available else gather an empty mine. | 0 = march sent, 1 = nothing to do, 2 = abandoned, 3 = setup error |

Cron-cadence helper at `src/pnc/cadence.py` (`next_recheck(troops)`)
codifies the schedule heuristic below — pass the result straight to
CronCreate. Tests for all of the above are in `tests/pnc/`.

Run tests with:

```bash
python3 tests/pnc/test_state.py     # vision library
python3 tests/pnc/test_iron.py      # iron-gather decision logic
python3 tests/pnc/test_sapphire.py  # sapphire target selection
python3 tests/pnc/test_cadence.py   # cron-cadence scheduler
```

## Reference: announce-before-act + return-to-Termux

Both are mandatory per the existing playbook:
- `~/say "PNC gather recheck"` BEFORE any tap (gives the user a heads-up
  if they're touching the phone).
- `adb shell am start -n com.termux/.app.TermuxActivity` AFTER the cycle
  completes (so the user can see chat / next cron status).
