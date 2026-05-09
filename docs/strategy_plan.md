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

Working through Phase 2 next. Will commit each phase separately so
review can happen incrementally.
