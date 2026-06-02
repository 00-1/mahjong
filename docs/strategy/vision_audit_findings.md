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

## Second pass — post-fix validation

After the queue-snap fix (`7a4fa02`), repeated the audit:

### Detection
- Match rate: 97.5% → **99.7%**
- Queue matches: 320 → **366** (+46 = exactly the recovered centre-queue)
- Main / tray match counts: unchanged (no regression)
- Remaining 6 unmatched: all from screenshots where the agent
  navigated outside the puzzle (game world map). Zero on actual
  puzzle screens.

### Strategy
End-to-end test: ran fresh `extract_board.py` then `decide()` on
all 25 start-of-run screenshots in the saved data. Distribution:

- TRIPLET pick: **18 of 25** — planner immediately identifies a
  triplet to clear from the start state.
- GAME_OVER: 6 — these are the post-restart-leak cases where the
  initial screen already had tray=7 (environmental issue, not
  vision or strategy).
- EXPLORE: 1 — `run_143611` with lookahead_value=+25.9; healthy
  position with no immediate triplet but recoverable.

Critically: the runs that previously surrendered as "unrecoverable"
on first frame (155720, 155845, 162200 — the user's screenshot
cases) all now identify the butterfly_orb triplet at step 0. The
position was always winnable; vision was hiding it.

### What the data tells us about the strategy code path

When vision is correct, the planner does the right thing. The
remaining loss-mode pattern is genuine: tray-pair-jam at high
tray fill (the user's manual-loss screenshot showed this too —
2 lanterns + 2 butterfly_orbs + 2 plumerias all stuck because
the 7th tap was a singleton). The "tray-pair-completion bonus"
sketched earlier targets exactly this and is a defensible next
strategy refinement.

### What needs to fail-safe

- If `unmatched_positions.json` ever appears in a run's extraction
  dirs, that's a new template gap. The auto-write makes it
  obvious; templates can be extended without the diagnostics
  having to be reverse-engineered every time.
- The `intended_actual_match=False` events in the new verify log
  are the canary for vision misclassifying tap targets. Should be
  rare; if frequent, the matcher needs another sample broadening.

## Third pass — strategy/timing fixes after deep tap audit

After comprehensive tap-pair + burst audit, four real bugs found and
fixed in one batched change:

### Surrender guard misfired mid-game [FIXED]
The `surrender_min_main_board=10` floor was meant as a step-0 vision-
suspect check, but it was unconditionally enforced — blocking surrender
mid-game when the board naturally cleared down to 7-9 visible tiles.
Run_165854 lost 7 wasted taps after lookahead said -1000 because of
this. Replaced with a `surrender_sparse_grace` window (default 5
steps after `surrender_step_floor`); after that, sparse main_board
no longer vetoes surrender. Validated: surrender now correctly
fires at step 21 of run_165854 (was never).

### Bayesian verifier counted non-tapped anchors [FIXED]
`verify_bayesian_predictions` was comparing predicted-d2 to
actual-tile-at-anchor regardless of whether that anchor had been
tapped. For non-tapped anchors, actual is still d1 — comparison
always wrong. Real Bayesian accuracy was 6.2% (basically random),
not the 21% reported. Updated to require either explicit
tapped_keys or auto-infer from before/after diff. Confirmed via
unit test that only tapped anchors flow through.

### Triplet bursts looked "incomplete" 28% of the time [FIXED]
75 historical triplet bursts: 54 clean, 21 incomplete. Root cause:
`adaptive_wait_for_change` returns on the *first* state change after
the burst — but a burst fires 3 taps + animations totaling ~1.5s.
Returning on first change captures a mid-burst snap with only 1-2
of the 3 taps having visually resolved. State.json then shows
"only 1 of 3 cleared" but the game actually completed all 3. Added
`require_stable_for` param: in stability mode, waits until state
has held for N seconds. Burst path passes 0.6s default. Single-tap
path unchanged.

