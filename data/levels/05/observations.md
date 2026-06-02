# Level 5 — observations

Manual ground-truth read of `data/screenshots/level_05/run_01_t000.jpg`,
recorded before the vision pipeline exists so we have something to grade
the first extraction pass against.

## Layout summary

- **Main board**: irregular cluster, ~6 columns wide, with depth varying by
  position. Ghosted edges suggest most positions are 2–3 deep.
- **Side queues**: 4 queue heads visible — two on the lower-left (orange
  lantern + blue kite above it), two on the lower-right (yellow bee + pink
  daisy above it). Each is fed by a wood-grain "edge-on stack" suggesting
  several queued tiles behind the visible head.
- **Tray**: empty.
- **Boost counts**: 0 / 0 / 0 (Withdraw / Retreat / Refresh).

## Top-of-stack tiles by approximate (row, col)

Row indices are visual-top-to-bottom of bright tiles in the main cluster.

| Cell | Tile (descriptive) |
|------|-----|
| (1, 0) | pink_plumeria (red-ribboned) |
| (1, 1) | yellow_butterfly_orb |
| (1, 2) | yellow_bee |
| (1, 3) | pink_daisy |
| (1, 4) | rainbow_pinwheel |
| (1, 5) | pink_daisy |
| (2, 0) | orange_lantern |
| (2, 1) | swallow |
| (2, 2) | (empty — center gap) |
| (2, 3) | (empty — center gap) |
| (2, 4) | orange_lotus |
| (2, 5) | blue_butterfly |
| (3, 0) | orange_lotus |
| (3, 1) | blue_kite |
| (3, 2) | orange_lotus |
| (3, 3) | yellow_butterfly_orb |
| (3, 4) | yellow_butterfly_orb |
| (3, 5) | yellow_paper_crane |

Plus a top "ghost" row (row 0) where only depth indicators show — no bright
tile fronts. These are sub-positions hidden under the row 1 tiles.

## Queue heads

| Position | Head tile |
|----------|-----------|
| lower-left, upper queue | blue_kite |
| lower-left, lower queue | orange_lantern |
| lower-right, upper queue | pink_daisy |
| lower-right, lower queue | yellow_bee |

## Tile inventory observed in this screenshot

Distinct tile arts seen (visible tops + queue heads):

1. pink_plumeria
2. yellow_butterfly_orb
3. yellow_bee
4. pink_daisy
5. rainbow_pinwheel
6. orange_lantern
7. swallow
8. orange_lotus
9. blue_butterfly
10. blue_kite
11. yellow_paper_crane

11 distinct tile arts. For a clearable level, the total tile count across
board + queues must be a multiple of 3. Counting visible top-of-stack tiles
alone (18 main + 4 queue heads = 22) is just an underestimate — actual total
includes everything stacked + queued.
