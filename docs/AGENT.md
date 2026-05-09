# Agent integration contract

This document describes how an autonomous play agent (running on a phone /
ADB) should interact with the solver via `scripts/agent.py`.

The agent itself doesn't need to import any Python modules from this repo
— it shells out to `agent.py` and parses JSON from stdout. That keeps the
contract stable.

## Game navigation (before the play loop)

The Arcane Puzzle is buried inside an Events menu. Before calling
`agent.py start-run`, the agent needs to navigate:

```
home -> Event Center -> Festival Event tab -> Arcane Puzzle ->
  scroll to current level -> tap Continue (or Restart for fresh run)
```

Reference screenshots with annotations are in `docs/navigation/`. See
`docs/navigation/README.md` for details. The rest of this document
assumes the agent has reached the gameplay screen (Level N visible at
top, tiles laid out).

## Recommended: use `autoplay.py` (no LLM in inner loop)

For speed, the entire play loop is now a Python script that runs natively
on the agent's host. The LLM only needs to navigate to the gameplay
screen and launch:

```
python scripts/autoplay.py --level 8
```

`autoplay.py` then:
- Takes screenshots via `adb exec-out screencap`
- Runs the solver (`extract_board.py` + `decide`)
- Taps via `adb shell input tap`
- Verifies each tap actually had its expected effect (state changed at
  the tapped position)
- Retries with small coord offsets if a tap missed
- Bursts triplet sequences (3 taps in a row) without re-snapping
- Sleeps for animations (configurable per-tap and per-triplet settle)
- Logs every step under `data/runs/<run_id>/`
- Exits with status: 0=won, 1=lost, 2=abandoned, 3=setup error

Key flags:

| Flag | Default | Purpose |
|---|---|---|
| `--level N` | required | Which level the script should drive |
| `--device SERIAL` | auto | adb device serial (only needed if multiple) |
| `--max-steps N` | 200 | Bail after N steps to prevent infinite loops |
| `--tap-settle SEC` | 1.5 | Wait after each non-triplet tap |
| `--triplet-settle SEC` | 2.5 | Wait after a triplet-completing tap (clear animation) |
| `--no-verify` | off | Skip post-tap verification (faster but riskier) |
| `--max-tap-retries N` | 2 | If a tap misses, retry with small offset up to N times |
| `--keep-screenshots` | off | Save the screenshot of every step under the run dir |
| `--verbose` | off | Per-step JSON log of decisions |

### Tap verification

After each tap, autoplay re-snapshots and checks:
- For a single tap: did the tile at the tapped position change (vanish or
  reveal a depth-2 tile)?
- For a triplet burst: did all 3 positions change AND did the tray
  auto-clear the triplet?

If verification fails, autoplay retries with a small pixel offset (±8 in
each direction) before giving up. After 3 consecutive missed taps the
run is abandoned (probably an unrecoverable scroll / popup state).

### Adaptive wait

After each tap, autoplay polls for state change instead of using a fixed
sleep:
- After `--min-wait` (default 0.3s), snap+extract.
- If the state hasn't changed yet, sleep 0.25s and retry.
- Up to `--max-wait` (default 3.0s) total polling.

So fast animations complete in ~0.5s rather than the old fixed 1.5s. Slow
animations still get up to 3s.

For triplet bursts, an extra `--triplet-extra-wait` (default 1.0s) is
added on top — the auto-clear takes longer than a single tap.

### Reused snap

The verification snap is reused as the next iteration's decision input,
saving one full `screencap + extract` per step (~700ms-1s on a typical
phone).

### Master log

Each run gets `data/runs/<run_id>/log.jsonl` — single jsonl file, one
event per line. Tail it live or grep after the fact:

```
tail -f data/runs/run_*_l08/log.jsonl
grep '"event":"verify"' data/runs/run_*_l08/log.jsonl | jq -c .
```

### Health check

Every `--health-check-interval` steps (default 20), autoplay verifies
the ADB device is still reachable. If not, abandons cleanly with
status=abandoned, reason=adb_disconnected.

### Loop detection

If the visible state hasn't changed for 5 consecutive steps (despite
"successful" taps according to verify), autoplay abandons with
reason=stuck_loop. Catches edge cases where the game enters an
unexpected state we keep mis-recovering from.

### LLM agent's role

With autoplay + session.py, the LLM agent only handles:
1. Environment setup (adb, Termux deps, keepalive) — once per session
2. Navigation from home → gameplay screen — once per level (or per
   re-attempt, if a level was lost)
3. Launching `session.py` (which calls `autoplay.py` per attempt)
4. Between attempts/levels: handle popups, navigate to next level via
   level list

For the play loop itself, zero LLM context cycles per move.

## Session orchestration

For an unattended run of multiple levels with retries on loss:

```
python scripts/session.py \
    --level 8 --level 9 --level 10 \
    --max-attempts 3 \
    --inter-attempt-pause 8.0
```

Calls `autoplay.py` per attempt. Records every attempt's outcome,
pauses between attempts to give the agent time to navigate back to the
gameplay screen, and returns once all levels are processed.

Exit code: 0 if all listed levels were won at least once, 1 otherwise.
Per-level stats (`data/levels/NN/stats.json`) accumulate as expected.

The `--inter-attempt-pause` is a hard sleep — the LLM agent should use
that window to dismiss popups and navigate to the next gameplay screen.
If it can't, the next attempt's autoplay will return `setup_error`
(extraction fails on a non-puzzle screen) and the session moves on.

## Loop overview (lower-level, when autoplay isn't usable)

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

### `check` (preflight)

```
python scripts/agent.py check --screenshot path.png
```

Output:
```json
{"looks_like_puzzle": true, "tile_faces_found": 21, "image_size": {"w": 1220, "h": 2712}}
```

Cheap and fast — detects bright tile faces only, doesn't run the full
extraction. If `looks_like_puzzle: false`, the agent is on the wrong
screen (popup / level list / load screen) and should navigate before
calling `decide`. The `decide` command itself will also return
`reason_code: NOT_A_PUZZLE` in this case, but `check` is faster.

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
| `WAIT_FOR_AUTOCLEAR` | Tray contains a triplet about to clear | Sleep ~1.5 sec, re-screenshot, retry decide |
| `GAME_OVER` | Loss state detected | End run with status=lost |
| `NOT_A_PUZZLE` | Screenshot doesn't look like the puzzle gameplay screen | Navigate / dismiss popup, take new screenshot, retry decide |
| `NO_MOVES` | Pipeline ran but found no tappable tiles | Treat as `NOT_A_PUZZLE` — likely a non-game screen |
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
