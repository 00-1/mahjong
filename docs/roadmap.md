# Roadmap & open questions

## Hypothesis status (updated 2026-05-08)

Original hypothesis: *underlying puzzle structure is fixed across retries; only
the visual skin on each tile randomizes.*

After ingesting two independent runs of level 5 (run 1 t=0 + restart run 2 t=0):

- **Grid structure: SAME ✓** — both runs have the same 16 main-board cell
  positions and same 4 queue-head positions. The same level-5 template
  matches both with 0 unmatched detections.
- **Tile-on-position: RANDOMIZED ✗** — only 1 of 16 main-board cells holds
  the same tile (lotus at (1,4)) and only 1 of 4 queues (right_lower bee).
  Statistically consistent with random assignment.
- **Triplet groupings: RANDOMIZED ✗** — the 3-position groups that formed
  triplets in run 1 (e.g., (1,4), (2,0), (2,2) all = lotus) are NOT triplets
  in run 2 (those positions are 3 different tiles).

So we have to throw out "pre-solve the level". But structural priors are
still useful: position layout, queue placement, and (likely) stack depths
+ lean directions are fixed.

This needs validation on harder levels. User intends to gather data through
level 8+ before fully discarding the structure-fixed approach.

## Confirmed mechanics

- Main board tiles render with one of **9 candidate offset positions** when
  the top tile is removed and a lower tile is exposed: origin (depth 1) plus
  4 diagonal half-tile shifts and 4 cardinal half-tile shifts. The offset
  direction reveals the stack's "lean".
- Queue heads can appear **anywhere along their wood-grain strip's cx
  range**, not at a fixed cx. The cx position shifts as tiles are consumed.
- Tray has **7 evenly-spaced slots** at the bottom. Loss occurs when all 7
  fill without a triplet.
- Some stacks are **depth >= 3** (loss state revealed sunflower / dandelion
  tiles that were never visible in earlier states of the same run).

## Anomalies to investigate

1. **Empty positions can refill.** Run 1 t=9 had (0,1), (0,3), (1,4), (2,4)
   as positions with no detection (presumed depth-1 stacks now cleared).
   Run 1 loss state has tiles at (0,1), (0,3), (2,4) again. Strongly
   suggests **queue tiles refill main-board cells** when adjacent main slots
   empty, not just shifting along the queue strip itself.
2. **Two visually-similar blue butterflies** (`blue_butterfly_a` and
   `blue_butterfly_b`) get distinct pHashes (distance > 40). Need to verify
   the game treats them as match-3 distinct or whether this is a
   recognition false-split.

## Open questions for the user

- Is your phone's screenshot resolution always 1220x2712?
- What's at the top of the screen when this game loads (any other UI)?
- How do queue heads get *consumed*? When you tap a queue head, does
  the next tile in the queue strip slide in, or does the queue strip
  shift, or does it feed into main-board cells?
- Is there an animation when tiles get added to the tray? (matters for
  whether sequential screenshots can be captured cleanly mid-animation.)
- Does the game show the *total tile count* anywhere (like "X of Y
  remaining")?

## Roadmap

### Phase 1: vision pipeline (mostly done)

- [x] HSV-based tile face detection (works on any state)
- [x] Per-level template; snap-to-anchor extraction
- [x] 9-direction offset coverage for depth-2 reveals
- [x] Tile fingerprint library (pHash, threshold 28)
- [x] Hungarian (globally-optimal) bipartite matching
- [x] Tray slot detection (7 slots)
- [x] Queue head detection (flexible cx)
- [ ] Stack-depth estimation from a *single* image (the corner-cream
      heuristic doesn't work; need a smarter signal)
- [ ] Partially-occluded tile recognition (template-match against library
      crops with partial masks)
- [ ] Level number OCR / template match
- [ ] Boost-count OCR

### Phase 2: data model

- [x] BoardState dataclass + JSON serialization
- [x] Diff tool that infers tap events between two states
- [x] Triplet grouping from tap events
- [ ] Run history: ingest a sequence of screenshots, build a tap timeline
- [ ] Cross-run merge: combine multiple runs of the same level into one
      structural picture (depths, lean directions per anchor)

### Phase 3: solver

- [ ] Dependency graph: which positions are blocked by which (uses stack
      depths + the queue-refill mechanic if confirmed)
- [ ] Reactive solver: given current visible state, pick the next tap to
      maximize expected score
- [ ] Forward search with the 7-slot tray constraint

### Phase 4: feedback loop

- [ ] If structure-fixed eventually holds for level 8+, accumulate per-level
      structural priors across many runs
- [ ] Constraint propagation between vision and solver: hidden tile
      identities can be partially inferred from visible-tile counts +
      multiple-of-3 invariant

## Useful screenshots to gather

In rough priority order:

1. **Level 8+ initial state, multiple runs.** Repeated runs of the same
   level. Tests whether structure-fixed holds at later levels even though
   it didn't at level 5.
2. **Mid-game state of any level showing 3-5 tiles in the tray** (no
   triplet yet). For tray contents validation and tray-state diffing.
3. **A queue head being tapped + the next state immediately after.** Tells
   us whether queues feed into main-board cells or just advance internally.
4. **Levels 6 and 7** initial states. Map out how the layout grows in
   complexity between 5 and the "really hard" 8.
5. **Screenshots of any animation in progress** if you can catch one. Tells
   us about timing for any future automation.
