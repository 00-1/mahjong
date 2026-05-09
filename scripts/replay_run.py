#!/usr/bin/env python3
"""Replay a run, surface its losing decisions, suggest where strategy fails.

Methodology for refining strategy: for each run that ended badly, walk
the saved state files and:

1. Identify the LAST step where the solver had a strong move (TRIPLET
   or PROBABLE) — call that the "strategic peak"
2. Identify the FIRST EXPLORE step (where the solver had no triplet) —
   call that the "fork" where the run started losing
3. Between fork and end: track tray growth, identify which taps
   caused trouble (tile types that would never form triplets)
4. Identify "stuck tiles": types with visible_count >= 3 that we had a
   chance to clear but didn't

Usage:
    python scripts/replay_run.py <run_id>
    python scripts/replay_run.py --all-lost            # all losing runs
    python scripts/replay_run.py --suggest-improvements

Outputs structured findings — feeds the strategy-refinement workflow.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_run(run_dir: Path) -> dict:
    meta = json.loads((run_dir / "meta.json").read_text())
    states = []
    for sf in sorted(run_dir.glob("t*.state.json")):
        states.append(json.loads(sf.read_text()))
    decisions = []
    for df in sorted(run_dir.glob("t*.decision.json")):
        decisions.append(json.loads(df.read_text()))
    log = []
    log_path = run_dir / "log.jsonl"
    if log_path.exists():
        for line in log_path.read_text().splitlines():
            try:
                log.append(json.loads(line))
            except Exception:
                pass
    outcome = {}
    if (run_dir / "outcome.json").exists():
        outcome = json.loads((run_dir / "outcome.json").read_text())
    return {"meta": meta, "states": states, "decisions": decisions,
            "log": log, "outcome": outcome, "run_dir": run_dir}


def analyze_run(run: dict) -> dict:
    """Identify strategic peak, fork, and losing pattern."""
    states = run["states"]
    decisions = run["decisions"]
    if not decisions:
        return {"verdict": "no_data"}

    # Walk decisions: find last TRIPLET (strategic peak) and first EXPLORE (fork)
    strategic_peak = -1
    fork = -1
    triplet_count = 0
    explore_count = 0
    for i, d in enumerate(decisions):
        rc = d.get("reason_code", "")
        if rc == "TRIPLET":
            strategic_peak = i
            triplet_count += 1
        if rc == "EXPLORE":
            explore_count += 1
            if fork < 0:
                fork = i

    findings = {
        "run_id": run["meta"]["run_id"],
        "level": run["meta"]["level"],
        "status": run["meta"].get("status"),
        "outcome_notes": run["outcome"].get("notes"),
        "total_steps": len(states),
        "triplet_decisions": triplet_count,
        "explore_decisions": explore_count,
        "strategic_peak_step": strategic_peak,
        "fork_step": fork,
    }

    # Tray growth pattern after the fork
    if fork >= 0 and fork < len(states):
        tray_progression = []
        for s in states[fork:]:
            tray = sum(1 for t in s.get("tray", []) if t.get("tile_id"))
            tray_progression.append(tray)
        findings["tray_after_fork"] = tray_progression
        findings["tray_max_after_fork"] = max(tray_progression) if tray_progression else 0

    # Stuck-tile analysis at fork: which tile types had >= 3 visible but
    # weren't being completed? Suggests a missing or wrong solver heuristic.
    if fork >= 0 and fork < len(states):
        fork_state = states[fork]
        tile_counts = Counter()
        for c in fork_state.get("main_board", []):
            if c.get("tile_id"):
                tile_counts[c["tile_id"]] += 1
        for q in fork_state.get("queues", []):
            if q.get("tile_id"):
                tile_counts[q["tile_id"]] += 1
        for t in fork_state.get("tray", []):
            if t.get("tile_id"):
                tile_counts[t["tile_id"]] += 1
        # Stuck = >= 3 visible but solver chose EXPLORE (no triplet found)
        stuck = {tid: n for tid, n in tile_counts.items() if n >= 3}
        if stuck:
            findings["stuck_tiles_at_fork"] = stuck

    # Bad taps: explore taps that added to tray without clearing
    if fork >= 0:
        bad_taps = []
        for i in range(fork, len(decisions) - 1):
            d = decisions[i]
            if d.get("reason_code") == "EXPLORE":
                tap = d.get("tap")
                if not tap:
                    continue
                tile = d.get("label", d.get("tile_id"))
                # Did the tray grow?
                before = states[i] if i < len(states) else None
                after = states[i + 1] if i + 1 < len(states) else None
                if before and after:
                    before_tray = sum(1 for t in before.get("tray", []) if t.get("tile_id"))
                    after_tray = sum(1 for t in after.get("tray", []) if t.get("tile_id"))
                    if after_tray > before_tray:
                        bad_taps.append({
                            "step": i, "tile": tile,
                            "location": tap.get("location"),
                            "tray_growth": after_tray - before_tray,
                        })
        findings["bad_explore_taps"] = bad_taps[:10]  # cap output
        findings["bad_explore_count"] = len(bad_taps)

    return findings


def suggest_strategy_changes(findings_list: list[dict]) -> list[str]:
    """Cross-run pattern analysis: aggregate findings, propose tweaks."""
    suggestions = []

    losses = [f for f in findings_list if f.get("status") == "lost"]
    if not losses:
        suggestions.append("No losing runs to learn from yet.")
        return suggestions

    # Common: ran out of triplets, had >= 3 of some tile but couldn't reach
    common_stuck_tiles = Counter()
    for f in losses:
        for tid, n in (f.get("stuck_tiles_at_fork") or {}).items():
            common_stuck_tiles[tid] += 1
    if common_stuck_tiles:
        top = ", ".join(f"{tid}({n})" for tid, n in common_stuck_tiles.most_common(5))
        suggestions.append(
            f"Stuck-tile candidates across losses: {top}. These tiles had >=3 "
            f"visible at the fork step but weren't cleared. Likely all 3 are "
            f"blocked by neighbors. Solver should attempt unblocking sequences."
        )

    # Common: hit fork early relative to total steps
    avg_fork = sum(f.get("fork_step", 0) for f in losses if f.get("fork_step", -1) >= 0)
    if losses:
        avg_fork /= len(losses)
        suggestions.append(
            f"Average fork (last triplet decision) at step {avg_fork:.1f}. "
            f"After that we explore-tap into tray-fill. Strategy refinement: "
            f"when we hit fork, BEFORE exploring, scan dim tiles for the "
            f"tile types we have 2 of in tray — those are highest-leverage "
            f"unblock targets."
        )

    # Tray growth pattern
    tray_growths = []
    for f in losses:
        if f.get("tray_after_fork"):
            tray_growths.extend(f["tray_after_fork"])
    if tray_growths:
        suggestions.append(
            f"Tray progression after fork (across all losses): "
            f"min={min(tray_growths)}, max={max(tray_growths)}, "
            f"avg={sum(tray_growths) / len(tray_growths):.1f}. "
            f"If max consistently hits 7, the explore-mode is making "
            f"things worse. Consider an early-stop heuristic: when "
            f"in EXPLORE and tray >= 5, only tap if the tap completes "
            f"a near-triplet (2 of a kind already in tray)."
        )

    return suggestions


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run_id", nargs="?", default=None,
                   help="Specific run id to replay (default: all losing runs)")
    p.add_argument("--all", action="store_true", help="Process all runs")
    p.add_argument("--all-lost", action="store_true",
                   help="Process all runs that ended in loss")
    p.add_argument("--suggest-improvements", action="store_true",
                   help="Output cross-run pattern analysis + suggestions")
    p.add_argument("--runs-dir", type=Path,
                   default=ROOT / "data" / "runs")
    args = p.parse_args()

    if args.run_id:
        targets = [args.runs_dir / args.run_id]
    elif args.all_lost:
        targets = []
        for rd in sorted(args.runs_dir.iterdir() if args.runs_dir.exists() else []):
            if not rd.is_dir():
                continue
            meta_path = rd / "meta.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text())
            if meta.get("status") == "lost":
                targets.append(rd)
    elif args.all:
        targets = [d for d in sorted(args.runs_dir.iterdir() if args.runs_dir.exists() else []) if d.is_dir()]
    else:
        # default: all runs
        targets = [d for d in sorted(args.runs_dir.iterdir() if args.runs_dir.exists() else []) if d.is_dir()]

    findings = []
    for rd in targets:
        if not rd.exists() or not rd.is_dir():
            continue
        try:
            run = load_run(rd)
        except Exception as e:
            continue
        f = analyze_run(run)
        findings.append(f)
        print(json.dumps(f, indent=2))

    if args.suggest_improvements and findings:
        print("\n=== Strategy refinement suggestions ===")
        for s in suggest_strategy_changes(findings):
            print(f"- {s}")

        # Also surface path-library candidates: if many runs ended in
        # 'abandoned' from setup_error or NOT_A_PUZZLE patterns, those
        # are LLM-time-sinks worth scripting.
        from collections import Counter
        outcome_reasons = Counter(f.get("outcome_notes", "") for f in findings)
        if outcome_reasons:
            print("\n=== Path-library candidates ===")
            print("(paths that recur across runs and might be scriptable)")
            for reason, n in outcome_reasons.most_common(10):
                if n >= 2:
                    print(f"- {n} runs ended with notes='{reason}'. "
                          f"If repeatable, add to docs/path_library/TODO.md.")
            print()
            print("Also check: docs/path_library/failures.jsonl — review existing")
            print("scripted-path failures via `scripts/review_paths.py`.")


if __name__ == "__main__":
    main()
