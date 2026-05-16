# PNC Sapphire Mine — operational notes (1080×2400)

Operational rules captured from user 2026-05-15 after a failed first
attempt clarified the flow. **Treat as authoritative**; the agent's
prior misread (treating "Excavation Time" as a personal march timer
and "Continuously Occupy" as auto-gather) is corrected below.

## Trigger condition

The Sapphire Mine entry lives in the city-view left-side panel,
*below* the regular Speedup / Build / Speedup rows. Two states:

- **"Sapphire Mine IDLE"** — no active sapphire march out.
- **"Sapphire Mine HH:MM:SS"** — a march is currently gathering;
  the timer counts down to its return.

When to act:

- IDLE → **act now**: tap, enter Lv.8, send a march (see flow below).
- Timer **< 6 h** → **act now**: recall the existing march and send
  a fresh one. Don't wait for IDLE — the recall+restart preserves
  uptime.
- Timer **≥ 6 h** → schedule a cron one-shot to fire at
  `current_time + (timer - 6 h)` and leave it running.

## Calibrated taps (1080×2400)

Updated 2026-05-15 from step-by-step live run with fixtures captured at
each modal — fixtures committed under `tests/pnc/fixtures/` and
referenced by `tests/pnc/test_sapphire.py::test_calibrated_taps_match_*`.

| Element | (x, y) | Notes |
|---|---|---|
| Sapphire Mine icon (city side panel) | (80, 930) | Position depends on what's above; verify with side-panel crop y=400..1200, x=0..200 |
| Lv.8 Mine "Enter" button | (905, 1870) | Yellow CTA on Lv.8 row of the mine list. Lv.2 (top) → Lv.8 (bottom), each labeled with Output K/hr. Header reads "Sapphire Mine" + balance + "Inactive +20%" / Redeem |
| CONFIRM on first-entry modal | (780, 1434) | "You can gather Sapphire after teleporting…" — yellow on right. **Only fires on first-ever entry per session;** subsequent entries skip straight to the Pickaxe Tip. The script snap-and-detects this rather than tapping blind |
| Pickaxe Tip "Don't ask again today" checkbox | (358, 1305) | Was (330, 1245) — missed the checkbox |
| Pickaxe Tip "Continuously Occupy" (left button) | (310, 1462) | Was (294, 1434) — landed too high; the OTHER yellow button "View" opens the Golden Dwarf Pickaxe purchase page (do NOT tap that) |
| Mine Info popup "Pillage" (right yellow) | (772, 1689) | Opens after tapping a skull-no-horns tile. Left "View Info" button is grey, do not tap |
| "Unprotected pit" Don't-ask checkbox | (210, 1310) | Different layout from the Pickaxe Tip — checkbox is on the LEFT, not center |
| "Unprotected pit" CONFIRM (centred yellow) | (540, 1450) | One-button modal; centre CTA, not right-side |
| Depart-dialog "I" loadout (main march) | (575, 275) | Top-row "I" / "II" / "III" / "IV" loadout slots — tap I for main-march troops (whichever loadout slot the user saved as main). Tapping Select All instead would pick weak defaults |
| Depart-dialog Depart button | (540, 2295) | Yellow CTA at very bottom. Same coord works for Select All (which becomes Depart after the loadout fills) |
| Page-navigator < arrow | (330, 2080) | Bottom of mine grid: `< N Section >` |
| Page-navigator > arrow | (745, 2080) | |
| Page-number numpad input | (540, 2080) | Tap the "N Section" text to open a numpad. Then `adb input text 1114; adb input keyevent 66` (Enter). OK-button coord still TBD if Enter doesn't bind |

## Flow (recall + send)

1. Tap **Sapphire Mine** in the city side panel — opens the Lv2..Lv8
   list page.
2. Tap **Lv.8 Enter** at (905, 1870) → **CONFIRM** at (780, 1434) →
   **Continuously Occupy** at (294, 1434) on the pickaxe-promo modal.
   You're now in the Lv.8 mine grid view.
3. **Header check — read the Pillage Attempts counter** (top-right,
   below "Excavation Time"). This determines target type:
   - Pillage Attempts **> 0** → target an **occupied mine with a
     skull icon (no horns)**. The skull-no-horns marker means
     "pillagable" (the no-horns is the differentiator from a
     friendly skull or alliance flag, which is not pillagable).
   - Pillage Attempts **== 0** → target an **empty mine** (no flag
     of any kind on the tile).
