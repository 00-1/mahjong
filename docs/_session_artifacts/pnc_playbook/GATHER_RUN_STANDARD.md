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
| Lv-slider thumb (drag) | from `(1000, 1985)` to `(550, 1985)`, 1500ms | Drops from Lv7 (default) to ~Lv4. Slow drag is critical — short drags don't register |
| Lv-slider plus button | (1015, 1970) | Nudge up by 1 (e.g. Lv4 → Lv5) |
| SEARCH button | (540, 2280) | Bottom of search panel. Re-tap to cycle to next nearest mine |
| Gather marker | (520, 650) | Small troop figure above the "Gather" text. Camera auto-centres after SEARCH |
| Bottom Select All / Depart | (540, 2295) | The big yellow CTA at the very bottom of the Depart dialog. Same coords for both — "Select All" becomes "Depart" after troops fill |
| Search-panel close (X) | (1015, 1530) | Top-right of the search bottom-sheet |
| Cancel exit-game prompt | (294, 1434) | When `keyevent 4` triggers "Exit the game?" |
| Mythic Hero promo close (X) | (1005, 390) | Top-right of the popup card after a connection-restore |
| Connection-failed CONFIRM | (540, 1440) | Reconnect dialog after PNC loses network |

The slider quirk is worth re-reading: a short drag from the thumb does
nothing, only a 1500-ms drag spanning ≥30% of the track moves the
value. After landing roughly, nudge with the + button at (1015, 1970)
— each tap = +1 level.

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
