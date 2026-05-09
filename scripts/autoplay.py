#!/usr/bin/env python3
"""Self-driving play loop: screenshot, decide, tap, sleep — no LLM in the loop.

Plays a single level autonomously. Logs every step under
`data/runs/<run_id>/`. Exits when the level is won, lost, or stuck.

Usage:
    python scripts/autoplay.py --level 8 [options]

Exit codes:
    0  won
    1  lost
    2  abandoned (stuck, max-steps, ADB error, etc.)
    3  setup error (adb not connected, level not found, etc.)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.autoplay_lib import (
    adaptive_wait_for_change,
    adb_check_device,
    adb_tap,
    heuristic_outcome,
    snap_and_extract,
    state_signature,
)
from src.agent.decide import decide as decide_fn
from src.agent.dim_learn import (
    aggregate_dim_accuracy,
    predict_dim,
    verify_predictions_vs_state,
)
from src.agent.occult import (
    aggregate_occult_accuracy,
    predict_occult_at_anchors,
    update_anchor_priors,
    verify_anchor_predictions,
)
from src.agent.run import end_run, record_step, save_meta, start_run
from src.agent.stats import integrate_run
from src.agent.verify import verify_tap, verify_triplet_burst


TRIPLET_REASONS = {"TRIPLET", "PROBABLE"}
TAP_RETRY_OFFSETS = [(0, 0), (0, -8), (0, 8), (-8, 0), (8, 0), (-8, -8), (8, 8)]


class MasterLog:
    """Append-only jsonl log per run. Open once, write line per event."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = path.open("a")

    def emit(self, event: str, **fields) -> None:
        rec = {"event": event, "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z", **fields}
        self.fh.write(json.dumps(rec) + "\n")
        self.fh.flush()
        # Also stdout for live monitoring
        print(json.dumps(rec))

    def close(self) -> None:
        try:
            self.fh.close()
        except Exception:
            pass


