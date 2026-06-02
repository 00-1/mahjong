# Puzzles & Chaos: Frozen Castle — Exploration Notes

**Package:** `com.global.pnck`
**Launcher activity:** `com.eyu.kylin.riversdk.AtlasPluginDemoActivity`
**Version:** 1.91.00
**Account state at start (2026-05-03):** VIP 12, Power 305,467,442
**Realm:** K255

## Announce before touching the phone

The phone is shared with the user, who may be playing PNC manually at any moment. **Before kicking off any test, gather flow, exploration, or other action that issues taps/swipes/`monkey`/`am start`, call `~/say "<short heads-up>"` FIRST.** Gives the user a chance to intervene before the action lands.

Read-only operations (`dumpsys`, `adb devices`, `adb exec-out screencap`, helper scripts running with `SKIP_SNAP=1`) don't need the heads-up — they don't affect the user's session. Anything that drives input does.

When a cron-scheduled prompt fires, its first action must also be `~/say` so the user knows the auto-run is starting.

## Use judgment — don't be a click-tool

When you snap, **think about what's on screen**, don't just check for the expected button. If something's off — wrong realm, wrong screen, popup blocking, button missing, troop count changed since last snap — diagnose and recover. Don't blindly retry the planned tap sequence. Examples that have actually happened:

- Header showed "Viewing Realm 66" + no search magnifier → recovered by tapping WORLD twice (city → world bounce).
- Search SEARCH cycled to a mine we'd already sent a march to → tapped SEARCH again to skip rather than committing a duplicate.
- Troop count changed from 4/5 to 5/5 mid-cycle (a march arrived) → recomputed plan based on current state.
- Cold launch landed on an event modal instead of city view → would dismiss with back keyevent before proceeding.

**Treat each snap as an open question, not a checkbox.** Be willing to deviate from the planned sequence. Narrate via `~/say` when you're recovering from something unexpected, so the user knows you're adapting rather than stuck.

## CronCreate scheduling: never schedule for a past time

When scheduling the next maintenance cron, **always check `date "+%H:%M"` first** and pick a target time strictly *after* the current time. CronCreate one-shots silently no-op if their target time has already passed by the time you create them — they auto-delete and never fire. There's no warning.

This bit us 2026-05-08: I scheduled "02:15" when it was already "02:39", expecting the cron to fire ~36 min later. It never fired. Maintenance loop went dead for ~5.5 hours.

**Why it's easy to mis-time:** the maintenance cycle takes longer than estimated. Over 4 march sends with N+1 SEARCH skipping, tab corrections, occasional misclicks, and snap-read-decide loops, a cycle is realistically **30–60 minutes** of wall-clock — not the few seconds it feels like in the moment.

