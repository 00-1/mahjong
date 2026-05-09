# Game navigation: home → Arcane Puzzle level

The puzzle is buried inside an Events menu. The agent needs to navigate
this flow before it can call `agent.py decide` on a real puzzle screen.

## Steps

The five screenshots in this directory document the path. They're named
in chronological order (01 = first step the agent sees, 05 = arrived at
the level list).

### 1. `01_home.jpg` — game home screen

City view, with various UI elements. **Tap the small fireworks / event
banner in the top-right** (red circle in the reference screenshot). It's
the small panel with a countdown timer next to it. That opens the Event
Center.

### 2. `02.jpg` — Event Center / Daily Event tab

Tap the **Festival Event** tab (red circle on the screenshot). Three
tabs total: Daily Event | Festival Event | Coming soon.

### 3. `03.jpg` — Festival Event list, scroll to "Arcane Puzzle"

Scroll the list down. Tap the **Arcane Puzzle** entry near the bottom
(red circle).

### 4. `04.jpg` — Arcane Puzzle level list, scroll down

Levels 1-7 are visible at top, all completed (checkmark icons). Scroll
down to reach your current level (red arrow points down).

### 5. `05.jpg` — find level, tap **Continue**

The current in-progress level (level 8 in the example) has a yellow
**Continue** button (red circle) and a grey **Restart** button. Tap
**Continue** to enter the level. (Tap **Restart** to start a fresh run
of the same level — useful for retries.)

After step 5, the Arcane Puzzle gameplay screen loads — that's the state
the rest of the toolkit assumes. Call `agent.py start-run --level N`
where N is the level you just continued / restarted, and proceed with
the play loop.

## Calibrated taps (verified 2026-05-09 on Poco F6, HyperOS, 1220×2712)

Phone-pixel coordinates that landed cleanly:

| Step | Target | Phone (x, y) | Notes |
|---|---|---|---|
| 1 | Event banner (top-right) | (1029, 242) | The icon cluster top-right with the event timer. Original-doc location of "fireworks banner" — for the build I tested, this was a generic event banner, not literal fireworks. |
| 2 | Festival Event tab | (610, 400) | Center of the icon, NOT the text label below it. Tapping at the text y (~480) sometimes misses and dismisses the panel — got teleported to a random map tile with the dismissal. |
| 3 | Arcane Puzzle card | (610, 2400) | Card center. The bottom of the panel sometimes has chat overlay — be sure card is fully on screen before tapping; do NOT tap below ~y=2470 in this view. |
| 4 | Scroll to Level 8 | swipe `(600,2200)→(600,1700)` 800ms | Slow scroll. **Wait 3 s after** for the list to fully settle — momentum keeps it moving for 1–2 s, and tapping mid-scroll is unreliable. |
| 5 | Continue button (Level 8) | varies — verify with snap | After the settle, snap and locate Continue's actual y. In our successful run it was phone y≈1981. Position can shift between (1054, 1610, 1854, 1981) depending on how far the list settled. **Don't trust a memorized y across attempts** — re-snap each time. |

## CRITICAL: avoid edge-swipe keepalives

If you have a background loop running `adb shell input swipe X1 Y1 X2 Y2` to keep the phone screen alive (common pattern), **make sure the swipe is NOT at the screen edges**. On HyperOS / MIUI, swipes from x ≤ ~20 trigger the system **Back gesture**.

Symptom: every tap inside the level list appeared to "bounce" the panel back to top — but actually the keepalive was firing a back-gesture between my tap and my snap. Continue button taps registered correctly but the level never opened because Back fired immediately after.

**Safe keepalive options:**
- `adb shell input keyevent 224` (KEYCODE_WAKEUP) every 30 s — wakes screen, no touch simulation, no gesture risk. Use this.
- Tap at a known-safe interior coord (e.g. `(610, 50)` in the status bar area), but slightly riskier — depends on app.

**Unsafe:**
- `adb shell input swipe 5 Y1 5 Y2 ...` — edge x triggers HyperOS back-gesture. **Don't do this.**

Setting `stay_on_while_plugged_in=7` (`adb shell settings put global stay_on_while_plugged_in 7`) keeps the screen on while charging and is enough on its own — you may not need any keepalive at all if charging is reliable.

## Notes for the agent

- **Detecting the level**: easiest is to read it directly from the level
  list (the row label text "Level 8" etc.), but you can also OCR the
  "Level N" header on the gameplay screen to verify.
- **Continue vs Restart**: Restart resets progress on that level (useful
  if you want a fresh structure for testing). Continue resumes from where
  you left off.
- **Animations / popups**: between screens there may be load spinners or
  reward popups. The agent should wait for them to clear before tapping.
- **Returning home after a level**: typically a back button (top-left) or
  a "leave level" prompt. After end-run, the agent navigates back to step
  4 to choose the next level.

