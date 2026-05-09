# Towards an optimal solver — theoretical framing + implementation plan

## What is this game, formally?

Single-player, sequential, partially-observable, finite-horizon
decision problem with these primitives:

- **State**: a forest of "anchors" (board positions); each anchor
  carries a stack of tiles (height ≤ 2 in level 8); plus queue
  strips that feed tiles in order; plus a bounded tray (k=7).
- **Hidden state**: depth-≥2 tiles at each anchor and unseen-yet
  queue positions. Per-level priors are learnable from accumulated
  runs (and we have them).
- **Action**: tap any tappable top tile. The tapped tile enters the
  tray; the tile beneath it (if any) becomes the new top.
- **Auto-clear** (the unusual mechanic): when 3 of a kind accumulate
  in tray, all three are removed.
- **Terminals**: WIN if all tiles cleared (board+queue+tray empty);
  LOSS if tray reaches 7 with no triple.

Multiplicity per tile-id is divisible by 3. Empirically (level 8) we
have a mix of 3-instance and 6-instance tiles — see
`inventory_findings.md`.

## Complexity — what's known

- **Mahjong Solitaire with peeking** (the closest published variant)
  is NP-complete even when restricted to isolated `aab` / `abb`
  stacks — i.e. depth-2 stacks covering depth-1 reveals. de Bondt
  2012, [arXiv:1203.6559](https://arxiv.org/abs/1203.6559),
  reduction from 3-SAT.
- **Match-three / Candy Crush variants** are NP-hard (Walsh 2014
  [arXiv:1403.1911](https://arxiv.org/abs/1403.1911); Gualà et al.
  2014 [arXiv:1403.5830](https://arxiv.org/abs/1403.5830)) but
  without a bounded buffer — so not directly transferable.
- **Mahjong Solitaire (no peeking)** is the classical NP-completeness
  result, catalogued in Eppstein's compendium
  [ICS UCI](https://ics.uci.edu/~eppstein/cgt/hard.html).
- **Bounded-buffer + triple-match + hidden tiles**: not in any
  literature the research turned up. This specific combination
  appears unstudied. So no off-the-shelf optimal algorithm.

## Implication — what kind of solver to build

Given NP-hardness even of the deterministic peeking variant, **we
will not get an exact polynomial-time optimal algorithm**. The
practical universe is:

1. **Heuristic search with strong value function** — what we have
   now (depth-3 lookahead + state_value). Good for triplet phase,
   weak in deep explore.
2. **Determinized UCT (single sample MCTS)** — sample one consistent
   assignment of hidden state from priors, run UCT on the resulting
   perfect-information game. Repeat per move. ~200-300 LOC.
3. **Information Set MCTS (ISMCTS)** — Cowling, Powley, Whitehouse
   2012 ([preprint](https://eprints.whiterose.ac.uk/id/eprint/75048/1/CowlingPowleyWhitehouse2012.pdf),
   pseudocode in
   [CIG'11 Dou Di Zhu paper](http://orangehelicopter.com/academic/papers/cig11.pdf)).
   Tree nodes are *information sets* (states the agent cannot
   distinguish); each iteration redetermines the hidden state and
   only descends through edges legal in that determinization. The
   principled fix to determinized UCT's "strategy fusion" pathology
   (UCT confidently picking moves that win in some worlds and lose
   in others). ~400-500 LOC.
4. **POMCP** — Silver & Veness NeurIPS 2010
   ([preprint](https://dspace.mit.edu/bitstream/handle/1721.1/100395/Silver_Monte-carlo.pdf)).
   UCT over histories with an unweighted particle-filter belief
   update. The most general approach; needs only a black-box
   generative simulator (which we have via `simulate_tap`). Reference
   implementations: [POMCP](https://github.com/GeorgePik/POMCP),
   [PyPOMDP](https://github.com/namoshizun/PyPOMDP),
   [pomdp-py](https://h2r.github.io/pomdp-py/).
5. **PBVI / SARSOP** — point-based offline value iteration. Probably
   overkill: belief space (multinomial over hidden assignments)
   blows up fast, our horizons are short.

## Recommended path

**Single-determinization UCT first.** Rationale:
- Smallest implementation (~200 LOC on top of the simulator we
  already have).
- Determinization quality is high here — anchor priors give
  near-deterministic d1 distributions and reasonable d2 marginals.
- Gives a clean baseline to A/B against the current heuristic
  lookahead.
- Failure mode (strategy fusion) is observable in logs: if UCT
  confidently picks a move whose simulations split between wins
  and losses, that's the trigger to upgrade.

**Upgrade to ISMCTS only if strategy fusion bites.** It's not free
— ISMCTS needs careful handling of action legality across
determinizations. But the de-Bondt-style structure (mostly
independent stacks) means determinizations don't differ all that
much in legal-action space, so SF may not be the main pathology.

**POMCP if we want explicit belief tracking.** This is the cleanest
end-state architecture but adds particle filtering complexity.
Worth it if/when we want to compose POMCP with other inference
(e.g. Bayesian inventory updates, animation-frame observations).

## Mapping onto our codebase

### What we already have

- **Generative simulator**: `src/solver/simulate.py:simulate_tap`
  takes a `BoardState` + action + reveal map → next state. Exactly
  the black-box generator MCTS needs.
- **Action enumeration**: `candidate_locations`.
- **Heuristic value function**: `state_value` — usable for
  rollout-cutoff and for `Q` initialization.
- **Per-anchor priors**: `data/levels/<NN>/anchor_priors.json` with
  d1 and d2 distributions. Direct input to determinization sampling.
- **Outcome detector**: simulate_tap returns terminal status.

### What's missing for UCT

1. **Determinization sampler.** Function: given current state +
   priors + cleared history → sample a fully-instantiated state
   where all hidden tiles are filled in. ~80 LOC. Constraints:
   - Per-anchor d2: sample from `anchor_priors[d2]` distribution.
   - Queue depth 2+: same idea, per-queue priors.
   - Inventory consistency: total sampled tiles per tile-id must
     not exceed `inventory[tid].count - cleared_so_far - visible
     - tray`. Reject-and-resample if violated; in practice this
     tightens the d2 sample.
2. **UCT tree node + UCB selection.** Standard. ~80 LOC.
3. **Rollout policy.** Use the existing `state_value` as
   leaf-cutoff after a configurable depth, or random-policy
   playouts to terminal. The cutoff variant is much faster and
   probably enough.
4. **Decision wrapper.** Replace `lookahead_recommend` call site
   with `uct_recommend(state, n_iterations, n_determinizations)`.
   Returns the same dict shape so `decide.py` doesn't change.

Total: ~250 LOC of new code, 0 changes to existing surface.

### What's missing for ISMCTS (delta on UCT)

- Tree nodes keyed by *information set*, not state — but our IS is
  trivially `(visible_state, cleared_history)`.
- Per-iteration redetermination + legal-action filtering.
- Visit-count handling that respects only edges legal in the
  current determinization.

Add ~150 LOC.

## Wiring plan (deferred — to do when agent run completes)

Phase A — foundation (must precede any MCTS work):
1. **Inventory builder.** `scripts/build_inventory.py` aggregates
   per-run max-observed counts, rounds up to multiples of 3,
   writes `data/levels/NN/inventory.json`. ~50 LOC. **High
   priority** — without this the dead-tray penalty is wrong, the
   determinization sampler doesn't have a constraint, and the
   Bayesian reveal posterior doesn't have a denominator.
2. **Cleared-history tracking.** `BoardState` gets a
   `cleared: dict[tile_id, int]` field populated by replaying step
   logs from the current run. Used by both state_value and
   determinization. ~40 LOC.
3. **Bayesian reveal posterior.** Replaces `predict_occult_at_anchors`.
   Inputs: anchor_priors, inventory, cleared_history,
   visible_state. Output: per-anchor posterior over hidden tile.
   Trivially computable; deletes the broken ensemble + the 5-8s/step
   it currently burns. ~100 LOC.

Phase B — solver upgrade:
4. **Determinization sampler.** ~80 LOC.
5. **Single-determinization UCT.** ~250 LOC including the sampler.
   Wire as alternative to `lookahead_recommend` behind a
   `--use-uct` flag. Don't replace the existing path; A/B them.

Phase C — adaptive (only if A/B says we need it):
6. **ISMCTS upgrade** if strategy fusion observed. ~150 LOC delta.
7. **POMCP** if we want a unified Bayesian + planning framework.
   Larger lift, only if Phase A+B isn't enough.

## Acceptance criteria

Before merging the UCT path:
- On a fixed set of 20 saved post-fork states (where greedy/lookahead
  fails), UCT picks a move whose Monte Carlo win rate over 500
  determinizations is ≥ 1.5× the current solver's MC win rate.
- UCT decision time per move ≤ 3 seconds at 1k iterations
  (ballpark; tune iter count to fit). Currently a step takes
  ~5-8s with the broken occult predictor running. Replacing it
  with the Bayesian posterior should free up that budget.
- No regression on triplet phase: when a triplet exists, UCT picks
  a clearing tap. (UCT's exploration noise can cause spurious
  weakness here; cheap to validate.)

## Things explicitly not pursued

- **PBVI / SARSOP** — overkill, blows up.
- **Deep RL value function** — the data we have is plenty for
  hand-engineered heuristics; deep RL needs orders of magnitude
  more samples for marginal gains. Revisit if we ever scale to
  many levels with shared structure.
- **Buying the Patreon Arcane Puzzle guide** — $5, only verified
  human-authored guide for this exact game. Worth doing once for
  human-knowledge cross-check, but the fact that no public
  reverse-engineering exists means we'll be ahead of the meta
  with our own data.

## Useful references

Implementation:
- ISMCTS Dou Di Zhu paper has near-pseudocode:
  http://orangehelicopter.com/academic/papers/cig11.pdf
- POMCP NeurIPS preprint (clean algorithmic exposition):
  https://dspace.mit.edu/bitstream/handle/1721.1/100395/Silver_Monte-carlo.pdf
- Reference Python POMCP: https://github.com/GeorgePik/POMCP

Theory:
- de Bondt, *Solving Mahjong Solitaire boards with peeking*:
  https://arxiv.org/abs/1203.6559 (read §3 for the `aab/abb`
  reduction; §4 has a deterministic-baseline solver useful as a
  per-determinization perfect-info subroutine)
- Cowling, Powley, Whitehouse, *Information Set Monte Carlo Tree
  Search*: https://eprints.whiterose.ac.uk/id/eprint/75048/1/CowlingPowleyWhitehouse2012.pdf

Community / domain:
- Puzzles & Chaos wiki Arcane Puzzle page:
  https://puzzles-chaos.fandom.com/wiki/Arcane_Puzzle
- Patreon "Mahjong Match Strategy" guide:
  https://www.patreon.com/posts/mahjong-match-128287302
- Maxims that the casual-strategy guides converge on:
  - Play as if tray = 2, not 7
  - Don't dig until you have 2 in hand
  - Surface-clear-first

## Estimated total effort

- Phase A (inventory + cleared history + Bayesian posterior): ~half
  day
- Phase B (determinization sampler + UCT): ~day
- Tuning + acceptance validation against saved states: ~half day

So ~2 days of focused work to a UCT-based solver that should
strictly improve on the current heuristic lookahead. Phase C is
contingent on whether B closes the gap.
