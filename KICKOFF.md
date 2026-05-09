# Kickoff — pull this branch and run

You (the phone agent) just pulled this branch. Follow these steps. If anything
returns `needs_llm` or fails, fall back to LLM judgment — that's expected on
first invocation of new scripts that need calibration.

## 0. Verify environment

```bash
adb devices                  # should list a 'device' (not 'unauthorized')
adb shell wm size            # note the resolution, e.g. 1080x2400
```

If adb isn't connected or shows `unauthorized`, see `docs/fresh_setup.md`.

## 1. Calibrate navigation (once per device)

These coords are from a Poco F6 (1220×2712). The script auto-scales them
to your device's actual resolution.

```bash
python scripts/navigate.py calibrate \
    --event-banner-x 1029 --event-banner-y 242 \
    --festival-tab-x 610 --festival-tab-y 400 \
    --arcane-puzzle-x 610 --arcane-puzzle-y 2400 \
    --scroll-from-x 600 --scroll-from-y 2200 \
    --scroll-to-x 600 --scroll-to-y 1700 \
    --continue-y-hint 1981 \
    --num-scrolls 1
```

Saves to `data/navigation_config.json`.

## 2. Calibrate restart (once per device)

We don't have a screenshot of the post-loss "Tip" modal yet, so you have
to find the Discard and Challenge Again button coords yourself.

**Approach**:

1. Get to a loss state (play level 8 manually until tray fills, OR run
   step 4 below and let it lose, OR just let `session.py` do it once and
   inspect a screenshot when it stalls)
2. Snap the screen and find the Discard button (yellow CTA on the right
   of the "Use Discard or Withdraw" modal)
3. Tap it, then snap the LOSE screen and find the Challenge Again
   button (yellow CTA, single-button-on-screen)
4. Use the cv2 colour-mask technique from `docs/fresh_setup.md` if eyeballing
   on a downscaled JPEG is unreliable
5. Run:
   ```bash
   python scripts/restart.py \
       --discard-x <X> --discard-y <Y> \
       --challenge-again-x <X> --challenge-again-y <Y>
   ```
   First invocation will execute the recovery flow with the provided coords
   and save them to `data/restart_config.json`. Subsequent calls scale them
   automatically.

If you can't find the modal because we're not at a loss yet, skip this for
now — the session will halt at first loss and ask you to calibrate then.

## 3. Make sure you're at the puzzle gameplay screen

```bash
python scripts/navigate.py go --level 8
```

Returns 0 if it lands on the puzzle. If it returns 1 (`needs_llm`),
take over and navigate manually for now — then add a TODO entry to
`docs/path_library/TODO.md` describing what blocked the script.

## 4. Run the session

```bash
python scripts/session.py \
    --level 8 \
    --max-attempts 5 \
    --max-consecutive-losses 4 \
    --use-lookahead --lookahead-depth 3 \
    --learn-occult \
    --keep-screenshots
```

What this does:
- Up to 5 attempts at level 8
- Halts after 4 consecutive losses (don't burn all 10 challenge tickets if
  strategy is broken)
- Uses multi-step lookahead in EXPLORE mode (when no immediate triplet
  available)
- Builds occult-prediction accuracy data
- Saves screenshots so we can post-hoc analyze

Between attempts the session pauses 8 seconds — that's your window to
navigate back to the gameplay screen if we lost. If `restart.py` is
calibrated, you can run it during the pause. Otherwise navigate manually.

## 5. Path library workflow (your job during runs)

As you (the LLM agent) work, watch for:

- **Repetitive paths that aren't yet scripted** → add to `docs/path_library/TODO.md`
- **Scripts that fail in unexpected ways** → automatically logged to
  `docs/path_library/failures.jsonl` via `src/agent/path_log.py`
- **Recurring outcome patterns** → check `python scripts/review_paths.py`

After a multi-run session, run:

```bash
python scripts/replay_run.py --all-lost --suggest-improvements
python scripts/review_paths.py
```

These tell you what failure patterns showed up, which scripted paths need
patching, and what new paths might be worth scripting.

## 6. Commit your run data

After the session ends:

```bash
git add data/runs/ data/levels/ data/tiles/ docs/path_library/
git commit -m "session run data + new tile samples + path failures"
git push origin claude/general-session-Yg2yw
```

The run logs (`data/runs/<run_id>/`) and accumulated stats
(`data/levels/NN/stats.json`, `occult_accuracy.json`, `anchor_priors.json`)
are what we use to refine strategy on the next iteration.

## What success looks like

After 5 attempts at level 8 with `--learn-occult`:
- `data/levels/08/stats.json` shows actual win rate (was 0% on the
  fake-won runs)
- `data/levels/08/occult_accuracy.json` has ~50-200 verified predictions
  with confidence-bucketed accuracy
- `data/levels/08/anchor_priors.json` has per-anchor distributions from
  ~100 observed states
- `data/runs/run_*_l08/log.jsonl` for each attempt has full timing +
  decision history

If win rate is < 20%, the strategy is broken — `replay_run.py` output
will surface what's failing. We iterate from there.

## Reference docs

- `docs/AGENT.md` — full agent contract (commands, reason codes, etc.)
- `docs/strategy_plan.md` — strategy refinement methodology
- `docs/path_library/README.md` — path library system
- `docs/navigation/README.md` — calibrated nav screenshots
- `docs/fresh_setup.md` — Termux setup notes
- `docs/agent_environment.md` — adb / keepalive / device gotchas
- `data/README.md` — what's stored where