4. **Find the target tile.** Page 1 is shown by default.
   - **Pages 1..~1113 are nearly always filled with horned-skull
     tiles** (alliance / strong-realm players we won't pillage).
     User said: "many many early pages are filled with horns" (2026-05-15).
   - **Jump to page 1114 first**, then forward-scan with `>` if no
     skull-no-horns visible:
     1. Tap the page-number text at **(540, 2080)** → numpad opens
     2. `adb input text 1114; adb input keyevent 66` (Enter)
     3. If Enter doesn't dismiss the numpad on a fresh device, fall
        back to tapping the OK button (coord TBD — capture fixture
        next time the numpad is visible)
   - `pnc_sapphire.py` does this automatically with the
     `START_SECTION = 1114` constant; override with `--start-section N`
     or skip with `--no-page-jump`.
5. **Tap the target tile.** Opens the Depart dialog.
6. **Select the main march, NOT "Select All"**. There's a numbered
   button "1" near the **top center** of the Depart dialog — that's
   the saved main-march loadout (heroes + troops calibrated for
   pillage/defense). Tapping `Select All` would auto-pick weak
   defaults; we want the strong loadout.
7. **Depart** at the bottom CTA (~540, 2295) — same coords as iron
   Depart.
8. Return to city; the side-panel Sapphire Mine row now shows the
   active timer.

## Recalling an existing march (timer < 6h)

User said: "as soon as there is less than six hours remaining on the
current gather we want to recall and send troops". The recall is
done from the **Lv.8 mine view header** — there should be a red
**Recall** button (location not yet captured; investigate next
attempt). After recall, follow the send flow above with a fresh
target.

## Sapphire vs iron

Sapphire uses a **separate troop slot** from iron. Iron Troop Info
in the world-map header still shows 5/5 even when sapphire is out.
Confirmed.

## Pillage success verification

User confirmed (2026-05-15): "you just look to see if there's an
**active gather (above the recall button)**". The check is:

1. Wait for the march to land (after a pillage, this includes a
   battle animation — see "Battle skip" below).
2. Snap the Lv.8 mine grid.
3. Find the red Recall button on the left side (`detect_recall_button`).
4. **Look just above the recall button for an "active gather"
   indicator** — visual signature TBD; fixture needed.

If the indicator is present → pillage succeeded, troops are gathering.
If absent → likely defeated or rerouted; try another mine.

The mail/report path is **not** used for verification — we just read
the mine-grid state directly.

## Battle skip

Pillage marches trigger a battle animation before the troops land on
the mine. Currently the animation plays out (~30+ seconds) and the
script hits the SKIP chevron at the bottom-right via
`detect_battle_skip`. User asked us to "find button to fix battle
animation" — there's likely a settings toggle to auto-skip combat
animations. Capture next time we're in a fight; candidates:

- In-battle screen has a gear icon in the top-right.
- Account Settings → Game → "Skip battle animations" toggle.
- Or a per-march "auto skip" checkbox on the Depart dialog.

Once the toggle is wired ON, the battle-animation skip taps become
unnecessary.

## Open questions for next attempt

- Active-gather indicator visual (above recall button) — capture
  fixture after a confirmed-successful pillage lands.
- Battle-skip global toggle location.
- OK button on the page-number numpad — verify Enter (keyevent 66)
  works; if not, capture numpad fixture and pin the OK coord.
- Recall confirmation prompt (after tapping Recall, does a
  "Recall march?" dialog appear? coord for its CONFIRM is unknown).
- Pillage Attempts counter — current detector
  (`read_pillage_attempts_available`) is presence-only; doesn't
  distinguish 0 vs N>0. Needs a Pillage-Attempts:0 fixture to extend.
- What does the side-panel "Sapphire Mine IDLE" mean *while* the
  Lv.8 mine's own Excavation Time is still > 0? Theory: IDLE means
  no personal march is out; the mine's Excavation Time is a global
  reservoir, not a personal timer. Confirmed by 2026-05-15 walkthrough
  (we entered while IDLE, saw Excavation Time 1d 14:08:24, sent a
  march, returned to a personal timer in the side panel).

## Scripts (status as of 2026-05-09)

All four planned scripts are now implemented and validated against
fixtures in `tests/pnc/fixtures/`. The cron infrastructure stays —
scripts are what the cron prompt should `subprocess.run()` instead of
an LLM rerunning the procedure from notes.

| Script | Status | Live-tested? |
|---|---|---|
| `scripts/pnc_popup_dismiss.py` | done | yes — dismissed Mythic Hero in 2 rounds |
| `scripts/pnc_iron_gather.py` | done | not yet (built offline against fixtures) |
| `scripts/pnc_sapphire.py` | done — recall+pillage+depart wired | yes — pillage flow ran end-to-end manually |
| `src/pnc/state.py` | done — `detect_popup`, `find_mine_tiles`, `read_sapphire_sidepanel`, `read_troop_count`, `in_world_view`, `read_search_panel_lv` | covered by 10-test suite |
| `src/pnc/cadence.py` | done — `next_recheck(troops)` returns delay seconds + reason | covered by 6-test suite |

Open work tracked elsewhere: pillage-attempts header OCR, sapphire
timer HH:MM:SS parsing, pillage-success Mail check, page-jump (1114)
implementation. None block the existing scripts; they just expand
their decision space.

Run all PNC tests:

```bash
for t in tests/pnc/test_*.py; do echo "=== $t ==="; python3 "$t" || break; done
```

Same kill switch (Ctrl+C / killing the script) applies as before.
