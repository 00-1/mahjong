# Strategy investigation — index

Deep planning docs for moving past the current heuristic lookahead
toward a principled solver. Created while a phone-side run is in
flight, intentionally NOT yet implemented to avoid muddying the
experiment.

## Read in this order

1. **[`inventory_findings.md`](inventory_findings.md)** — empirical
   tile-inventory analysis from accumulated level-8 runs. Confirms
   mixed multiplicities (3-instance and 6-instance tiles coexist),
   identifies tile_006 as the "rare" candidate, surfaces why the
   current dead-tray penalty is too pessimistic.

2. **[`information_extraction.md`](information_extraction.md)** —
   what the vision pipeline currently extracts vs what it could.
   Documents the 0%-accuracy live occult predictor, sketches a
   Bayesian replacement, and lists 7 high-value information gaps
   (partial-occlusion matching, animation-frame tile-id capture,
   queue-position priors, etc.).

3. **[`optimal_solver_plan.md`](optimal_solver_plan.md)** —
   theoretical framing (POMDP, NP-hardness via de Bondt 2012,
   match-three NP-hardness via Walsh / Gualà), survey of candidate
   solvers (single-determinization UCT, ISMCTS, POMCP), and a
   3-phase implementation plan with citations and LOC estimates.

## TL;DR conclusions

- The bounded-buffer triple-match-with-hidden-tiles variant we have
  isn't in the literature. The closest published result (de Bondt
  2012) proves the deterministic peeking variant NP-complete, so no
  exact poly-time optimal exists.
- Recommended next solver: **single-determinization UCT** (~250
  LOC), upgrading to ISMCTS only if strategy fusion bites.
- Three Phase-A foundations gate the solver work:
  inventory builder, cleared-history tracking, Bayesian reveal
  posterior. Together they replace the broken occult ensemble and
  give the solver correct supply numbers.
- The 0%-accurate live occult predictor is currently dead weight
  burning 5-8s/step; replacing it with a closed-form Bayesian
  update (deterministic, <50ms) is the single biggest perf win
  available.

## Status

All three docs are planning artifacts. No code changes pending.
Wait for the in-flight phone run to complete + post-run review,
then prioritise from `optimal_solver_plan.md` Phase A.
