"""Analyze accumulated runs: timing breakdown, win rates, common failure
modes, per-anchor depth observations.

Usage:
    python scripts/analyze_runs_v2.py [--level N]

Reads data/runs/<run_id>/log.jsonl + state files and outputs a summary
dashboard. Useful for:
- Spotting timing bottlenecks (which steps are slow?)
- Identifying levels that frequently lose
- Per-anchor depth distribution (anchor X is depth>=2 in 80% of runs)
- Tile recognition confidence audit (any cells assigned at high distance?)
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

import click

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "data" / "runs"


def load_run(run_dir: Path) -> dict:
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return {}
    meta = json.loads(meta_path.read_text())
    log_lines = []
    log_path = run_dir / "log.jsonl"
    if log_path.exists():
        for line in log_path.read_text().splitlines():
            try:
                log_lines.append(json.loads(line))
            except Exception:
                pass
    state_files = sorted(run_dir.glob("t*.state.json"))
    states = []
    for sf in state_files:
        try:
            states.append(json.loads(sf.read_text()))
        except Exception:
            pass
    outcome_path = run_dir / "outcome.json"
    outcome = json.loads(outcome_path.read_text()) if outcome_path.exists() else {}
    return {"meta": meta, "log": log_lines, "states": states, "outcome": outcome,
            "run_dir": run_dir}


@click.command()
@click.option("--level", type=int, default=None, help="Filter to a single level")
@click.option("--runs-dir", type=click.Path(path_type=Path), default=RUNS_DIR)
def main(level: int | None, runs_dir: Path) -> None:
    runs = []
    for d in sorted(runs_dir.iterdir() if runs_dir.exists() else []):
        if not d.is_dir():
            continue
        r = load_run(d)
        if not r.get("meta"):
            continue
        if level is not None and r["meta"].get("level") != level:
            continue
        runs.append(r)

    if not runs:
        click.echo("no matching runs found")
        return

    click.echo(f"\n=== {len(runs)} runs analyzed (level filter: {level}) ===\n")

    # Outcomes
    statuses = Counter(r["meta"].get("status") for r in runs)
    click.echo("Outcomes:")
    for s, c in sorted(statuses.items(), key=lambda x: -x[1]):
        click.echo(f"  {s}: {c}")

    # Per-level win rate
    by_level = defaultdict(list)
    for r in runs:
        by_level[r["meta"]["level"]].append(r["meta"].get("status"))
    click.echo("\nPer-level outcome distribution:")
    for lvl in sorted(by_level):
        results = by_level[lvl]
        won = sum(1 for s in results if s == "won")
        click.echo(f"  level {lvl}: {len(results)} runs, {won} won ({won/len(results):.0%})")

    # Timing breakdown across all runs
    decide_times = []
    tap_times = []
    wait_times = []
    for r in runs:
        for ev in r["log"]:
            if "decide_ms" in ev:
                decide_times.append(ev["decide_ms"])
            if "tap_ms" in ev:
                tap_times.append(ev["tap_ms"])
            if "wait_ms" in ev:
                wait_times.append(ev["wait_ms"])

    def stats(vals, label):
        if not vals:
            click.echo(f"  {label}: no data")
            return
        click.echo(f"  {label}: n={len(vals)} median={median(vals)}ms mean={mean(vals):.0f}ms max={max(vals)}ms")

    click.echo("\nStep timing (ms):")
    stats(decide_times, "decide")
    stats(tap_times, "tap_cmd")
    stats(wait_times, "adaptive_wait")

    # Tile recognition confidence audit
    distance_distribution = Counter()
    high_distance_cells = []
    for r in runs:
        for s in r["states"]:
            for cell_list, src in [(s.get("main_board", []), "main"),
                                    (s.get("queues", []), "queue"),
                                    (s.get("tray", []), "tray")]:
                for c in cell_list:
                    d = c.get("tile_id_distance")
                    if d is None:
                        continue
                    bucket = (d // 10) * 10
                    distance_distribution[bucket] += 1
                    if d >= 50:
                        loc = (c.get("row"), c.get("col")) if src == "main" else c.get("queue_id") or c.get("slot")
                        high_distance_cells.append({
                            "run": r["meta"]["run_id"], "level": r["meta"]["level"],
                            "src": src, "loc": loc, "tile_id": c.get("tile_id"),
                            "distance": d,
                        })
    click.echo("\nTile pHash distance distribution (10-buckets):")
    for bucket in sorted(distance_distribution):
        n = distance_distribution[bucket]
        click.echo(f"  [{bucket}, {bucket+10}): {n}")
    if high_distance_cells:
        click.echo(f"\n{len(high_distance_cells)} cells assigned at distance >= 50 (worth auditing):")
        for c in high_distance_cells[:10]:
            click.echo(f"  {c}")
        if len(high_distance_cells) > 10:
            click.echo(f"  ... and {len(high_distance_cells) - 10} more")

    # Verify success rate
    verify_events = []
    for r in runs:
        for ev in r["log"]:
            if ev.get("event") in ("verify", "verify_burst"):
                verify_events.append(ev)
    if verify_events:
        success_count = sum(1 for ev in verify_events if ev.get("success"))
        click.echo(f"\nVerify outcomes: {success_count}/{len(verify_events)} successful "
                   f"({success_count/len(verify_events):.1%})")
        miss_reasons = Counter(ev.get("reason") for ev in verify_events if not ev.get("success"))
        if miss_reasons:
            click.echo("Miss reason distribution:")
            for reason, n in miss_reasons.most_common():
                click.echo(f"  {reason}: {n}")

    # Per-anchor depth observations across runs
    anchor_depth_counts: dict = defaultdict(lambda: Counter())
    for r in runs:
        lvl = r["meta"]["level"]
        for s in r["states"]:
            for c in s.get("main_board", []):
                key = (lvl, c.get("row"), c.get("col"))
                d = c.get("stack_depth")
                if d is not None:
                    anchor_depth_counts[key][d] += 1
    if anchor_depth_counts:
        click.echo("\nPer-anchor depth observations (across all states of all runs):")
        for key in sorted(anchor_depth_counts)[:20]:
            counts = anchor_depth_counts[key]
            d_str = ", ".join(f"d{d}:{n}" for d, n in sorted(counts.items()))
            lvl, r, c = key
            click.echo(f"  L{lvl} ({r},{c}): {d_str}")
        if len(anchor_depth_counts) > 20:
            click.echo(f"  ... and {len(anchor_depth_counts) - 20} more anchors")


if __name__ == "__main__":
    main()
