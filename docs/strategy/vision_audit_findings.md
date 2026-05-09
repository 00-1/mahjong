# Vision audit — 158 screenshots across 17 runs (level 8)

Re-extracted every saved screenshot with current code, compared to
runtime-saved state.json, surfaced anomalies. Run independently of
the phone agent so results are clean.

## TL;DR

The template was missing **24+ anchor positions** the level actually
uses. Reconstructed from data → 45 main_board anchors (was 21).
After rebuild: 96.5% detection match rate, 0 false-positive new
matches, 40 of 158 screenshots now extract more main_board tiles
than runtime did — none extract fewer.

## Findings & fixes

### 1. Template was missing 24 main_board anchor positions [FIXED]

The original template had 21 main_board anchors, mostly along outer
columns (cx 137, 271, 405, 673, 807, 941). Real screenshots have
detections at *additional* between-column positions: cx 205, 339,
473, 540, 607, 741, 875.

The level layout is denser than the template assumed:
- 7 rows of main_board (cy 621, 692, 764, 837, 908, 981, 1052
  scaled), evenly spaced ~71px apart
- Up to 10 cells per row in the wide top/bottom rows
- 4-6 cells per row in middle rows

Built `scripts/audit_template.py`-style clustering (inline) that
aggregates detection positions across all puzzle screenshots, takes
clusters with ≥5 observations, generates anchors. Total: 45 main
anchors covering all observed positions.

### 2. Queue cy_tolerance too tight [FIXED]

Persistent unmatched at cx=540 cy=1301 (46 occurrences across runs).
This is the center queue-strip head — template had it at cy=1249,
detection sees it at cy=1301 (52px below). Tolerance was 50.

Bumped `queue_cy_tolerance` from 50 → 75 in `snap_detections`.
Single-line change; covers normal queue-strip animation drift.

### 3. Tap-into-non-existent-anchor was the "tap had no effect" cause

Investigated 9 tap events where state showed no change after a
successful tap call. All 9 were the agent tapping at depth-offset
positions (e.g. cx=205) interpreted as "depth-2 reveal of (0,1)
peeking left". Actually they were full standalone tiles at
between-column positions the template didn't have. The tap landed
on the right pixel and hit the actual tile, but the next snap
re-detected the same tile at the same offset position and looked
unchanged.

**Fixed by anchor-template rebuild** (item 1). Once those positions
have proper anchors, the tap is recorded against the right (row,
col) and the post-tap state correctly reflects the change.

### 4. Tile-id matching is healthy

Distance distribution across 1,445 in-run main_board matches:
- 0-10:   37.9%
- 11-20:  45.8%
- 21-30:  12.1%
- 31-40:   0.4%
- 41-50:   2.7%
- 51+:     1.1%

So 95.8% of matches are well below the 60-distance threshold. The
~1% at distance 51+ are marginal but still under threshold. No
threshold tuning needed.

### 5. Detection count is bimodal — NOT_A_PUZZLE detection works

Across 158 screenshots: 36 have 0-2 detections (non-puzzle screens
— world map, modal overlays), 122 have ≥11 detections (puzzle
screens). Zero in the 3-10 range. Existing
"main_board count == 0 → NOT_A_PUZZLE" check is sound; could even
tighten to "main_board < 6 → NOT_A_PUZZLE".

### 6. Tap consistency is mostly fine

Of ~150 main_board taps logged across runs:
- 57 successful single-tap → tray increment
- 35 successful with depth-2 reveal
- 34 successful with anchor cleared (single-depth)
- 4 single-tap triplet-clear (tray drop -2)
- 9 "no change" — all due to template gaps (item 3)
- 3 "tray dropped by 1" (suspicious but rare)

Post-template-rebuild, the 9 "no change" should disappear.

### 7. Per-anchor tile_id "diversity" was a measurement artifact

Audit aggregated tile_ids at each anchor across ALL run states and
showed apparent disagreement with `anchor_priors.json` (which
records only d1). The audit was conflating d1 + d2 + d3 reveals.
Both data sources are valid; they measure different things. No bug.

## Outstanding

### A few non-puzzle-screen detections [low priority]

6 unmatched detections in cy 1700-2000 (between queue and tray
zones) all came from screenshots where the agent navigated OUT of
the puzzle (game world map showing). The 0-2 detection floor caught
these as NOT_A_PUZZLE; no impact on play.

### Stack-depth detection not directly validated

The audit didn't compare `stack_depth=1` vs `stack_depth=2`
assignments against ground truth. Worth adding a pass that checks:
when a tile transitions stack_depth=1→2 between consecutive states,
does the visible tile_id change too? (It should — d1 was tapped,
d2 became the new top.)

### `bayesian_accuracy.json` verification logic is wrong

Compares predicted-d2 to actual-tile-at-anchor-next-step. But
actual is only d2 if we tapped that anchor. Otherwise we're
comparing predicted-d2 to actual-d1 (always wrong). Real Bayesian
accuracy is likely substantially higher than the 21% reported.

Fix sketch: only verify anchors whose tile_id changed between the
prediction step and the verification step. Easy 10-line fix.

## What this means for the strategy

With the template rebuild, the agent now sees the FULL board.
Many of the agent's recent "agent gave up on a winnable position"
losses were vision-incompleteness in disguise — the planner couldn't
see triplet-completing tiles. With these anchors added, the same
starting positions become winnable strategy decisions, not
extraction-suspect ones.

Strategy work (the tray-pair-completion bonus, MCTS, etc) is still
the right next direction — but should be validated against the
new richer state extraction, not the old gap-ridden one.