### Tray-pair-completion bonus [ADDED]
Direct strategy fix for the genuine loss pattern (tray-pair-jam at
tray=4-7 — observed in user's manual loss screenshot too). When
state has `tray_count=2` of some tile AND that tile is also visible
on the board, give a +20 bonus when tray ≥ 4 (else +5). The third
instance is right there — taking it drops tray by 2 net (3 in tray
auto-clears). Old state_value's flat +5 "near-triplet seed" reward
treated reachable and unreachable pairs equally; the bonus now
explicitly privileges reachable.

Validated unit-test: at tray=4 with 2 tile_X in tray + 1 visible,
state_value = -9.3; with 0 visible (unreachable), state_value =
-62.3. Difference of +53 strongly steers the planner toward the
completion. At tray=2 the bonus is small (+11 difference), so
early-game decisions aren't distorted.

### Verify_tap intended-vs-actual surfaced [ADDED]
verify_tap now records `expected_tile_id`, `target_actual_tile_id`,
`intended_actual_match`, `tray_added`, `tray_removed`,
`unexpected_position_changes`. Old verify only checked "did target
location change". With the new fields, vision-misclassified-target
cases are flagged as `intended_actual_match=False` even when the
tap technically "succeeds". Across 74 historical tap pairs, found
0 misclassifications — vision is accurate at tap targets.

## Final detection numbers

- Match rate: 99.76% across 158 screenshots × all detections
- Remaining 6 unmatched: all from world-map screenshots (agent
  navigated outside puzzle), not real puzzle state.
- 19 of 26 saved start-states pick TRIPLET on first decision;
  6 are post-restart-leak with tray=7 already (env issue);
  1 is healthy EXPLORE.

## What "perfect" looks like now

Vision: detection match rate at 99.76%; tile-id matching at 0% target
mismatch on real taps.
Strategy: surrender fires correctly when lookahead detects terminal
loss; tray-pair-completion bonus targets the dominant loss mode.
Timing: triplet bursts stabilize before re-snap.
Diagnostics: every run logs git SHA + library version; verify
records intended-vs-actual for every tap; unmatched_positions.json
auto-written when template gaps appear.

The remaining gap is fundamentally non-resolvable with current
data: d2 placement in this game is genuinely random for most
anchors. The Bayesian predictor at 6.2% (random baseline 7.7%)
isn't broken — there's just no signal.

## What's left

- A genuine MCTS / determinized UCT solver would be the next
  strategy upgrade (per `optimal_solver_plan.md`). Worth doing
  if the current strategy + bug fixes don't push win rate
  meaningfully.
- Strict per-anchor confidence thresholding for Bayesian
  predictions would help when more data lands. Right now sample
  size is too small to set per-anchor cutoffs reliably.

## Round 4-5 — anchor priors rebuild + forward-simulation finding

### Anchor priors data integrity [FIXED]
Discovered that `anchor_priors.json` had mixed (row, col) keys
across template versions. After the template rebuild, old labels
pointed to different physical positions. Built
`scripts/rebuild_anchor_priors.py` and rebuilt from all 146 saved
puzzle screenshots using current template:
- 30 anchors with priors (was 21)
- 1718 total observations
- Several strong d2 patterns appear:
  - (6,5) tile_012: 100% (25 obs) — perfectly deterministic
  - (6,7) tile_009: 100% (6 obs) — small sample but consistent
  - (5,4) tile_002: 96% (25 obs)
  - (3,5) tile_004: 86% (14 obs)
  - (6,6) tile_008: 69% (48 obs)
  - (2,3) tile_006: 52% (42 obs)

Combined with the per-anchor filter, the Bayesian predictor now
emits 11 high-confidence predictions on a typical mid-game state
— vs 18 mostly-noise before, or 8 after rebuild without the
filter alone.

### Forward simulation reveals depth-3 limit
Tested: load the saved start of run_20260509_165854_l08, let the
planner play it forward picking each step's lookahead-recommended
move. With depth=3 + Bayesian-MAP reveals + per-anchor filter:
- 3 triplets cleared, lost at step 15.

The simulator is pessimistic about random anchors — when no
high-confidence prediction exists, the position becomes empty
in simulation rather than "something unknown is here". So the
lookahead can't plan reveal-cascades for low-confidence anchors.

This is the genuine ceiling of heuristic search on the current
game state. Pushing past it requires:
- Deeper search (depth=5 at branching factor ~18 takes minutes)
- MCTS with sampled determinizations (matches the
  `optimal_solver_plan.md` recommendation)
- A more sophisticated reveal model that doesn't degenerate to
  empty positions for random-prior anchors

### What we know vs what's left

KNOWN-WORKING (validated):
- Vision: detection 99.76%, tile-id match 96% within threshold,
  0 mismatches at tap targets.
- Strategy at depth=3 with current heuristic: identifies recoverable
  vs terminal states correctly, picks reasonable moves in EXPLORE,
  surrenders at the right step.
- Diagnostics: every tap logged with intended-vs-actual; runs
  stamped with git SHA + library version; unmatched_positions
  auto-written when template gaps appear.
- Rebuild tooling: `rebuild_anchor_priors.py` keeps priors aligned
  with template changes.

KNOWN-LIMITS:
- Depth=3 lookahead can't see beyond ~3 taps of consequence,
  loses to tray-fill when triplet completion requires a 5+ tap
  unblock sequence.
- d2 placement in this game is genuinely random for most anchors
  (per the empirical 6.2% accuracy at random baseline).
  No predictor will solve this without MCTS-style sampling.
- Burst incompleteness (~28% of historical bursts) — likely
  fixed by `--burst-stability-window=0.6` but not yet validated
  on live data.

FORWARD WORK if more iteration desired:
- Determinized UCT: ~250 LOC, bigger lift, would push past the
  depth-3 ceiling.
- Probabilistic simulator: replace "no reveal" with sampled-from-prior
  reveal in low-confidence anchors. Needs expectimax-style search
  to be useful.
- Per-anchor confidence learning: the filter is a static threshold;
  dynamic per-anchor calibration would help once more data lands.

## Round 6 — Determinized UCT shipped (opt-in)

After the full validation pass and identifying depth-3 lookahead as
the heuristic-search ceiling, implemented single-determinization UCT
per `optimal_solver_plan.md` Phase B.

### `src/solver/uct.py` (~280 LOC)
- `determinize()`: samples a per-anchor d2 assignment from priors
  weighted by remaining-inventory.
- UCT loop: UCB1 selection (c=1.5), expansion of one untried action
  per iteration, bounded-depth rollout with greedy-prefer-triplets
  bias, state_value-evaluated leaves.
- `uct_recommend()` returns the same shape as `lookahead_recommend()`
  so `decide()` can swap them.

### Wiring
- `decide.py`: new `use_uct`, `uct_iterations`, `uct_rollout_depth`,
  `anchor_priors` params. When `use_uct=True` and there's no
  immediate triplet, runs UCT instead of lookahead.
- Decision dict gains `search_method` field ("uct" | "lookahead" |
  None) for post-hoc analysis.
- `autoplay.py`: `--use-uct` flag (default off), `--uct-iterations`
  (default 200), `--uct-rollout-depth` (default 8). Lazy-loads
  anchor priors when UCT enabled.
- `session.py`: forwards.

### Why default off
A/B forward-simulation on a saved start state showed UCT and
lookahead both plateau at 3 triplets / step 15 / lost. Both are
bottlenecked by the same thing: when no high-confidence d2
prediction exists for an anchor, the simulator treats the position
as becoming empty after a tap. UCT samples reveals (so has more
data than lookahead's MAP-only) but commits to that single sample
per decision; if the sample happens to be unfavourable, UCT
follows it.

UCT's real value comes from real-game reveals: on the phone the
ACTUAL d2 tile appears after a tap, and UCT can adapt run-to-run
in ways depth-bounded lookahead can't. The forward-simulator's
pessimism is the bench's limit, not the algorithm's.

### What's left for true ISMCTS
Re-determinize per iteration so different rollouts average across
plausible worlds. ~50 LOC delta from current UCT — keep tree
structure (action-keyed) but resample determinization each
iteration, traverse by action. Worth doing if UCT-as-shipped
doesn't materially beat lookahead in live runs.

## Final state of the day's iteration

8 commits over 4+ rounds:
- 36514b1: surrender fix + burst stability + tray-pair bonus + verifier
- a15c7e1: per-anchor Bayesian filter
- d022e4f: anchor priors rebuild + rebuild_anchor_priors.py
- b2ebe63: session.py flag forwarding
- 4e15c0f: round 4-5 audit doc
- f42b19e: UCT solver

Vision pipeline: 99.76% match rate, 0 tap-target mismatches.
Strategy: heuristic lookahead at depth=3 with surrender guard +
tray-pair-completion bonus + per-anchor Bayesian reveals.
Alternative solver: UCT shipped behind --use-uct.
Diagnostics: complete (commit logging per run, intended-vs-actual
per tap, unmatched_positions auto-write, bayesian_accuracy with
correct verifier).

The ceiling now is fundamentally about either:
1. Live-game reveals (which neither offline simulator can predict
   for random anchors) — UCT might help here on phone runs.
2. ISMCTS-style averaging across determinizations — ~50 LOC more.

Branch is in good shape for live runs.
