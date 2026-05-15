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

| Element | (x, y) | Notes |
|---|---|---|
| Sapphire Mine icon (city side panel) | (80, 930) | Position depends on what's above; verify with side-panel crop y=400..1200, x=0..200 |
| Lv.8 Mine "Enter" button | (905, 1870) | Yellow CTA on Lv.8 row of the mine list. Lv2 (top) → Lv8 (bottom), each labeled with Output K/hr |
| CONFIRM on Lv.8-entry modal | (780, 1434) | "You can gather Sapphire after teleporting…" — yellow on right |
| "Continuously Occupy" on Pickaxe-promo | (294, 1434) | The OTHER button "View" opens the buy-pickaxe shop — don't tap |
| Page-number jump (Lv.8 mine view) | tap (490, 2080) on the "1" between `< _ Section >` to open the numpad input | Then key in the page number (e.g. 1114) and submit |

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
4. **Find the target tile.** Page 1 is shown by default. If no
   suitable tile is visible:
   - Tap the page number "1" at (490, 2080) — opens a numpad input.
   - Type a deeper page number (user's example was `1114`) and
     submit. (OK-button position is unconfirmed — needs cv2 mask
     verification next attempt.)
   - Or use the `<` `>` arrows for fine navigation.
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

## Open questions for next attempt

- Recall button location and confirmation prompt.
- Main-march "1" button precise coords on the Depart dialog.
- OK button location on the page-number numpad input.
- Pillage Attempts counter coords (header crop) so we can read it
  programmatically.
- What does the side-panel "Sapphire Mine IDLE" mean *while* the
  Excavation Time on Lv.8 mine is still > 0? My theory: IDLE means
  no march is currently out — but the Lv.8 mine has an internal
  Excavation Time independent of personal marches. Needs verification.

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