**Rule:** When picking the cron's `M H DoM Mon *`:
1. Run `date "+%H:%M"` immediately before the CronCreate call.
2. Compute the target time = `current_time + max(soonest_slot_offset, 5 min buffer)`.
3. If `target_time < current_time` (you crossed an hour boundary, or you're already past the predicted slot opening), pick `current_time + 5 minutes` instead and let the cron see the actual state.
4. Sanity check: target time MUST be in the future at the moment of scheduling.

For overnight loops, this matters less because cycles are 60+ min apart and rarely tight against the boundary — but it's the kind of bug that's invisible until you check why nothing's happened, hours later.

## Bottom-nav menu inventory (investigation log)

Per request, between maintenance cycles when 5/5 already, pick one bottom-nav menu to explore. Document layout/sub-tabs/observations here.

| Menu | Phone (x, 2580) | Sub-tabs / contents | Notes |
|---|---|---|---|
| WORLD/HOME | 140 | (toggles city↔world) | calibrated |
| HERO | 340 | HERO / NOT OBTAINED / BAG / Curio Warehouse | per existing notes |
| QUEST | 510 | TBD | not yet investigated |
| BAG | 680 | RESOURCES / SPEEDUPS / MILITARY / RARE / OTHER (top: BAG / DIAMOND SHOP) | investigated 2026-05-08. RESOURCES tab shows chests/items grouped by type. 131 unopened chests visible. |
| MAIL | 840 | TBD | not yet investigated |
| ALLIANCE | 1010 | Alliance War / Alliance Event / Alliance Research / Alliance Shop / Alliance Territory / Alliance Gift / Alliance Bulletin (bottom row: Alliance Teleport, Alliance Mail, Request, Alliance Help, Alliance Treasury) | Alliance Territory used for furnace gather flow |
| RANK | 1160 | TBD | not yet investigated |

## Always expect to start in Termux

Because we always return Termux to the foreground at the end of every run, **the next run always starts in Termux**, not in PNC. The first action of any PNC operation is therefore always to launch PNC (`adb shell monkey -p com.global.pnck ...`). Don't assume PNC is foregrounded just because we used it earlier in the conversation; the previous run ended with a return-to-Termux. The Termux→PNC transition has a fade (see fade table) — give it a small sleep before snapping.

## Always return to Termux when done

After ANY PNC interaction — sending marches, just checking march timers, observing state, anything — the last step before yielding is **always** to return Termux to the foreground:

```
adb shell am start -n com.termux/.app.TermuxActivity
```

This applies even for read-only checks (e.g. snapping the world map to read gather timers for scheduling). The user can't see the conversation if PNC is sitting in the foreground, and they often passively watch the screen to know when a run ended. Don't leave PNC up unless explicitly asked to.

## Screen geometry
- Phone: 1220 x 2712 pixels (Poco F6)
- `snap.sh` resizes to 33% (≈403 x 895) JPEG q70 to fit Read context budget
- Conversion: phone_x = small_x × 3.027, phone_y = small_y × 3.030
- Coordinate quirk: in city/world map views, world map tiles are isometric and click-to-tile mapping is non-trivial — clicks must hit the tile center, not the visual icon. Use the SEARCH flow which auto-centers the camera on the target tile, then tap the on-screen action label (e.g. "Gather") rather than the building art itself.

## Bottom nav (city view)
Phone y ≈ 2580 for icon centers. From measurements:
| Button | phone x | Notes |
|---|---|---|
| WORLD / HOME | 140 | Toggles between city view and world map |
| HERO | 340 | Opens hero roster panel (12+ heroes mostly Lv.350) |
| QUEST | 510 | Opens **Daily Quest** panel. Tabs: DAILY QUEST / MAIN QUEST / ALLIANCE ACTIVITY. Daily tasks with GO buttons + diamond/coin rewards. **Close: `keyevent 4`** (no exit-game prompt). |
| BAG | 680 | (untested) |
| MAIL | 840 | Opens **MAIL**. Bottom-tabs: LORD / ALLIANCE / REPORT / MILITARY / SYSTEM / FAVORITE. **LORD = gather-completion mails** with mine coords + amounts: Lv.7 Furnace ≈ 20K iron, Lv.7 Farm/Lumberyard ≈ 400K, Alliance Furnace ≈ 159K iron per share. **REPORT = war/rally outcomes** (Victory/Defeat). Close: `keyevent 4`. |
| ALLIANCE | 1010 | Documented elsewhere — Alliance panel with War/Event/Research/Shop/Territory/Gift/Bulletin. Close: X at (1120, 287). |
| RANK | 1160 | (untested) |

**Modal close-method varies:**
- X at (1120, 287): Alliance panel, Alliance Building, Kingdom Map, BAG/Talent overlays, depart_dialog, tile_action.
- `keyevent 4` (back): Daily Quest, MAIL (and likely sub-panels of those).
- Empty-map tap (610, 1900): castle action panel.
- Back-arrow (120, 180): stacked sub-panels (castle_buff, arcane_barrier).
- CANCEL (348, 1636): exit-game prompt itself.

If unsure, look for an X close icon in the panel's header. If none visible AND the panel is a list-style overlay (not over the world map), `keyevent 4` is usually safe.

Tapping HERO opens the **HERO** panel: header "HERO", currency (449,427), Recruit button top-right, sub-tabs Hero Bond / Recd Lineup / Filter, a 3-column grid of hero cards (each: portrait, +N stat boost, level, name, star rating). Sub-bottom-tabs of HERO panel: HERO | NOT OBTAINED | BAG | Curio Warehouse. To exit: hardware back (`adb shell input keyevent 4`).

## Side action panel (city view, left side)
- **Speedup** (counter shows speedup item count)
- **Build** — IDLE / queued construction status
- **Research** — IDLE / queued research status
- **Gathering** — timer until gathering march returns (per slot)

## Right-side side panel (events / shop)
War Momentum, Rewards Center, VS (PvP event), Limited Offer, 1st Top Up, Top-up Gifts, plus rotating event icons. Avoid tapping these — they tend to be limited-time purchase pop-ups.

## World map view
Activated by tapping WORLD (bottom nav) or HERO (also lands on map with troop info open).
- Top header now shows **X / Y coordinates** of camera focus and a search/star/zoom-out cluster
- **Troop Info (n/5)** panel top-left lists all current marches:
  - Each row: action icon (gathering = pickaxe-style, rallying = flag, etc.) + label (Gathering / Rallying) + countdown timer + return arrow
  - Max 5 marches simultaneously — if 5/5, must wait for one to return before sending a new gather
- Bottom-left has two stacked icons:
  - **Pin/locate** (top, ≈ phone y=2030) — recenters on player castle
  - **Search** (bottom, ≈ phone (80, 2170)) — opens resource search panel

## Resource search flow (THE main task)

Tap the **search magnifier** at phone (80, 2170) → search panel opens as a bottom sheet over the world map.

**Resource type tabs** (highlighted in gold when selected):
- Monster
- Monster Den
- Farm = food
- Lumberyard = wood
- Quarry = stone
- **Furnace** = **iron** ← this is what we always want

The tab row is **horizontally scrollable** and only shows ~4 tabs at a time. After a fresh PNC launch the panel often defaults to the **Monster** tab (leftmost), not Furnace. To switch:

1. Snap full (`~/snap.sh`) so you can see the tab row at phone y≈2030.
2. If Furnace isn't visible: swipe the tab row left — `adb shell input swipe 1150 2090 100 2090 500`.
3. Re-snap; tap the Furnace tab at the position it now occupies (typically ~(1029, 2030) once scrolled fully right).
4. The level slider re-binds to Lv 1–7 for Furnace and shows "5/7" / "Lv.5" once selected.

Always check the tab is on Furnace AND the slider says Lv.5 before tapping SEARCH; otherwise you'll be searching for monsters or the wrong resource type.

**Level slider:** 1–7. We always use **Lv.5** (default in current session was already Lv.5).

**"Show occupied Resource Sites"** — keep UNCHECKED. With it unchecked, search results filter to sites that aren't currently being gathered.

**SEARCH button** at phone ≈ (620, 2575). Tapping it:
- Pans the camera to the nearest matching mine
- Shows an info card with `K<realm> X:## Y:##` and current resource amount
- Shows a floating **"Gather" label with a helmet/troop icon** above the mine
- Tapping SEARCH again cycles to the next nearest mine

### Verifying a mine is safe to gather

The "Show occupied" filter is **not enough** — it only excludes mines where someone is already gathering. It does NOT exclude mines where someone is **marching toward** the mine. Before committing, visually confirm:

- **No dashed march lines** ending at the mine. Lines come in three colours, all of which mean "abort this mine":
  - **Green dashed** = friendly/alliance march incoming
  - **Grey dashed** = neutral march incoming
  - **Red dashed** = enemy march incoming
- The resource amount on the info card should equal the **mine's max** (Lv.5 Furnace = **10,000** iron). If it shows less (e.g. 9,958), someone is already there gathering even if no march line is visible — skip.
- An "Info" label instead of "Gather" floating over the mine = mine is occupied — skip.

**If any of those conditions fail, tap SEARCH again to find a different mine. Do NOT abandon by tapping the X (which closes the search panel).**

#### March line vs search-highlight ring (don't confuse them)

After SEARCH, the selected mine is wrapped in a **green dashed CIRCLE/RING** that's the search-result highlight — that's NOT a march line, even though it's green and dashed. Distinguishing them:

- **Search highlight ring**: a closed circular/elliptical loop centered on the mine tile. Both ends meet. No external endpoint. Always present after a successful SEARCH.
- **March line**: a *linear* dashed segment with two distinct endpoints — one at a castle (origin) and one at the mine (destination). It enters the highlight ring rather than tracing it. Multiple march lines can be present pointing at the same mine.

**Concrete check:** trace any green/grey/red dashed segment with your eye — does it form a closed loop centered on the mine (highlight) or does it run from somewhere else *into* the mine (march)? If any non-loop dashed segment terminates at or very near the mine, **abort the mine**. Re-tap SEARCH to cycle.

(Lesson learned 2026-05-03: an X:317 Y:561 mine was approved as clean despite a clear green linear march line entering from the upper-right. The closed search ring around the tile was correctly identified, but the linear segment was overlooked. Look for both.)

### Sending the march (verified)

Once a mine is verified clean — **execute the rest as one fast sequence**, no waiting between steps. After SEARCH lands on a clean mine there's a race window where other players can grab it; every second of delay raises the abort rate.

1. Tap the **Gather** marker (it's a small troop figure above the floating "Gather" text — not really a helmet) at phone ≈ **(605, 712)** when search panel is still open and camera is centered on the mine.
2. The **Depart** troop selection dialog opens. It has TWO "Select All" buttons:
   - **Upper "Select All"** (≈ phone (605, 797)) — selects HEROES (fills the 5 hero slots with top-power heroes Lv.350). **DO NOT TAP** — we want no heroes.
   - **Bottom "Select All"** (≈ phone (605, 2585), the big button at the bottom of the dialog with `00:00:00` timer above it) — auto-selects TROOPS. **This is the one we want.**
3. After tapping the bottom Select All, the troop sliders auto-fill (e.g. 6,154 Witchers for a 10K Lv5 furnace), the march time populates (~3:29 from our castle for X:290 Y:554), and the bottom button changes to **"Depart"** at the same coords (≈ phone (605, 2585)).
4. Tap **Depart** at phone (605, 2585) to send. The dialog closes; Troop Info gains a `Marching MM:SS` row and a green dashed march line is drawn from castle to mine.

**If a confirmation prompt appears warning about other players going to the mine: abandon the attempt** (don't confirm; back out and search again).

### View detection before any batch click

PNC's default launch screen is **city view (inside the castle)**, NOT world map. Always snap and check before issuing world-map clicks like (80, 2170) — those coords land on BAG in city view.

To get from city → world: tap **WORLD** at phone (140, 2580) (bottom-left of bottom nav).

### Foreign-realm recovery (CRITICAL pre-flight check)

PNC's "world map" view can also be **viewing a foreign realm** (rally targets, alliance views, recently visited realms). Tell-tale signs in the snap:
- Header shows **"Viewing Realm <N>"** banner near the top.
- Header coords still show but the surrounding territory is unfamiliar (foreign alliance castles).
- **The search magnifier is absent from the bottom-left.** PNC removes it when you're not in your home realm.

**If you tap (80, 2170) while in a foreign realm, you hit nothing useful — and the next-coordinate tap (the SEARCH button at 620, 2575) lands somewhere unintended (often BAG in city view, depending on what dialog comes up).** This is exactly the failure mode we hit in the 2026-05-03 maintenance run.

**Pre-flight check before any search click:** snap. Confirm BOTH:
1. No "Viewing Realm <N>" banner present.
2. Search magnifier visible bottom-left around small (35, 705) / phone (105, 2135 area).

If either check fails, recover by **tapping WORLD twice** (with a pause between):
- First tap: enters our city view (city is always our castle).
- Second tap: exits to world map, this time centered on **our** realm (K255), with the search magnifier present.

Then re-snap and re-verify before issuing search clicks. Don't proceed until those two conditions both hold.

### Cycling SEARCH past already-targeted mines

The SEARCH button cycles through the nearest unoccupied Lv5 furnaces. The "occupied" filter only excludes mines being actively *gathered*, not mines we ourselves are *marching toward*. So cycling can land on mines we've already sent a march to — info card shows 10,000 iron and "Gather" label, but tapping Gather would conflict with our own pending march.

How to spot one of "our own" pending mines: the info card matches a coordinate from a Marching row in our Troop Info panel. Or the camera shows our own green dashed march line ending exactly at this mine.

**Action:** tap SEARCH again to cycle to the next one. Don't waste a march. Don't close the panel via X — that resets the cycle.

### SEARCH cycle reset (batch-skip pattern — important speed optimization)

The SEARCH cycle position resets after a few seconds of idle (between your tap and the next, while you're snapping/reading). The reset puts the cycle back to "nearest first". Practically, this means **the very first result after a fresh SEARCH is always the nearest unoccupied mine — which is almost always one you just sent a march to in this maintenance pass.**

Don't waste a snap+verify on it. Pre-emptively skip:

- Sent 0 marches in this run so far → tap SEARCH once, snap, verify (normal flow).
- **Sent 1 march already → tap SEARCH twice in a row, snap on the second, verify** (the first surfaces the mine you just sent to; the second cycles past it).
- **Sent 2 marches → tap SEARCH three times, snap on the third.**
- Sent N marches → tap SEARCH `N+1` times.

Each skip-tap can chain in one bash call without sleep, e.g. `adb shell input tap 620 2575 && adb shell input tap 620 2575 && sleep 1.0 && ~/snap.sh` for 1-march-already-sent. The animation between rapid taps is short — the tile camera-pan only needs to settle for the *final* tap.

If the snap shows a still-already-targeted mine after your N+1 taps (game changed state, someone else's march arrived), one more SEARCH tap to advance.

This eliminates the "always wasting one verification on an own-march mine" cycle that was the dominant overhead of multi-send maintenance passes.

## Alliance furnace (one slot reserved)

**One of our 5 march slots should always be gathering the alliance furnace** — a special tile labelled **`[Ax7] Alliance Furnace`** (our alliance). This is distinct from regular Lv5 furnaces:

- **Located just north of our castle.** Off-screen from the default castle-centered view; you have to swipe north on the world map to see it. SEARCH does NOT find it.
- **No clean-check required.** No issue with other players targeting it; the "no dashed lines, full amount" rule doesn't apply. Just go.
- **Much longer gather duration.** ~21 hours vs ~1 hour for regular Lv5 furnaces. This is how you recognize a slot is *already on the alliance furnace*: any Troop Info entry with `Gathering 20:00:00`-ish (or any 20h+ remaining) IS the alliance-furnace gather. The progress bar on the row shows fraction complete — useful when the absolute time has decremented and you can't tell from the timer alone whether it's an alliance-furnace gather mid-way through or a regular gather just starting.

**Maintenance rule:**
- If Troop Info has any 20h+ Gathering row → alliance furnace covered, send remaining free slots to regular Lv5 furnaces via SEARCH flow.
- If Troop Info has NO 20h+ Gathering row and we have a free slot → send that slot to the alliance furnace (manual scroll-to-tile flow, separate from the SEARCH flow).

**`[A7A] Alliance Furnace` is a DIFFERENT alliance — do NOT gather from it.** Same building art, different prefix in the label. Watch the prefix carefully when scrolling.

### Navigating to the alliance furnace via the Alliance menu (preferred)

No scrolling needed. Use the menu:

1. From world map, tap **ALLIANCE** in bottom nav at phone **(1010, 2580)**. Opens the Alliance panel.
2. Tap **ALLIANCE TERRITORY** card at phone ≈ **(100, 1636)** (or wherever it appears in the alliance grid — labels can shift). Opens "Alliance Building" panel with bottom tabs: Territory Building / Economic Building / Warehouse & Hospital / Special Building.
3. Tap **Economic Building** tab at phone ≈ **(470, 2645)**. Shows Alliance Farm / Alliance Lumberyard / Alliance Quarry / **Alliance Furnace** cards.
4. The Alliance Furnace card shows current coords (e.g. `X:304 Y:498`), status (`Gathering` in green if currently being gathered), and remaining resources.
5. **Tapping the card body** (e.g. (210, 1455)) — observed: teleports world map camera to the tile area but does NOT open a Gather UI. Returns you to world map centered on the furnace.
6. **Tapping the coord link `X:Y` text** specifically (e.g. (236, 1310)) — UNTESTED, was about to try when adb dropped. Likely also teleports camera, possibly with a more precise center or with a Gather UI overlay.

### Sending a march to the alliance furnace (verified)

End-to-end verified 2026-05-03 21:04 — alliance furnace march sent successfully.

Full sequence (all phone-pixel coords):

1. **Alliance bottom-nav:** tap **(1010, 2580)**.
2. **Alliance Territory** card: tap **(100, 1636)**. Opens "Alliance Building" panel with bottom tabs.
3. **Economic Building** tab at the bottom: tap **(470, 2645)**.
4. **Pin icon** (small location-marker) next to the X:Y coord on the Alliance Furnace card: tap **(115, 1310)**. The panel closes and the world map camera teleports to the alliance furnace area, header showing X:304 Y:500-ish (camera focus offset slightly from the tile at 304/498).
5. **Tile tap:** tap **(640, 1300)**. The actual alliance-furnace tile is **upper-right** of where the pink heart-flower decorations are; tapping near (530, 1545) or (515, 1545) hits the neighbouring player castle "[Ax7] jinyed" at X:302 Y:500 and opens a Trade/Message/Reinforce popup — wrong target. (640, 1300) lands cleanly. The action panel appears with **More Details** on the left (~333, 1394) and **Gather** on the right (~878, 1394) plus the info card showing `K255 X:304 Y:498` and remaining resources.
6. **Tap Gather:** **(878, 1430)** — slightly *below* the visible button center to land reliably (878, 1394 just barely missed in our test). Opens the Depart dialog.
7. **Bottom Select All:** **(605, 2585)** — auto-fills troops. Capacity is **larger** than regular Lv5 furnaces (260,976 vs 245,976 in our test), and **more troop types** are listed (Sword Saint, Witcher, Battlefield Rose, Windrunner, Iron Catapult, Royal Guard). Heroes stay empty.
8. **Tap Depart:** **(605, 2585)** — same coord, button morphs from Select All to Depart. March sends; Troop Info gains a `Marching MM:SS` row pointed at the alliance furnace.

### Pitfalls observed

- **Tile-tap target is offset from the floating label and from the building art.** Don't try to estimate from those; (640, 1300) is the calibrated coord when teleported via the menu pin.
- **Player-castle popup recovery:** if you accidentally hit the neighbouring castle, tap an empty area of the map to dismiss — DO NOT press back. Pressing back escalates to an "Exit the game?" Tip dialog. If you're in that dialog, tap **CANCEL at (115, 1636)** to recover; CONFIRM kills PNC.
- **`Gathering` (green) status on the Economic Building card means an alliancemate is currently gathering** but does NOT prevent us from also sending a march. Multiple alliance members can gather simultaneously; the tile capacity is shared.
- **Notification bar** at very top of screen — don't tap (50, 100) or similar to "dismiss" anything. That pulls down system shade and can switch focus to Termux.
- **A Daily Quest popup** can appear on a fresh launch; press back to dismiss before navigating menus.

## Rally vs march

In Troop Info, the status field of each row tells you what the slot is doing: `Marching` / `Gathering` / `Returning` / `Rally` (or `Rallying`). **A Rally row consumes a march slot and cannot be redirected** to gathering — wait for it to complete. Don't try to "free" a Rally slot. The timer on a Rally row indicates when it'll free up; treat it the same as any other timer for scheduling the next maintenance check.

## March slot accounting

Max 5 simultaneous marches. Read the count from the **Troop Info (n/5)** panel top-left of the world map. Each row shows status (Gathering / Marching / Returning) + countdown. If 5/5, must wait — tapping Gather while full will likely show a friendly error (untested but expected; check March Info first either way).

**Gather → return cycle:**
- `Marching MM:SS` — troops travelling to the mine. Outbound was ~3:30 to (X:290, Y:554) from our castle.
- `Gathering MM:SS` — troops at the mine collecting. Time depends on mine size and gather speed; observed ~38–51 min for a fresh Lv5 furnace.
- (Returning) — back-trip after gathering completes; mirrors the outbound time (~3:30).
- Slot frees only when troops are physically back at castle. **Total wait until next send-able slot ≈ Gathering remaining + outbound travel time.**

When scheduling a recheck for the maintenance loop, target `min(gathering_remaining_per_slot) + travel_time - 1min` so we hit the slot just as it opens.

## Arcane Barrier (shield) — apply BEFORE every gather run

**Why:** if our gather march arrives at a resource tile while another player is there, we'd otherwise auto-attack them. With Arcane Barrier active we just retreat instead. No combat, no risk. We have a large stockpile of 2-hr shields; use freely.

**Recognize active state:** in the Castle Buff panel (see flow below), the Arcane Barrier row shows `Time Left: HH:MM:SS` with a yellow border. If active, exit out — already covered. If row shows the normal description "Protects your Castle from attacks and scouts." with no time, you're unshielded — apply.

**Flow (verified 2026-05-03):**

1. World map, centered on castle (use WORLD-twice bounce if not).
2. Tap dead-center for MY CASTLE: phone **(610, 1390)**. Castle action panel opens.
3. Tap **Castle Buff icon** (icon, not text) above the "Castle Buff" label — phone roughly **(610, 1170)** to **(610, 1240)**. The icon is a small castle/flag cluster above the text. Castle Buff list panel opens.
4. Find **Arcane Barrier** row (2nd item under MILITARY, between War Frenzy and Troop ATK). Tap the row OR its yellow `>` arrow. **Calibration warning:** the row hit-areas in this list are ~50–100 px offset from where the visual rows appear in a 33% snap. If the wrong row opens (e.g. Troop ATK when you aimed at Arcane Barrier), back out and tap **higher** by ~150 phone-pixels and retry. The arrow at phone ≈ **(1110, 1394)** (which visually looks like War Frenzy's arrow) actually opened Arcane Barrier. Trust the hit, not the visual.
5. Arcane Barrier sub-panel opens with shield options (2-hr / 8-hr / 24-hr / 12-hr / 3-Day). For routine gather runs use the **2-hr USE button** — phone **(1075, 1480)** (verified). Same calibration warning: the USE button visually appears around small y=525 (phone ~1590) but the real hit area is ~100 phone-px higher.
6. Confirm: a brief "Used Arcane Barrier (2-hr) x1" toast appears, and back in the Castle Buff list the Arcane Barrier row now shows `Time Left: 02:00:01` with a yellow border.
7. Back out (`keyevent 4`) and proceed with gather flow.

**If shield timer is very low** (e.g. < 5 min) and you want to refresh: same USE flow, but PNC may show an "extra prompt" to confirm replacing the active shield. Tap CONFIRM (likely ~(605, 1636) — TBD).

**War Frenzy interaction:** if War Frenzy state is active (after launching attack/scout/rally), Arcane Barrier won't be available. Don't attack from this account during the maintenance loop. Gather marches don't trigger War Frenzy.

## Coordinate calibration is unreliable for novel UI; use cursor preview + commit

The visual position of UI elements in a 33%-downsized JPEG does not always map cleanly to the actual hit area. Sub-panels in PNC sometimes have hit-areas that are 50–150 phone-px offset from where the button *appears*. A tap that visually "should" land on the right control will sometimes hit a neighbouring one.

**Cursor preview pattern** (use any time you're not confident a coord will land):
```
adb shell settings put system pointer_location 1
(adb shell input swipe X Y X Y 1500 &); sleep 0.5; ~/snap.sh
# Read snap; look at "X: ## Y: ##" overlay at top + crosshair position vs target
adb shell settings put system pointer_location 0
# When confident: adb shell input tap X Y  (a NEW quick tap, not the swipe-hold release)
```

**Important:** the swipe-hold release is interpreted as a long-press, which does NOT trigger button actions. Use the swipe-hold purely to visualize where the tap lands. Then send a separate `adb shell input tap` to actually click.

If the cursor lands away from the intended target, adjust Y first (sub-panels seem more often Y-offset than X), re-preview, then commit.

## Tile tapping: trust the camera-center, not the visual building art

Click accuracy itself is fine — verified 2026-05-03 with Android's `pointer_location` overlay (`adb shell settings put system pointer_location 1`). A `adb shell input tap 610 1390` lands at exactly X=610, Y=1390 on screen. So when a tile-tap goes to the wrong target, it's a *tile-identification* error, not a click error.

**Key heuristic:** when the world-map camera is centered on a tile (after a locate/teleport/recenter operation, or by default on launch for our castle), the tile's interactive center is at the **dead-center pixel of the visible map area: phone (610, 1390)**.

- Don't estimate the tap position from where the building art is rendered — iso projection offsets the art relative to the tile center, neighbouring tiles overlap visually, and labels float above-left of their tile.
- Don't estimate from where the floating "MY CASTLE" / "[Ax7] Alliance Furnace" label appears — labels offset.
- Just tap (610, 1390) when the camera is recentered on the target tile.

This applies to:
- **Our home castle** on world map default view → (610, 1390) hits the castle action panel (Castle Buff / Reinforcement / Enter Castle / Info / Appearance).
- **Tile that we just teleported to** via Alliance Building → pin icon — the camera ends up centered on (or very near) that tile, so (610, 1390) is the right tap. Note: for the alliance furnace specifically, the camera ends up at a slight offset (Y:500 not Y:498), so (640, 1300) — slightly upper-right of dead-center — is what worked. If dead-center misses on a teleport, try one tile up-right of center.
- **A SEARCH-result mine** — same logic, camera centers on the matched mine, tap (610, 1390) (or the upper-right offset if needed) for the action panel.

(Lesson learned 2026-05-03: spent ~10 attempts hitting neighbouring player castles around home because I was estimating tap position from the visible "MY CASTLE" label and building art instead of just trusting "default center = home".)

## Calibrated tap targets (verified, gather flow)

These are the calibrated phone-pixel coordinates for the gather flow. Tested and working as of 2026-05-03 on Poco F6 (1220x2712). Don't recompute every time — just use these.

| Target | Phone (x, y) | Context | Notes |
|---|---|---|---|
| WORLD bottom-nav | (140, 2580) | City view | Switches to world map. Same coord on both views (highlighted on the active view). |
| Search magnifier | (80, 2170) | World map only | Opens resource-search bottom sheet. **In city view this lands on BAG** — always confirm view first. |
| SEARCH button (panel) | (620, 2575) | Search panel open | Runs the search. Re-tap to cycle to the next nearest mine. |
| Gather marker | (605, 712) | After SEARCH lands on a mine | Small troop figure above the floating "Gather" text. Camera auto-centers each search; marker has been stable across multiple mine coords (X:282 Y:486 and X:290 Y:554 both used (605, 712)). |
| Bottom Select All / Depart | (605, 2585) | Depart dialog open | Big bottom button. First tap auto-fills troops; the same button morphs to "Depart" — second tap sends the march. |
| Upper Select All | (605, 797) | Depart dialog open | **DO NOT TAP** — selects all heroes (we want zero heroes). |

**If clicks miss:** assume an in-game UI update or a different device, not a transient. Re-snap, identify the target visually, convert via `phone_x = small_x × 3.027, phone_y = small_y × 3.030`, update the table above. Suspect drift if: the Gather tap doesn't open the Depart dialog, the SEARCH tap doesn't center the camera, or the WORLD nav tap toggles into a non-map screen. Don't blindly retry — recalibrate.

## Known fade transitions (need a small sleep before snap)

The snap-driven rule has a few exceptions where the screen is mid-fade and a snap during the fade returns a darkened/translucent frame. Insert a small sleep before snap in these cases:

| Transition | Symptom | Fix |
|---|---|---|
| Termux → PNC foreground (`monkey` launch when PNC was backgrounded) | First snap shows world map *behind* a translucent dark overlay; partial UI text visible but dimmed | `sleep 1` (or up to `sleep 2`) before snap, OR snap once, detect fade, sleep 1, re-snap. ~1 s is enough — was tested as the full `sleep 6` originally but that was overkill. |
| Cold app launch (PNC was killed) | Mostly black or partial logo | `sleep 2` then snap, retry up to 2–3 times until resource bar appears (per cold-launch handling). |

Update this table any time we observe another fade. The principle stands: if a snap looks half-rendered/translucent/dim, that's the cue — bump sleep up by ~0.5–1 s for that transition specifically, not globally.

## Narrate via ~/say for everything the user should hear

The user often has eyes on the phone, not the Termux conversation. Chat text alone is invisible to them in that moment. **For every meaningful chat-text update during a PNC run, also call `~/say "<short sentence>"` with the same essence.** Rule of thumb:

- Short progress markers ("searching", "mine clean, gathering", "march one sent") → `~/say` only is fine.
- Decisions or problems ("wrong realm, recovering", "tap missed, retrying", "found a march line, skipping") → `~/say` AND chat (chat can be longer for diagnosis).
- Final summaries / scheduled-cron info → both, with the `~/say` being the one-sentence headline of the chat-text version.

`~/say` is fire-and-forget so it doesn't slow anything down. The cost of skipping it is the user asking "what just happened?" because they couldn't see the chat.

## Game UI map

`~/pnc_explore/UI_MAP.md` is a living document of the game's structure: persistent shell, world/city views, every panel we've identified, calibrated coords, the canonical flow sequences (search-and-gather, alliance furnace, arcane barrier), and a prioritised list of unexplored menus to map next. Read it whenever planning a new flow.

## Autonomous exploration queue

`~/pnc_explore/EXPLORE_QUEUE.md` holds the prioritised backlog of autonomous tasks — march-line corpus capture, daily-claim sweeps, menu mapping, buff refresh, etc. Each entry includes goal, prerequisites, steps, and follow-up work so a future agent can pick one off and run it without further context.

When you finish a task, mark it done in EXPLORE_QUEUE.md and capture any learnings into NOTES.md / UI_MAP.md.

## Offline flow testing

`~/pnc_test_flow.sh` exercises the helper scripts against saved screenshots in `~/pnc_explore/`. The screenshots cover world map, city, search panel, search result, Termux foreground, and various tile-action states. Run before committing changes to any helper:
```
~/pnc_test_flow.sh           # full suite (~80 s)
~/pnc_test_flow.sh views     # just view detection
~/pnc_test_flow.sh mines     # just mine state
~/pnc_test_flow.sh flows     # multi-step scenarios
```

When you encounter a new game state, save a representative screenshot to `~/pnc_explore/<descriptive_name>.png`, add a test case to `pnc_test_flow.sh`, then update the recogniser in `pnc_view.sh` until the test passes. Tests prevent regressions when retuning thresholds.

## Move learned behaviours into scripts (ongoing principle)

Multimodal Read + AI reasoning is **slow** (each cycle is 5–15 s). Most maintenance steps boil down to deterministic checks ("is mine clean?", "what view are we in?", "n/5?") whose answers are in pixel data and don't need an AI. **As we learn how to recognise something reliably, move that recognition into a shell script** (`~/pnc_*.sh`) that returns a structured result. The AI is then called only for novel states or when a script returns `unknown`.

This keeps the AI in the loop for judgment calls (where it's strong) and out of the loop for repetitive recognition (where it's slow). Speedup compounds — every check we move out of AI cuts 5–15 s off every maintenance pass that uses it.

**When you (a future AI agent) figure out a new recognition pattern that you'll use repeatedly:**
- Write or extend a `~/pnc_*.sh` helper that returns the answer in <1 s.
- Use ImageMagick pixel sampling for "is this colour at this coord," tesseract OCR for text labels, `adb shell dumpsys ...` for system state.
- Be conservative — return `unknown` rather than guessing. False positives are worse than slow.
- Add the script to the table below and update the maintenance loop to call it.
- Bake the threshold/region tuning into the script comments so future tuning is easy.

**Existing helper scripts:**

| Script | Returns | Notes |
|---|---|---|
| `~/snap.sh` | full 33% JPEG | overview |
| `~/snap_top.sh` | top 80% 33% JPEG | faster, hides bottom UI |
| `~/snap_zoom.sh X Y W H` | full-res crop | precision button-finding |
| `~/say "<msg>"` | speaks via espeak/paplay | narration |
| `~/pnc_view.sh` | one of: `locked` / `loading` / `world` / `world_foreign` / `city` / `castle_panel` / `castle_buff` / `arcane_barrier` / `search_open` / `depart_dialog` / `chat_open` / `exit_prompt` / `alliance_panel` / `alliance_building` / `bag_open` / `talent_open` / `daily_quest` / `kingdom_map` / `tile_action` / `unknown` | Single-pass OCR + dumpsys lock check. ~1.2 s. Use as the first step of every flow — branch on the result. Set `SKIP_SNAP=1` to test against a staged `~/screen.png`. |
| `~/pnc_troop_count.sh` | `<n>/5  <status1>;<status2>;...` (e.g. `4/5  GATHERING 1d 02:13:14;GATHERING 00:38:42;MARCHING 00:01:40`) or `unknown` | OCR on Troop Info panel region. Requires world view. ~1.7 s. Tolerant of OCR noise (slash/letter confusion). |
| `~/pnc_mine_state.sh` | `clean_unverified K255 X:### Y:### AMOUNT` / `skip <reason> COORD AMOUNT` / `unknown` | Assesses a SEARCH-result mine. Returns `clean_unverified` because the march-line check is deferred (heuristic gave false positives on the search-highlight ring). Caller (AI or future smarter detector) does the final dashed-line verification. Reasons emitted: `wrong_amount`, `info_label`, `march_line` (when implemented). |
| `~/pnc_test_flow.sh [views\|troops\|mines\|flows\|all]` | Test runner. Stages saved screenshots from `~/pnc_explore/`, runs the helper scripts with `SKIP_SNAP=1`, asserts expected outputs. Prints pass/fail summary. **No taps sent to phone.** | 37 baseline tests; ~80 s for the full suite. Add new test cases as we learn more states. |

Add to this table as new helpers land.

## Three snap helpers: pick the right one for the task

| Helper | What it does | Output | Use when |
|---|---|---|---|
| `~/snap.sh` | Full screen, 33% downscale, q70 JPEG | ~50–80 KB at 403×895 | Need to see the whole UI (search panel + Depart button + bottom nav). General-purpose. |
| `~/snap_top.sh` | Full screen, 33% downscale, top 80% only | ~30–50 KB at 403×716 | World-map state checks, mine verification, troop info. Faster Read; can't see bottom nav / search panel internals. |
| `~/snap_zoom.sh X Y W H` | Full-resolution crop of a region | depends on W·H, ~30–80 KB at q85 for 400×400 | **Precision button-finding without the 33% downscale error.** Every pixel = one phone pixel. Use when standard snaps put adjacent buttons within ~30 phone-px of each other and you need to land cleanly. |

**Zoom workflow:**
```
~/snap_top.sh                       # overview, locate rough region
~/snap_zoom.sh 800 1400 400 400     # full-res cutout of that region
# Read zoom JPEG, identify button center at zoom-image (zx, zy)
adb shell input tap $((800 + zx)) $((1400 + zy))   # phone tap = origin + zoom
```

Don't crop the whole screen at full res — JPEG balloons. Keep crop ≤ 600×600 for typical button-region precision tasks.

This eliminates the ~3× error multiplier that 33% snaps impose. The Castle Buff sub-panel calibration issues we ran into were caused by ~5-px estimation errors in 33% snaps becoming 15-px hit-area misses on the phone, which is enough to land between adjacent rows. Full-res zoom snaps don't have that problem.

## Use snap_top.sh for verification snaps when the search panel is open

`~/snap.sh` produces the full 403×895 JPEG (~50–80 KB). `~/snap_top.sh` produces a top-60% crop (~403×540, ~30–50 KB) — same image, just the top portion. The Read tool processes the smaller image substantially faster.

**When to use which:**

| Scenario | Tool |
|---|---|
| World-map state check (Troop Info + map content) | `~/snap_top.sh` — Troop Info is in the upper-left, map content is in the upper area |
| Mine verification after SEARCH (info card + Gather label + march lines + Troop Info) | `~/snap_top.sh` — all relevant signals are in the top 60% |
| Cycling SEARCH past already-targeted mines (just need the X:Y in the info card) | `~/snap_top.sh` |
| Confirming Depart dialog state, troop counts, button morph | `~/snap.sh` — bottom Select All / Depart button is below the 60% line |
| Bottom-nav button verification (after launch, before/after city↔world toggle) | `~/snap.sh` — bottom nav is at the very bottom |
| Any time you suspect something is off and need full context | `~/snap.sh` |

When in doubt, use the full snap. The cropped one is a speed optimization for the common case, not a correctness guarantee.

## Suggested sleep defaults (after the snap-driven rule)

These are after-tap pauses that are large enough to let the UI settle but tight enough that you're not double-counting your own latency. Tune up if you see partial frames; tune down if you confirm the UI is ready faster.

| After action | Sleep before snap |
|---|---|
| Tap search magnifier (80, 2170) | 0.5 |
| Tap SEARCH (620, 2575) — including cycle-skip | 0.7–1.0 (camera pan is the longest) |
| Tap Gather (605, 712) | 0.5 |
| Tap bottom Select All / Depart (605, 2585) — first | 0.5 |
| Tap Depart (605, 2585) — second tap, dialog closes | 0.5 |
| Tap WORLD (140, 2580) — view toggle with fade | 0.7 |
| Tap ALLIANCE / sub-menu navigation | 0.5 |
| `monkey ... LAUNCHER` (PNC launch from Termux) | 1.0 (warm) — re-snap if mid-fade |
| `monkey ... LAUNCHER` after PNC kill (cold launch) | 2.0 + retry loop |

Sleeping is the floor; if your reasoning between turns adds 1–2 s anyway, that's already on top.

## Pacing rule: snap-driven, not sleep-driven

**Don't** insert long fixed sleeps after taps. Your own per-step latency (tool-call round-trip + reasoning + next tool call) already eats real wall time — adding `sleep 1.5` on top double-counts the wait.

**Do** drive off the snap. Pattern:
1. Tap.
2. Immediately call `~/snap.sh` (or chain: `tap && ~/snap.sh`).
3. Read the snap. By the time the JPEG is encoded, transferred, and read, the UI animation has usually finished.
4. If the snap shows a mid-animation/loading frame: small recovery sleep (~0.5s), re-snap, re-read.

Concretely for the gather flow this looks like:

```
adb shell input tap 80 2170 && adb shell input tap 620 2575 && ~/snap.sh   # search → SEARCH → snap, no sleeps in between
# Read snap; verify mine clean
adb shell input tap 605 712 && ~/snap.sh                                    # Gather → snap; verify Depart dialog
adb shell input tap 605 2585 && ~/snap.sh                                   # Select All → snap; verify Depart button
adb shell input tap 605 2585 && ~/snap.sh                                   # Depart → snap; verify Marching row
```

The exception is **PNC launch**, which can cold-load with a black/loading screen. For launch:
1. `adb shell monkey -p com.global.pnck ...`
2. `~/snap.sh` (no sleep — go straight to snap)
3. Read it. If the snap shows the resource bar at the top (gold/wood/stone/iron icons) and bottom nav, you're done. If it's mostly black, shows a partial logo, or shows an event popup, do one short `sleep 2 && ~/snap.sh` and re-read; repeat at most 2–3 times.
4. If launch lands on an event/daily-login modal, dismiss with `adb shell input keyevent 4` (back), re-snap.

This handles cold and warm launches identically — no separate "is PNC already foregrounded" check needed; the snap tells you everything.

**Heuristic:** if you find yourself writing `sleep N && ~/snap.sh` with `N > 0.5` for any reason other than the cold-launch loop, you're probably overpaying. Just snap and read.

## Open questions / untested
- Exact failure mode when "warning about other players" prompt appears (text wording, button positions) — never observed yet, only mentioned in past notes
- Long-running 21-hour `Gathering` timers occasionally seen in Troop Info — likely a Lv7 furnace or stone/wood gather queued previously; ignore for iron-furnace planning
- Whether daily/weekly modals (event reset, claim rewards) ever block the city view on launch and need to be dismissed before the WORLD button is reachable

## Stale guidance (kept for reference, superseded above)
- World map tile clicks remain unreliable for any direct map interaction — always go through SEARCH
