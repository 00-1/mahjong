# Strategy refinement plan

## Goal

Beat level 8 reliably. Build a strategy framework that generalizes to higher
levels.

## Failure mode observed in real run data

`run_20260509_112851_l08`: cleared 13 triplets greedily (steps 0-12), then
ran out of immediate triplets at step 13. From there the solver did 7
EXPLORE taps of 7 different tile types — all unique, none formed a future
triplet. Tray grew 0 → 6, modal appeared, run lost.

**Root cause**: the greedy "always clear visible triplet" strategy paints
the solver into corners. By the time we hit fork (step 13), there's no
recovery because we have no near-triplet seeds in the tray.

## Plan

Phases roll out in dependency order. Each phase has acceptance criteria
that must pass before moving on.

### Phase 1: Foundation modules ✅ DONE

- [x] `src/solver/simulate.py` — deterministic state transition for a tap
- [x] `src/solver/lookahead.py` — depth-limited search with value function
- [x] `src/solver/economy.py` — per-tile supply/demand tracker

**Acceptance**: modules import cleanly + unit-test on saved state.

### Phase 2: Wire lookahead into the solver

- [ ] `src/agent/decide.py` accepts `use_lookahead: bool` and `depth: int`
- [ ] `scripts/autoplay.py` adds `--use-lookahead` flag
- [ ] When enabled, `decide` calls `lookahead_recommend` instead of greedy
      `suggest_moves` (or as a follow-up filter)

**Acceptance**: on the saved state at step 13 of the "won" run, lookahead
picks a *different* move than greedy did, with a higher expected value.

### Phase 3: Strategy comparison tool

- [ ] `scripts/compare_strategies.py` — takes a saved run + two solver
      configs, replays each decision under both, reports differences
- [ ] Run it on `run_20260509_112851_l08` and report which decisions
      diverge

**Acceptance**: tool produces a side-by-side report with at least one
divergent decision at fork, plus expected-value comparison.

### Phase 4: Resolution-independent calibration

- [ ] `scripts/restart.py` auto-detects screen resolution from screenshot
      and scales saved coords
- [ ] Per-level templates auto-rebuild on resolution mismatch (already
      implemented in template scaling — verify it triggers)

**Acceptance**: same `restart_config.json` works on both 1220×2712 and
1080×2400 (verifiable via the docs/_session_artifacts examples).

### Phase 5: Occult predictions feeding simulation

- [ ] Pass occult_predictions to `simulate_tap` so the lookahead can
      anticipate what gets revealed
- [ ] Score reveals using `economy.compute_economy` — a reveal of a
      tile we already have 2-of in tray is highly valued

**Acceptance**: lookahead with occult predictions makes more aggressive
"dig" moves (taps that reveal known-useful tiles).

### Phase 6: Per-anchor priors (needs accumulated data)

- [ ] After 5+ runs of level 8, `anchor_priors.json` has stable data
- [ ] `economy.predict_anchor_from_priors` returns most-likely tile at
      anchor with probability
- [ ] Lookahead uses priors when no occult prediction exists
- [ ] When priors disagree with occult prediction, log a "surprise" event

**Acceptance**: across multiple runs, surprise rate decreases as priors
build up.

### Phase 7: Smart restart policy

- [ ] Track per-attempt metadata: did we hit fork early? did we run out
      of tickets?
- [ ] If win rate at level 8 is very low (e.g. < 20%), the strategy is
      probably broken — don't burn all 10 tickets, halt and require
      human investigation

**Acceptance**: session.py supports a `--max-losses-before-halt N` flag
that stops after N consecutive losses.

## Validation methodology

For every change:
1. Articulate the failure mode it addresses
2. Identify a specific saved state that exhibits the failure
3. Run the new code against that state and confirm it picks differently
4. Sanity check: doesn't regress on saved states that were already going
   well

For Phase 5+ (need real data):
1. Run autoplay with new code for N attempts
2. Compare win rate to baseline
3. Run `replay_run.py` on losses to check that the failure modes have
   shifted (we want different losses, not the same ones)

## Out of scope (for now)

- Reinforcement learning / value-function training
- Cross-level transfer
- UI for inspecting / overriding solver decisions live

## Status checkpoint

- ✅ Phase 1: simulate.py, lookahead.py, economy.py
- ✅ Phase 2: --use-lookahead flag wired into autoplay + decide
- ✅ Phase 3: scripts/compare_strategies.py validates against saved runs
- ✅ Phase 4: restart.py auto-detects + scales coords for resolution mismatch
- ✅ Phase 5: merge_occult_and_priors feeds combined predictions to lookahead
- (deferred) Phase 6: anchor priors live (needs >=3 runs of accumulated data)
- ✅ Phase 7: --max-consecutive-losses on session.py

Validation against the saved fork-state of `run_20260509_112851_l08`:
- Step 17 lookahead returns expected_value=-1000 (correctly anticipates
  game-over within 3 moves)
- Step 0-12 lookahead matches greedy on triplet completion (no regression)
- Steps 13-17 (fork+) lookahead picks differently with quantified
  expected values

Next iterations require live run data:
- Phase 6 fully active once anchor_priors.json has data from real runs
- Tuning weights in state_value based on what compare_strategies surfaces
- Eventually: train value function from accumulated outcomes

## Phase 8 — Solver bug fixes from accumulated data (2026-05-09)

Inspecting `data/levels/08/occult_accuracy.json` revealed the live
occult predictor at 0/14 correct (0% accuracy at all confidence
buckets). At the same time, `anchor_priors.json` showed strong
empirical priors (e.g. (0,5) is tile_006 in 34/41 samples = 83%,
(4,0) is tile_003 in 27/57 = 47%).

Three bugs found and fixed in `merge_occult_and_priors` +
`simulate_tap`:

1. Wrong depth: merge used `d1` priors (= what was on TOP, the tile
   just tapped), but `simulate_tap` consumes the map as the
   *revealed* tile (= what comes up after the tap). That's `d2`.
   Net effect: the lookahead was being told "tapping this anchor
   reveals the same tile we just removed", which models nothing.
   Fix: use `d2`, also gate on `prior_min_share >= 0.4` to avoid
   noisy uniform-distribution anchors.

2. Live predictions polluting the map: with 0% accuracy at any
   confidence, low/medium-confidence predictions were overwriting
   the much-better priors. Fix: default `confidence_threshold=0.99`
   (effectively excludes live predictions until the predictor
   improves). Surface as `--occult-confidence-threshold` so we can
   lower it as accuracy data improves.

3. Reveal duplication: `simulate_tap` would re-reveal the same d2
   tile every time the same anchor was tapped within a search
   tree. Fix: only reveal when `cell.stack_depth == 1` (the first
   tap of an anchor); deeper taps yield empty position.

Strategic value-function addition: `state_value` now penalises DEAD
tray tiles — entries whose tile_id has fewer than 3 instances
across visible+tray+sim-revealed total (so a triplet is impossible).
-15 per dead tile makes the lookahead refuse explore taps that
permanently occupy a tray slot.

Validated on saved states from `run_20260509_112851_l08`: at step 0
(all anchors at depth 1), the d2-prior reveals shift per-candidate
state_value by +1 to +3 for most positions, and the root lookahead
EV improves from -25.30 to -19.30 — meaningful signal.

These fixes are gated on having enough run data to populate
anchor_priors with meaningful d2 distributions. We have that for
level 8 now (12 runs). For new levels, the d2 distribution will
start sparse and `prior_min_obs=3 + min_share=0.4` filter will
gracefully fall back to "no reveal" until enough data accumulates.
