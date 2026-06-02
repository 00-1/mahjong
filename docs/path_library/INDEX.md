# Scripted paths — index

Update when you add or modify a script.

| Path | Script | Status | Calibration | Notes |
|---|---|---|---|---|
| Home → puzzle gameplay | `scripts/navigate.py go --level N` | scripted | per-device, save to `data/navigation_config.json` | Vision-based Continue detection. Falls through to `needs_llm` if ambiguous yellow buttons |
| Post-loss recovery (Tip modal → Discard → LOSE → Challenge Again → fresh puzzle) | `scripts/restart.py` | scripted | per-device, save to `data/restart_config.json` | Calibrated coords + auto-resolution scaling |
| Play loop (snap → decide → tap → verify) | `scripts/autoplay.py` | scripted | none — pipeline native | Adaptive wait, Hungarian tap matching, triplet bursts, occult learning |
| Multi-attempt session (autoplay × N levels) | `scripts/session.py` | scripted | none | Pause-between-attempts gives LLM a window to navigate |
| Pre-flight: is this a puzzle screen? | `scripts/agent.py check` | scripted | none — vision-based | Tile-face count heuristic |
| Per-step decision | `scripts/agent.py decide` | scripted | none | Returns reason_code (TRIPLET / EXPLORE / GAME_OVER / NOT_A_PUZZLE / etc.) |

## Path failure log

Failures get appended to `failures.jsonl` (in this directory). Format:

```jsonl
{"ts": "2026-05-09T12:34:56Z", "path": "navigate.go", "script": "scripts/navigate.py",
 "run_id": "run_...", "failure_reason": "ambiguous_continue_button",
 "step": "continue_button", "candidates": [...]}
```

Run `scripts/review_paths.py` to summarize trends.
