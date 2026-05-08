# Arcane Puzzle Solver

Tooling to crack the **Arcane Puzzle** mini-game in *Puzzles & Chaos: Frozen Castle*.
Mahjong-adjacent match-3 with a 7-slot tray, stacked tiles, and (per our hypothesis)
a fixed structural layout per level with randomized tile skins.

## Hypothesis

The underlying puzzle structure is **fixed across retries** of a level — only the
visual skin on each tile randomizes. If true, retries leak structural information:
stack positions, depths, dependency graph, and the *grouping* of which tile-positions
form triplets together. Whether the grouping is also fixed is one of the first
questions we want to test.

## Phases

1. **Vision pipeline** — screenshot → board grid + tray + level number → JSON.
2. **Data model** — per-level structural data; per-run observations; diff tool to
   compare two runs of the same level.
3. **Solver** — dependency graph, linchpin detection, search respecting the
   7-slot tray constraint.

## Layout

```
data/
  screenshots/    # Raw screenshots dropped in here
  levels/         # Per-level JSON: grid, stacks, observed runs
  tiles/          # Tile fingerprint library (perceptual hashes + cropped art)
src/
  vision/         # Screenshot decoding (board detection, tile crops, hashing)
  model/          # Board state dataclasses, JSON schema
  solver/         # (later) dependency graph + search
scripts/
  extract_board.py  # CLI: screenshot path -> JSON board state
```

## Mechanics observed

- **Main board**: irregular cluster of tiles, stacked 2–4 deep. Only the topmost
  tile per position is tappable; lower tiles are partially visible (ghosted).
- **Queues**: in some levels, additional tile positions sit outside the main
  cluster, fed by wood-grain "edge-on stack" queues (visible as striped wooden
  strips). Each queue has one visible head tile; popping it reveals the next.
- **Tray**: 7 slots at the bottom. Tap a tile → moves to tray. Three identical
  tiles auto-clear. Tray full without a match → loss.
- **Boosts**: Withdraw / Retreat / Refresh — assumed unavailable for solving.

## Setup

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Workflow

1. Drop a screenshot into `data/screenshots/`.
2. Run `python scripts/extract_board.py data/screenshots/foo.png`.
3. Inspect the resulting JSON in `data/levels/<level>/runs/`.
4. New unique tiles get auto-IDs (`tile_001`...) in `data/tiles/`. Label them
   later via a small naming tool.
