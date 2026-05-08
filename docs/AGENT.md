# Agent integration contract

This document describes how an autonomous play agent (running on a phone /
ADB) should interact with the solver via `scripts/agent.py`.

The agent itself doesn't need to import any Python modules from this repo
— it shells out to `agent.py` and parses JSON from stdout. That keeps the
contract stable.

## Loop overview

```
1. agent.py start-run --level N             -> outputs {"run_id": "..."}
2. while game in progress:
     - take screenshot via ADB
     - agent.py decide --screenshot <path> --level N --run-id <id>
         -> outputs decision JSON
     - if decision.should_stop:
           agent.py end-run --run-id <id> --status (won|lost|abandoned)
           break
     - adb tap decision.tap.x decision.tap.y
     - sleep ~1.5 sec for animation
3. After level transitions:
     - agent.py end-run --run-id <id> --status won
     - start a new run for the next level
```

## Commands

### `start-run`

```
python scripts/agent.py start-run --level 8 [--run-id custom_id]
```

Output:
```json
{"run_id": "run_20260508_223145_l08", "level": 8, "started_at": "2026-05-08T22:31:45Z"}
```

If `--run-id` is omitted, generates a timestamped one.

### `decide`

```
python scripts/agent.py decide --screenshot path/to/screenshot.png --level 8 --run-id <id>
```

Output (success):
```json
{
  "should_stop": false,
  "reason_code": "TRIPLET",
  "tap": {"x": 837, "y": 956, "location": "(3,5)"},
  "tile_id": "tile_008",
  "label": "lotus",
  "confidence": 0.95,
  "score": 8.0,
  "reason": "3x lotus: tap (0,5) + (4,3) + (4,5)",
  "alternatives": [
    {"x": ..., "y": ..., "location": "...", "tile_id": "...", "label": "...", "score": ..., "reason": "..."}
  ],
  "state": {
    "level": 8,
    "tray_filled": 0,
    "tray": [],
    "main_board_count": 18,
    "queue_count": 3,
    "tile_counts": {"lotus": 4, "dandelion": 3, ...}
  },
  "image_size": {"w": 1220, "h": 2712},
  "run_id": "run_...",
  "step": 0
}
```

Output (stop signal):
```json
{
  "should_stop": true,
  "reason_code": "GAME_OVER",
  "reason": "tray full with no completable triplet — game lost",
  "state": {...}
}
```

### Reason codes

| Code | Meaning | Agent action |
|---|---|---|
| `TRIPLET` | Tap completes (or progresses) a visible triplet | Execute the tap with high confidence |
| `PROBABLE` | Reasonable move, no immediate triplet | Execute the tap |
| `EXPLORE` | Speculative tap, low confidence | Execute the tap or alternatively call agent again with a different tactic |
| `GAME_OVER` | Loss state detected | End run with status=lost |
| `NO_MOVES` | Pipeline didn't find any tappable tiles | End run with status=abandoned |
| `EXTRACTION_FAILED` | Image processing crashed | Retry, or end run with status=abandoned |
| `STATE_MISSING` | State JSON wasn't created | As above |
| `NO_MAPPING` | Internal: couldn't map suggested location to pixel coords | End run with status=abandoned |

### Tap coordinate system

`tap.x` and `tap.y` are in the **screenshot's pixel space**, with origin at
top-left, x increasing right, y increasing down. Match what `adb shell
input tap <x> <y>` expects (Android device coords).

Note: if your phone's screen resolution differs from the screenshot
resolution (ADB sometimes captures at native res while screen is rendered
differently), you may need to scale.

### `end-run`

```
python scripts/agent.py end-run --run-id <id> --status won
```

Status options: `won` | `lost` | `abandoned`.

## Per-run logs

Each run produces `data/runs/<run_id>/`:
- `meta.json` — level, run_id, started_at, last_step, status
- `t000.png`, `t000.state.json`, `t000.decision.json` — initial state + decision
- `t001.*`, `t002.*`, ... — subsequent steps
- `outcome.json` — written by `end-run`

Add `--no-keep-screenshot` to `decide` to skip storing PNGs (saves space).

## Suggested ADB integration

```bash
RUN_ID=$(python scripts/agent.py start-run --level 8 | jq -r .run_id)
LEVEL=8

while true; do
    adb exec-out screencap -p > /tmp/shot.png
    DECISION=$(python scripts/agent.py decide \
        --screenshot /tmp/shot.png \
        --level $LEVEL \
        --run-id $RUN_ID)

    SHOULD_STOP=$(echo "$DECISION" | jq -r .should_stop)
    if [ "$SHOULD_STOP" = "true" ]; then
        REASON=$(echo "$DECISION" | jq -r .reason_code)
        STATUS=$([ "$REASON" = "GAME_OVER" ] && echo "lost" || echo "abandoned")
        python scripts/agent.py end-run --run-id $RUN_ID --status $STATUS
        break
    fi

    X=$(echo "$DECISION" | jq -r .tap.x)
    Y=$(echo "$DECISION" | jq -r .tap.y)
    adb shell input tap $X $Y
    sleep 1.5
done
```

## Known limitations to handle on the agent side

1. **Animations**: after a tap, the game animates the tile flying to the
   tray. The next screenshot must be taken AFTER the animation settles
   (~1.5 seconds typical). Sleep accordingly.
2. **Triplet auto-clear animation**: when 3 tiles match, they animate out
   of the tray. Same — wait for the animation.
3. **Level transitions**: between levels, there may be a "level cleared"
   popup that the agent has to dismiss before starting the next run.
   The solver doesn't handle UI popups; the agent should detect them
   (e.g., look for the "next level" button via OCR or template match).
4. **Loss recovery**: when the solver returns `GAME_OVER`, the level is
   typically already lost in-game. The agent should `end-run` and decide
   whether to retry the same level.

## Knowledge accumulation

The repo accumulates knowledge over runs:
- `data/tiles/index.json` — tile fingerprint library, grows as new tile
  arts are encountered
- `data/levels/<NN>/template.json` — per-level anchor positions, built
  from the first clean initial state
- `data/runs/<run_id>/` — full play history per run
- `data/levels/_stats/` — (future) aggregated stats: win rate, common
  failure modes, etc.

The agent doesn't need to update any of these directly — `agent.py` does
it as a side effect of `decide` calls.
