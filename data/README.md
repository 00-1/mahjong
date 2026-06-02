# Data layout

Everything the agent + solver write goes here. Designed so that future
analysis tools can read it without invoking any pipeline code.

## Layout

```
data/
  screenshots/              # Original screenshots organized by level
    level_NN/
      run_NN_t000.jpg       # Manually-labeled screenshots from PR comments
      ...
  extractions/              # Per-screenshot extraction outputs
    level_NN/
      <stem>/
        state.json          # Structured BoardState
        overlay.jpg         # Annotated visualization
  levels/                   # Per-level structural priors + stats
    NN/
      template.json         # Anchor positions for the level
      stats.json            # Aggregated win rate, per-anchor tile observations
  tiles/                    # Tile fingerprint library
    index.json              # tile_id -> phash, label, samples[]
    samples/
      tile_001_00.jpg       # Up to 4 sample crops per tile
  runs/                     # Per-run play history
    run_<timestamp>_lNN/
      meta.json             # level, started_at, status, last_step
      log.jsonl             # Master event log (one event per line)
      t000.png              # Screenshot at step 0 (only with --keep-screenshots)
      t000.state.json       # Extracted board at step 0
      t000.decision.json    # Solver recommendation at step 0
      ...                   # tNNN files per step
      outcome.json          # Final result
```

## Per-step JSON

### `tNNN.state.json` (BoardState)

```json
{
  "level": 8,
  "image": "data/screenshots/level_08/run_01_t000.jpg",
  "image_size": [1220, 2712],
  "main_board": [
    {
      "row": 0, "col": 0,
      "bbox": [84, 722, 143, 143],
      "tile_id": "tile_001",
      "stack_depth": 1,
      "tile_id_distance": 16
    }
  ],
  "queues": [
    {"queue_id": "left_lower", "bbox": [...], "tile_id": "...", "tile_id_distance": 14}
  ],
  "tray": [
    {"slot": 0, "bbox": [...], "tile_id": "...", "tile_id_distance": 12}
  ],
  "boost_counts": {"withdraw": 0, "retreat": 0, "refresh": 0}
}
```

`tile_id_distance` (NEW) is the pHash distance to the matched library
entry — lower means more confident match. Distance >= 50 with our
threshold of 60 means the match is borderline; worth auditing.

### `tNNN.decision.json`

```json
{
  "should_stop": false,
  "reason_code": "TRIPLET",
  "tap": {"x": 1064, "y": 712, "location": "(0,5)"},
  "tile_id": "tile_008",
  "label": "lotus",
  "confidence": 0.95,
  "score": 8.0,
  "reason": "3x lotus: tap (0,5) + (4,3) + (4,5)",
  "alternatives": [...],
  "triplet_sequence": [...],
  "state": {...},
  "image_size": {"w": 1220, "h": 2712}
}
```

### `log.jsonl` events

Each line is a JSON object with at minimum `event` and `ts`:

```json
{"event": "run_start", "run_id": "...", "level": 8, "ts": "..."}
{"event": "decision", "step": 0, "reason": "TRIPLET", "decide_ms": 850, "score": 8.0, ...}
{"event": "tap", "step": 0, "x": 1064, "y": 712, "loc": "(0,5)", "attempt": 1, ...}
{"event": "verify", "step": 0, "success": true, "tap_ms": 12, "wait_ms": 450, "elapsed_sec": 0.46, ...}
{"event": "triplet_burst", "step": 1, "taps": 3, "locations": ["(0,5)", "(4,3)", "(4,5)"], ...}
{"event": "verify_burst", "step": 1, "success": true, ...}
{"event": "game_over", "step": 25, ...}
{"event": "run_end", "status": "lost", "steps": 25, "duration_sec": 87, ...}
```

Useful events to grep:
- `verify` / `verify_burst` — was each tap successful?
- `decision` — what was the solver thinking?
- `tap` — actual ADB taps issued
- `error`, `stop`, `exception` — failure modes
- `not_a_puzzle`, `game_over`, `run_end` — terminal states

Step timing fields (`decide_ms`, `tap_ms`, `wait_ms`) let you profile
where time is going across many runs.

### `outcome.json`

```json
{
  "run_id": "run_20260509_002145_l08",
  "status": "won",
  "notes": "5x_not_a_puzzle",
  "ended_at": "2026-05-09T00:24:31Z"
}
```

`status` is one of `won`, `lost`, `abandoned`. `notes` records the
reason when relevant (e.g. `consecutive_missed_taps`, `stuck_loop`,
`exception:RuntimeError`).

## Per-level data

### `levels/NN/template.json`

Anchor positions for the level. Built from the first clean t=0 capture
of the level; reused for all subsequent extractions of that level.

### `levels/NN/stats.json`

Updated by `agent.py end-run` (and `autoplay.py`) after every run:

```json
{
  "level": 8,
  "runs_total": 12,
  "runs_won": 3,
  "runs_lost": 6,
  "runs_abandoned": 3,
  "total_taps": 167,
  "common_loss_tray_tiles": {"tile_008": 5, ...},
  "per_anchor_observed_tiles": {
    "(0,0)": {"tile_001": 4, "tile_004": 6, "tile_007": 2}
  },
  "win_rate": 0.25,
  "avg_taps_per_run": 13.9
}
```

`per_anchor_observed_tiles` accumulates which tile appeared at each
anchor across all runs. Over many runs, this tells us the level's
tile pool distribution per position.

## Analysis tools

- `scripts/analyze_runs_v2.py` — across all stored runs, computes:
  outcome distribution, per-level win rate, step timing breakdown,
  tile recognition confidence audit, verify success rate, per-anchor
  depth observations.

- `scripts/analyze_runs.py` (older) — manual hypothesis tests
  (initial top tile fixed? depth-2 tile fixed? lean fixed?) — historical.

- `scripts/anchor_history.py` — per-anchor observation history across
  all states; surfaces tile diversity per position.

- `scripts/analyze_pool.py` — per-level tile pool distribution.

## What's deliberately NOT captured

- **Verification snapshots** — currently the *_wait_*.png files used
  during adaptive_wait are saved in `--shot-dir` (default `/tmp`), not
  in the run dir. They get cleaned up with `/tmp`. If you want them
  preserved per-run, point `--shot-dir` at a run-specific dir or copy
  them at run end.
- **Full alternative ranking** — only top 3 alternatives saved per
  decision. The rest aren't expensive to recompute from the state.
- **Animation frames** — between decisions we don't capture intermediate
  states.

## Recommended retention

`data/screenshots/` and `data/extractions/` for manually-curated
references — keep forever.

`data/runs/` grows fast with `--keep-screenshots`. For long-running
sessions, consider `--no-keep-screenshots` (state + decision JSON +
log are usually enough to reconstruct what happened).
