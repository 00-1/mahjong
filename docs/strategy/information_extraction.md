# Information extraction — what we know vs what we could know

Inventory of state we currently extract from screenshots, what's
unreliable, and what could be added. Strategy quality is bounded by
state quality, so this is the leverage point above the solver itself.

## Currently extracted (reliable)

| Signal | Source | Reliability |
|--------|--------|-------------|
| Top-tile bounding box on main board | `detect_tile_faces` (HSV mask + contours) | High — used in production |
| Tile-id of fully-visible top tiles | pHash + NCC template match | High — `tile_id_distance` typically < 20 |
| Tray slot contents (7 fixed positions) | Anchor-based crop + same matcher | High |
| Queue strip top tile | Anchor-based | Medium-high |
| Stack depth (1 or 2) | Heuristic on cell appearance | Medium |
| Tray fill count | Tray slot extraction | High |

## Currently extracted (unreliable)

### Occult tile prediction — 0% accuracy

`src/agent/occult.py` predicts which tile is at occluded anchors via
a 4-method ensemble (pHash + NCC + histogram + ORB). On level 8, 14
verified predictions returned 0 correct
(`data/levels/08/occult_accuracy.json`). At every confidence bucket.

This is now disabled by default (`--occult-confidence-threshold 0.99`)
and the planner falls back to anchor priors. The whole occult.py
codepath is currently dead weight in the loop — burning ~5-8 seconds
per step (`occult_predict.occult_ms` in run logs).

**Decision needed:** fix the predictor or remove it. The accumulated
data is enough for a re-design — see "Possible occult predictor v2"
below.

### Stack depth detection

`stack_depth` is set on each `MainCell` but we don't have a clear
spec for how it's determined or its accuracy. From the data, depth
values are usually 1 or 2; observed values look correct in the saved
states sampled.

**Investigation gap:** confusion-matrix analysis comparing
`stack_depth` predictions across consecutive states (depth 2 should
become 1 only after a clear). Worth verifying on next clean run.

## Currently NOT extracted (high-value gaps)

### 1. Per-level tile inventory

We know multiplicities are divisible by 3, but level 8 mixes 3-
instance and 6-instance tiles (see `inventory_findings.md`). The
solver currently assumes 3-instance for all tiles, which makes it
over-conservative on high-multiplicity tiles ("dead tray tile"
fires too eagerly).

**Fix:** per-level `inventory.json`, builder script that aggregates
across all completed runs. ~30 lines of Python.

### 2. Cleared-triplet history

We log triplet clears in `verify_burst` events but don't aggregate
into a per-run "triplets cleared so far" counter that the solver
can read at decision time. This matters for hidden-tile inference:
if all 3 instances of `tile_X` have been cleared, the planner can
prove no more `tile_X` will appear regardless of priors.

**Fix:** `BoardState` gets a `cleared_history: dict[tile_id, int]`
field. Populated from prior step logs. State_value uses
`inventory.count - cleared - visible - tray` for each tile.

### 3. Partially-visible tile identification

When a tile is partially occluded by an adjacent tile (spatial
overlap, not just stacking), the visible fragment usually contains
enough information for template matching IF we restrict matching to
the visible portion. We currently treat all non-fully-visible tiles
as "occult" and run the broken predictor on them.

**Fix sketch:** template matching with a partial-region NCC, where
the search region is the inferred visible fragment (computed from
overlapping bounding boxes of detected neighbors). This is a much
easier problem than predicting from nothing.

### 4. Animation-frame tile-id confirmation

When a tile is tapped, the in-flight animation clearly shows the
tile face for ~200-400ms before it lands in the tray. Similarly,
auto-clear animations float the cleared tiles upward. If we capture
a mid-animation screenshot we get a high-confidence read of which
tile was tapped/cleared.

We already do `adaptive_wait_for_change` which polls during this
window. We could opportunistically classify the in-flight tile from
those polls and use it as ground truth for prior reveals.

**Fix sketch:** during `adaptive_wait`, run lightweight tile-face
detection on intermediate snaps. Detected non-anchor faces in the
mid-screen region = mid-flight tiles. Match them and log as
"observed reveal." This gives free training data for the predictor
AND improves cleared-tile accounting.

### 5. Queue contents lookahead

Queues feed tiles into play. The visible head of each queue is
captured, but we don't see what's deeper in the queue. After
capacity-K observations the queue priors should converge.

**Fix:** extend `update_anchor_priors` to track queue position,
not just queue id. Currently `queue_pos[q.queue_id]` collapses
all observed values into one set; should be ordered list.

### 6. Tile-supply confirmation via animation

When a triplet auto-clears, three identical tiles fly up out of
the tray. If we capture the animation we get confirmed
`tile_id × 3` cleared. This is harder to miss than reading the
tray (which can be misclassified). And it confirms which tile was
cleared even if mid-flight obscures the tray.

**Fix:** an "animation watcher" that flags clear-events from
diff between consecutive snaps in the tray region. Same pipeline
as #4.

### 7. Level-start full-board snapshot

Right at level start, all anchors are at `stack_depth=1` so we see
the maximum exposed information. Currently the autoplay loop just
takes its initial snap and starts deciding. Worth keeping a
dedicated `level_start_state.json` per run for analytical purposes
— makes inventory-counting much easier and supports "is this level
configuration solvable" offline analysis.

**Fix:** trivial — record the first state separately.

## Possible occult predictor v2

The current predictor uses the depth-1 RGBA at the anchor (with 9
spatial offset attempts) and runs 4 vision methods. Hypothesis for
why it's at 0%: the visual signal at the occluded position is
dominated by the OVERLYING tile's pixels, not the occluded tile's.
The predictor was looking at where it thought the occluded tile
was, but the screen pixels there are actually showing the d1 tile.

Alternatives worth testing:
- **Anchor-prior alone** — current planner fallback. Empirically
  much better than the predictor (some anchors >80% top-1 accuracy
  from priors).
- **Conditioned on cleared triplets** — when 3 of `tile_X` have
  been cleared, P(d2 = tile_X) drops to 0. Use this to update the
  prior at decision time.
- **Conditioned on visible board** — the level has a fixed total
  inventory. Posterior over hidden tiles should sum to
  `total - visible - tray - cleared` per tile_id. This is a
  proper Bayesian update; very tractable with our scale.
- **Per-anchor template re-learning** — once we have enough verified
  reveals, train a per-anchor classifier. Overkill until the
  Bayesian update is proven insufficient.

**Recommendation:** delete `predict_occult_at_anchors` and replace
the call site with a Bayesian prior updater that consumes
`anchor_priors` + `cleared_history` + `inventory`. Probably 100-200
lines, fully deterministic, computable in <50ms. The 5-8s/step the
ensemble currently burns disappears.

## Priority for implementation

When the agent run completes and we resume coding:

1. **Inventory builder + state_value upgrade** (high impact, low
   risk, fully data-driven). Fixes the over-eager dead-tray penalty.
2. **Cleared-history tracking + Bayesian reveal posterior** (high
   impact, medium effort). Replaces the broken predictor with
   something correct.
3. **Animation-frame tile-id capture** (medium impact, medium
   effort). Free training data + redundancy.
4. **Partial-occlusion matching** (medium impact, medium effort).
   Recovers info we currently throw away.

Items 5-7 are nice-to-have, gated on whether items 1-4 close the
gap to "level 8 winnable."