def load_labels(tiles_dir: Path) -> dict:
    idx = tiles_dir / "index.json"
    if not idx.exists():
        return {}
    return {
        e["tile_id"]: e.get("label") or e["tile_id"]
        for e in json.loads(idx.read_text()).get("entries", [])
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--level", type=int, required=True)
    p.add_argument("--device", default=None)
    p.add_argument("--max-steps", type=int, default=200)
    p.add_argument("--min-wait", type=float, default=0.3,
                   help="Minimum delay after a tap before checking for change")
    p.add_argument("--max-wait", type=float, default=3.0,
                   help="Maximum delay polling for state change after a tap")
    p.add_argument("--triplet-extra-wait", type=float, default=1.0,
                   help="Additional wait after triplet bursts for clear animation")
    p.add_argument("--shot-dir", type=Path, default=Path("/tmp"))
    p.add_argument("--keep-screenshots", action="store_true")
    p.add_argument("--run-id", default=None)
    p.add_argument("--no-stats", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--tiles-dir", type=Path, default=ROOT / "data" / "tiles")
    p.add_argument("--max-tap-retries", type=int, default=2)
    p.add_argument("--health-check-interval", type=int, default=20,
                   help="Verify ADB device is reachable every N steps")
    p.add_argument("--learn-dim", action="store_true",
                   help="Predict dim tiles each step + verify against next state's bright tiles. "
                        "Adds ~0.5-1s per step but builds dim-ID accuracy training data.")
    p.add_argument("--learn-occult", action="store_true",
                   help="Anchor-driven occult prediction (multi-method ensemble incl. ORB). "
                        "Slower than --learn-dim (~1.5-3s/step) but much higher accuracy. "
                        "Writes data/levels/NN/occult_accuracy.json + anchor_priors.json.")
    p.add_argument("--use-lookahead", action="store_true",
                   help="Use multi-step search-based solver in EXPLORE regime "
                        "(when no immediate triplet is available). Default depth 3. "
                        "Greedy still picks for immediate triplets — search is only "
                        "consulted when there's no clear win.")
    p.add_argument("--lookahead-depth", type=int, default=3,
                   help="Search depth when --use-lookahead is set (default 3).")
    args = p.parse_args()

    device_arg = ["-s", args.device] if args.device else []

    if adb_check_device(device_arg) != "device":
        print(f"[autoplay] adb device unreachable. Connect first.", file=sys.stderr)
        return 3

    args.shot_dir.mkdir(parents=True, exist_ok=True)
    labels = load_labels(args.tiles_dir)
    label_fn = lambda t: labels.get(t, t) if t else "?"  # noqa: E731

    runs_dir = ROOT / "data" / "runs"
    meta = start_run(runs_dir, args.level, args.run_id)
    run_id = meta.run_id
    log = MasterLog(runs_dir / run_id / "log.jsonl")
    log.emit("run_start", run_id=run_id, level=args.level, started_at=meta.started_at,
             min_wait=args.min_wait, max_wait=args.max_wait, max_tap_retries=args.max_tap_retries)

    step = 0
    final_status = "abandoned"
    final_reason = ""
    consecutive_not_a_puzzle = 0
    consecutive_missed_taps = 0
    consecutive_unchanged = 0  # state didn't change after tap (potentially-stuck)
    last_state = None
    pre_npz_state = None  # last state where the puzzle WAS visible (for heuristic_outcome)
    last_dim_predictions: list = []  # for verifying against next bright state (--learn-dim)
    last_occult_predictions: dict = {}  # anchor-keyed predictions (--learn-occult)
    run_started = time.time()
    levels_root = ROOT / "data" / "levels"
    run_root = runs_dir / run_id

    # Lazy-loaded — only when --learn-occult requested
    _template_for_occult = None
    _library_samples_for_occult = None
    def _occult_setup():
        nonlocal _template_for_occult, _library_samples_for_occult
        if _template_for_occult is None:
            from src.vision.template import load_template, scale_template
            tp = ROOT / "data" / "levels" / f"{args.level:02d}" / "template.json"
            if tp.exists():
                _template_for_occult = load_template(tp)
        if _library_samples_for_occult is None:
            from src.vision.peek import load_library_samples
            _library_samples_for_occult = load_library_samples(args.tiles_dir)
        return _template_for_occult, _library_samples_for_occult

    # Initial snapshot
    shot_path = args.shot_dir / f"autoplay_{run_id}_init.png"
    state_dict, image_size = snap_and_extract(device_arg, shot_path, args.level)
    if state_dict is None:
        log.emit("error", msg="initial snap or extract failed")
        end_run(runs_dir, run_id, "abandoned", "initial snap failed")
        log.close()
        return 3

    try:
        while step < args.max_steps:
            # Health check periodically
            if step > 0 and step % args.health_check_interval == 0:
                if adb_check_device(device_arg) != "device":
                    log.emit("error", step=step, msg="adb disconnected at health check")
                    final_status = "abandoned"
                    final_reason = "adb_disconnected"
                    break

            # Compute decision from current state. Build the combined
            # occult+priors prediction map for lookahead simulation.
            occult_for_solver = None
            if args.use_lookahead:
                from src.solver.economy import merge_occult_and_priors
                occult_for_solver = merge_occult_and_priors(
                    last_occult_predictions if last_occult_predictions else None,
                    levels_root, args.level,
                    confidence_threshold=0.5, prior_min_obs=3,
                )
                if not occult_for_solver:
                    occult_for_solver = None
            decide_t0 = time.time()
            decision = decide_fn(
                ROOT / "data" / "extractions" / f"level_{args.level:02d}"
                / shot_path.stem / "state.json",
                image_size or (1220, 2712),
                label_fn=label_fn,
                use_lookahead=args.use_lookahead,
                lookahead_depth=args.lookahead_depth,
                occult_predictions=occult_for_solver,
            )
            decide_ms = int((time.time() - decide_t0) * 1000)
            record_step(
                runs_dir, run_id, step, shot_path, state_dict, decision,
                keep_screenshot=args.keep_screenshots,
            )
            meta.last_step = step
            save_meta(runs_dir, meta)
            last_state = state_dict
            reason = decision.get("reason_code", "")
            # Track the most recent state where the puzzle was actually visible
            if reason != "NOT_A_PUZZLE":
                pre_npz_state = state_dict

            log.emit(
                "decision", step=step, reason=reason,
                tap=decision.get("tap") if args.verbose else None,
                tray=decision.get("state", {}).get("tray_filled"),
                score=decision.get("score"),
                decide_ms=decide_ms,
                num_alternatives=len(decision.get("alternatives", [])),
            )

            # Verify last step's dim predictions against this step's bright state
            if args.learn_dim and last_dim_predictions:
                comparisons = verify_predictions_vs_state(last_dim_predictions, state_dict)
                if comparisons:
                    correct = sum(1 for c in comparisons if c["correct"])
                    log.emit("dim_verify", step=step,
                             total=len(comparisons), correct=correct,
                             comparisons=comparisons)
                    if not args.no_stats:
                        aggregate_dim_accuracy(levels_root, args.level, comparisons)

            # Predict dim tiles in this step's state for verification next step
            if args.learn_dim:
                dim_t0 = time.time()
                preds = predict_dim(shot_path, args.level, args.tiles_dir)
                dim_ms = int((time.time() - dim_t0) * 1000)
                pred_path = run_root / f"t{step:03d}.dim_predictions.json"
                pred_path.write_text(json.dumps([
                    {**vars(p), "bbox": list(p.bbox)} for p in preds
                ], indent=2))
                log.emit("dim_predict", step=step,
                         predictions_count=len(preds),
                         dim_ms=dim_ms,
                         confident=sum(1 for p in preds if p.confidence_score < 0.5))
                last_dim_predictions = preds

            # Occult prediction: anchor-driven, multi-method ensemble (better)
            if args.learn_occult:
                # Verify last step's occult predictions
                if last_occult_predictions:
                    comparisons = verify_anchor_predictions(last_occult_predictions, state_dict)
                    if comparisons:
                        correct = sum(1 for c in comparisons if c["correct"])
                        log.emit("occult_verify", step=step,
                                 total=len(comparisons), correct=correct,
                                 comparisons=comparisons)
                        if not args.no_stats:
                            aggregate_occult_accuracy(levels_root, args.level, comparisons)

                # Predict for next step
                template_for_occult, library_samples = _occult_setup()
                if template_for_occult is not None and library_samples:
                    import cv2
                    bgr = cv2.imread(str(shot_path))
                    if bgr is not None:
                        # Build set of currently-bright anchor keys
                        bright_keys = set()
                        for c in state_dict.get("main_board", []):
                            if c.get("tile_id"):
                                bright_keys.add(("main_board", c["row"], c["col"]))
                        for q in state_dict.get("queues", []):
                            if q.get("tile_id"):
                                bright_keys.add(("queue", q["queue_id"]))

                        occult_t0 = time.time()
                        preds = predict_occult_at_anchors(
                            bgr, template_for_occult, bright_keys, library_samples,
                        )
                        occult_ms = int((time.time() - occult_t0) * 1000)
                        # Save per-step
                        pred_path = run_root / f"t{step:03d}.occult_predictions.json"
                        pred_path.write_text(json.dumps([
                            {"anchor_key": list(k), **{kk: vv for kk, vv in vars(p).items() if kk != "anchor_key"}}
                            for k, p in preds.items()
                        ], indent=2))
                        log.emit("occult_predict", step=step,
                                 predictions_count=len(preds),
                                 occult_ms=occult_ms,
                                 high_confidence=sum(1 for p in preds.values() if p.confidence >= 0.5))
                        last_occult_predictions = preds

                # Update per-anchor priors from this step's bright state
                if not args.no_stats:
                    update_anchor_priors(levels_root, args.level, state_dict)

            # Terminal states
            if decision.get("should_stop"):
                if reason == "GAME_OVER":
                    final_status = "lost"
                    final_reason = "game_over"
                    log.emit("game_over", step=step)
                    break
                if reason == "NOT_A_PUZZLE":
                    consecutive_not_a_puzzle += 1
                    log.emit("not_a_puzzle", step=step, consecutive=consecutive_not_a_puzzle)
                    if consecutive_not_a_puzzle >= 5:
                        # Use BOTH last and pre-NOT_A_PUZZLE state for context
                        final_status = heuristic_outcome(last_state, previous_state=pre_npz_state)
                        final_reason = "5x_not_a_puzzle"
                        log.emit("stop_by_heuristic", step=step,
                                 outcome=final_status,
                                 pre_npz_main=len(pre_npz_state.get("main_board", []) if pre_npz_state else []),
                                 pre_npz_tray=sum(1 for t in pre_npz_state.get("tray", []) if t.get("tile_id")) if pre_npz_state else 0)
                        break
                    time.sleep(2.0)
                    # Re-snap and try again
                    shot_path = args.shot_dir / f"autoplay_{run_id}_{step:03d}_retry.png"
                    state_dict, image_size = snap_and_extract(device_arg, shot_path, args.level)
                    if state_dict is None:
                        final_status = "abandoned"
                        final_reason = "snap_failed_after_npz"
                        break
                    step += 1
                    continue
                final_status = "abandoned"
                final_reason = reason or "unknown"
                log.emit("stop", step=step, reason=reason, msg=decision.get("reason"))
                break

            consecutive_not_a_puzzle = 0

            # Triplet burst path
            triplet_seq = decision.get("triplet_sequence")
            if triplet_seq and len(triplet_seq) >= 2:
                log.emit(
                    "triplet_burst", step=step,
                    tile=decision.get("label"),
                    taps=len(triplet_seq),
                    locations=[t["location"] for t in triplet_seq],
                )
                burst_ok = True
                for t in triplet_seq:
                    if not adb_tap(device_arg, t["x"], t["y"]):
                        burst_ok = False
                        break
                    time.sleep(0.4)
                if not burst_ok:
                    log.emit("error", step=step, msg="burst tap failed")
                    final_status = "abandoned"
                    final_reason = "burst_tap_failed"
                    break

                # Wait for the auto-clear animation, then re-snap
                before_sig = state_signature(state_dict)
                state_dict, image_size, elapsed = adaptive_wait_for_change(
                    device_arg, args.shot_dir, args.level, before_sig,
                    min_wait=args.min_wait + args.triplet_extra_wait,
                    max_wait=args.max_wait + args.triplet_extra_wait,
                )
                if state_dict is None:
                    log.emit("error", step=step, msg="snap failed after triplet burst")
                    final_status = "abandoned"
                    final_reason = "snap_failed_post_burst"
                    break
                # Find the freshly-saved shot path for record_step's screenshot file
                # (the adaptive_wait helper creates timestamped files; we just track
                # the stem of whichever it returned)
                shot_path = _latest_shot(args.shot_dir, "autoplay_wait_")

                # Verify
                v = verify_triplet_burst(
                    decision["state"] if isinstance(decision.get("state"), dict) else {},
                    state_dict,
                    [t["location"] for t in triplet_seq],
                    decision["tile_id"],
                )
                # Note: decide()'s state summary doesn't have full main_board.
                # Use the recorded state_dict from the previous step as 'before'.
                # (The recorded step file is the actual before.)
                before_path = (
                    runs_dir / run_id / f"t{step:03d}.state.json"
                )
                if before_path.exists():
                    with open(before_path) as f:
                        before_full = json.load(f)
                    v = verify_triplet_burst(
                        before_full, state_dict,
                        [t["location"] for t in triplet_seq],
                        decision["tile_id"],
                    )
                log.emit("verify_burst", step=step,
                         success=v.success, reason=v.reason, notes=v.notes,
                         elapsed_sec=round(elapsed, 2))
                if v.success:
                    consecutive_missed_taps = 0
                    consecutive_unchanged = 0
                else:
                    consecutive_missed_taps += 1
                step += 1
                continue

            # Single-tap path (with retry on miss)
            tap = decision.get("tap")
            if not tap:
                final_status = "abandoned"
                final_reason = "no_tap_in_decision"
                break

            x, y = tap["x"], tap["y"]
            tap_attempts = 0
            tap_success = False
            before_sig = state_signature(state_dict)

            while tap_attempts <= args.max_tap_retries:
                offset = TAP_RETRY_OFFSETS[min(tap_attempts, len(TAP_RETRY_OFFSETS) - 1)]
                tap_x, tap_y = x + offset[0], y + offset[1]
                log.emit(
                    "tap", step=step,
                    x=tap_x, y=tap_y, loc=tap.get("location"),
                    tile=decision.get("label"), reason=reason,
                    score=decision.get("score"), attempt=tap_attempts + 1,
                )
                tap_t0 = time.time()
                if not adb_tap(device_arg, tap_x, tap_y):
                    log.emit("error", step=step, msg="tap failed")
                    final_status = "abandoned"
                    final_reason = "tap_command_failed"
                    break
                tap_ms = int((time.time() - tap_t0) * 1000)

                # Adaptive wait — poll until state changes or we time out
                wait_t0 = time.time()
                after_state, after_size, elapsed = adaptive_wait_for_change(
                    device_arg, args.shot_dir, args.level, before_sig,
                    min_wait=args.min_wait, max_wait=args.max_wait,
                )
                wait_ms = int((time.time() - wait_t0) * 1000)
                if after_state is None:
                    log.emit("error", step=step, msg="snap failed during wait")
                    final_status = "abandoned"
                    final_reason = "snap_failed_during_wait"
                    break

                # Verify
                v = verify_tap(
                    state_dict, after_state,
                    tap.get("location", ""), decision.get("tile_id", ""),
                )
                log.emit("verify", step=step,
                         success=v.success, reason=v.reason, notes=v.notes,
                         attempt=tap_attempts + 1,
                         tap_ms=tap_ms, wait_ms=wait_ms,
                         elapsed_sec=round(elapsed, 2))
                if v.success:
                    tap_success = True
                    consecutive_missed_taps = 0
                    consecutive_unchanged = 0
                    state_dict = after_state
                    image_size = after_size
                    shot_path = _latest_shot(args.shot_dir, "autoplay_wait_")
                    break
                # Tap missed — retry with offset
                tap_attempts += 1

            if final_reason:
                break

            if not tap_success:
                consecutive_missed_taps += 1
                log.emit("tap_miss_unrecoverable", step=step,
                         consecutive_misses=consecutive_missed_taps)
                if consecutive_missed_taps >= 3:
                    log.emit("stop", step=step, msg="3 consecutive missed taps")
                    final_status = "abandoned"
                    final_reason = "consecutive_missed_taps"
                    break
                # Even on miss, refresh state for next iteration
                shot_path = _latest_shot(args.shot_dir, "autoplay_wait_")
                state_dict, _ = snap_and_extract(device_arg, shot_path, args.level)
                if state_dict is None:
                    final_status = "abandoned"
                    final_reason = "snap_failed_after_miss"
                    break

            # Loop-detection: if state hasn't changed for many consecutive steps,
            # we're stuck even though taps "succeed"
            if state_dict is not None and last_state is not None:
                if state_signature(state_dict) == state_signature(last_state):
                    consecutive_unchanged += 1
                    if consecutive_unchanged >= 5:
                        log.emit("stop", step=step,
                                 msg="state hasn't changed in 5 steps — stuck loop")
                        final_status = "abandoned"
                        final_reason = "stuck_loop"
                        break
                else:
                    consecutive_unchanged = 0

            step += 1

        else:
            log.emit("max_steps_reached", step=step)
            final_status = "abandoned"
            final_reason = "max_steps"

    except KeyboardInterrupt:
        log.emit("keyboard_interrupt", step=step)
        final_status = "abandoned"
        final_reason = "keyboard_interrupt"
    except Exception as exc:
        log.emit("exception", step=step, msg=str(exc), type=type(exc).__name__)
        final_status = "abandoned"
        final_reason = f"exception:{type(exc).__name__}"

    end_run(runs_dir, run_id, final_status, final_reason)
    if not args.no_stats:
        levels_root = ROOT / "data" / "levels"
        stats = integrate_run(levels_root, runs_dir, run_id)
        win_rate = stats.win_rate() if stats else None
    else:
        win_rate = None

    duration = round(time.time() - run_started, 1)
    log.emit(
        "run_end",
        run_id=run_id, status=final_status, reason=final_reason,
        steps=step, level=args.level,
        duration_sec=duration, level_win_rate=win_rate,
    )
    log.close()
    return {"won": 0, "lost": 1, "abandoned": 2}.get(final_status, 2)


def _latest_shot(shot_dir: Path, prefix: str) -> Path:
    """Find the most recent file matching the prefix. Used to track which
    snap file the adaptive_wait helper produced."""
    candidates = sorted(shot_dir.glob(f"{prefix}*.png"))
    if candidates:
        return candidates[-1]
    return shot_dir / f"{prefix}fallback.png"


if __name__ == "__main__":
    sys.exit(main())
