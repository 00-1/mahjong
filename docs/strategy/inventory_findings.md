# Tile inventory findings — level 8

Investigation into the user's hypothesis: "each level introduces one
rare set; red flower seems rarer on level 8." Multiplicity is always
divisible by 3.

## Method

Counted definitive per-tile instances per run by:
- For each anchor (r,c): unique `(stack_depth, tile_id)` pairs across
  all states in the run. Each represents one physical tile that
  occupied that anchor at that depth at some point.
- For each queue strip: unique tile_ids ever seen there.
- Filtered to "real plays" (≥5 saved states) — early abandons don't
  reveal the full level.

Source: `data/runs/run_2026050*_l08/` × 6 real runs (112251, 112851,
125119, 125241, 125654, 125914).

## Result

| tile     | max obs / run | runs seen | inferred count |
|----------|--------------:|----------:|---------------:|
| tile_008 |             6 |       6/6 |              6 |
| tile_013 |             6 |       6/6 |              6 |
| tile_002 |             5 |       5/6 |              6 |
| tile_004 |             5 |       5/6 |              6 |
| tile_011 |             5 |       5/6 |              6 |
| tile_007 |             4 |       5/6 |              6 |
| tile_005 |             4 |       5/6 |              6 |
| tile_009 |             4 |       4/6 |              6 |
| tile_001 |             3 |       6/6 |              3 |
| tile_003 |             3 |       5/6 |              3 |
| tile_010 |             3 |       6/6 |              3 |
| tile_012 |             3 |       5/6 |              3 |
| tile_006 |             2 |       6/6 |        3 (?) |
| tile_015 |             2 |       1/6 |  noise (?) |

## Key takeaways

1. **Mixed multiplicities confirmed.** Level 8 has both 3-instance
   and 6-instance tile types. Two tiles directly observed at 6
   instances; another six observed at 4-5, all consistent with 6.
   Five tiles plateau at 3.

2. **The "dead tile in tray" heuristic is WRONG without inventory.**
   Current `state_value` flags a tray tile as dead if
   `visible + tray < 3`. For 6-instance tile_008, that fires at
   visible=1, tray=1 even though 4 copies are still hidden. The
   solver is currently being too pessimistic about explored taps
   for high-multiplicity tiles.

3. **tile_006 is the user's "rare" candidate.** Plateau at 2
   instances despite 100% appearance. Two possibilities:
   - True count is 3 with 1 always hidden in a queue strip we don't
     fully observe across runs (queues are progressive).
   - True count is 6 with 4 of them somewhere we never reach (deep
     stacks beyond depth 2, or specific queue positions).
   Need a longer run that gets further into the level to settle this.
   Anchor priors confirm: tile_006 is at (0,5) (34/41 obs) and
   (2,4) (27/41) — both d1, both nearly deterministic.

4. **Per-run variance** (compare runs 112251 vs 112851):
   - 112251 saw tile_002 = 3, tile_011 = 0
   - 112851 saw tile_002 = 5, tile_011 = 5
   This isn't observation incompleteness alone; some tile pools may
   be drawn-per-run, supporting the user's "alternative set"
   hypothesis. Needs more runs to confirm.

5. **tile_015 in 1/6 runs at max 2** — almost certainly tile-id
   misclassification. The library likely doesn't have a clean
   sample for it, or it's a near-confusion of an existing tile
   (the agent's `tile_id_distance` was probably high). Worth
   investigating in the vision pipeline separately.

## Implication for strategy

The solver needs a per-level inventory file. Proposed schema:

```json
// data/levels/08/inventory.json
{
  "level": 8,
  "estimated_total_tiles": 63,
  "tiles": {
    "tile_001": {"count": 3, "confidence": "confirmed"},
    "tile_008": {"count": 6, "confidence": "confirmed"},
    "tile_002": {"count": 6, "confidence": "high"},
    "tile_006": {"count": 3, "confidence": "uncertain", "max_observed": 2},
    ...
  }
}
```

`state_value`'s dead-tray detection becomes:

```
total_for_tile = visible + tray + estimated_hidden
estimated_hidden = inventory[tid].count - cleared_so_far - visible - tray
if total_for_tile < 3 AND tray > 0:
    dead_in_tray += tray
```

The "cleared_so_far" requires tracking triplets cleared during the
run (we already log this in `record_step`).

Builder script: walk all completed runs of a level, take the per-run
max for each tile_id, round up to the nearest multiple of 3, output
the JSON. Re-run weekly as data accumulates.

## Next investigations gated on more data

- Confirm tile_006's true count (need a long run that explores
  queues fully).
- Validate "alternative draw pool" — if some tile sets are drawn
  per-game, runs should naturally cluster into "saw tile_009 vs
  didn't" partitions with consistent secondary correlations.
- Per-anchor-position inventory: which anchors host 6-instance
  tiles? If high-multiplicity tiles concentrate in stacked anchors,
  unblock-cost is asymmetric across the board.
