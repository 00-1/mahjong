"""Accumulate per-level statistics across runs.

Updates `data/levels/<NN>/stats.json` after each run completes:
- runs_total, won, lost, abandoned
- avg_taps_per_run
- avg_taps_to_loss / avg_taps_to_win
- common loss patterns (tray contents at loss)
- per-anchor tile observation counts (across all runs of that level)
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class LevelStats:
    level: int
    runs_total: int = 0
    runs_won: int = 0
    runs_lost: int = 0
    runs_abandoned: int = 0
    total_taps: int = 0
    total_taps_won: int = 0
    total_taps_lost: int = 0
    common_loss_tray_tiles: dict[str, int] = field(default_factory=dict)
    per_anchor_observed_tiles: dict[str, dict[str, int]] = field(default_factory=dict)

    def win_rate(self) -> float:
        return self.runs_won / max(1, self.runs_total)

    def avg_taps_per_run(self) -> float:
        return self.total_taps / max(1, self.runs_total)


def stats_path(levels_root: Path, level: int) -> Path:
    return levels_root / f"{level:02d}" / "stats.json"


def load_stats(levels_root: Path, level: int) -> LevelStats:
    p = stats_path(levels_root, level)
    if not p.exists():
        return LevelStats(level=level)
    data = json.loads(p.read_text())
    return LevelStats(**data)


def save_stats(levels_root: Path, stats: LevelStats) -> None:
    p = stats_path(levels_root, stats.level)
    p.parent.mkdir(parents=True, exist_ok=True)
    d = asdict(stats)
    d["win_rate"] = stats.win_rate()
    d["avg_taps_per_run"] = stats.avg_taps_per_run()
    p.write_text(json.dumps(d, indent=2))


def integrate_run(levels_root: Path, runs_root: Path, run_id: str) -> LevelStats | None:
    """After a run ends, fold its data into the level's stats."""
    rd = runs_root / run_id
    meta_path = rd / "meta.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    level = meta["level"]

    stats = load_stats(levels_root, level)
    stats.runs_total += 1
    if meta["status"] == "won":
        stats.runs_won += 1
    elif meta["status"] == "lost":
        stats.runs_lost += 1
    else:
        stats.runs_abandoned += 1
    last_step = meta.get("last_step", 0)
    stats.total_taps += last_step
    if meta["status"] == "won":
        stats.total_taps_won += last_step
    elif meta["status"] == "lost":
        stats.total_taps_lost += last_step

    # Walk all states in the run, count tiles per anchor + capture loss tray
    state_files = sorted(rd.glob("t*.state.json"))
    for sf in state_files:
        try:
            s = json.loads(sf.read_text())
        except Exception:
            continue
        for cell in s.get("main_board", []):
            key = f"({cell['row']},{cell['col']})"
            tid = cell.get("tile_id")
            if not tid:
                continue
            stats.per_anchor_observed_tiles.setdefault(key, {})
            counts = stats.per_anchor_observed_tiles[key]
            counts[tid] = counts.get(tid, 0) + 1

    # Loss tray analysis: take final state if loss
    if meta["status"] == "lost" and state_files:
        final = json.loads(state_files[-1].read_text())
        tray_tiles = [t.get("tile_id") for t in final.get("tray", []) if t.get("tile_id")]
        for tid in tray_tiles:
            stats.common_loss_tray_tiles[tid] = stats.common_loss_tray_tiles.get(tid, 0) + 1

    save_stats(levels_root, stats)
    return stats
