"""Run lifecycle: managing per-game playthrough state.

Each "run" is one attempt at a level. Created when the agent starts a new
level, finalized when the level is won, lost, or abandoned. The run
directory accumulates: every screenshot, every extracted state, every
decision the solver made, plus a final outcome record.

Layout:
    data/runs/<run_id>/
        meta.json            — level, started_at, status, etc.
        t000.png             — initial screenshot (bytes only stored if --keep-screenshots)
        t000.state.json      — extracted state at step 0
        t000.decision.json   — solver recommendation at step 0
        t001.png, t001.state.json, t001.decision.json...
        outcome.json         — written at end_run
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path


@dataclass
class RunMeta:
    run_id: str
    level: int
    started_at: str
    last_step: int = 0
    status: str = "in_progress"  # "in_progress" | "won" | "lost" | "abandoned"
    notes: str = ""


@dataclass
class StepRecord:
    step: int
    screenshot_path: str
    state_path: str
    decision_path: str
    timestamp: str


def new_run_id(level: int, prefix: str = "run") -> str:
    """Generate a deterministic run id from current time + level."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}_l{level:02d}"


def run_dir(runs_root: Path, run_id: str) -> Path:
    return runs_root / run_id


def start_run(runs_root: Path, level: int, run_id: str | None = None) -> RunMeta:
    if run_id is None:
        run_id = new_run_id(level)
    rd = run_dir(runs_root, run_id)
    rd.mkdir(parents=True, exist_ok=True)
    meta = RunMeta(
        run_id=run_id,
        level=level,
        started_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )
    (rd / "meta.json").write_text(json.dumps(asdict(meta), indent=2))
    return meta


def load_meta(runs_root: Path, run_id: str) -> RunMeta | None:
    p = run_dir(runs_root, run_id) / "meta.json"
    if not p.exists():
        return None
    return RunMeta(**json.loads(p.read_text()))


def save_meta(runs_root: Path, meta: RunMeta) -> None:
    (run_dir(runs_root, meta.run_id) / "meta.json").write_text(json.dumps(asdict(meta), indent=2))


def record_step(
    runs_root: Path,
    run_id: str,
    step: int,
    screenshot_src: Path,
    state: dict,
    decision: dict,
    *,
    keep_screenshot: bool = True,
) -> StepRecord:
    rd = run_dir(runs_root, run_id)
    rd.mkdir(parents=True, exist_ok=True)
    name = f"t{step:03d}"
    screenshot_dest = rd / f"{name}.png"
    state_dest = rd / f"{name}.state.json"
    decision_dest = rd / f"{name}.decision.json"
    if keep_screenshot:
        shutil.copyfile(screenshot_src, screenshot_dest)
    state_dest.write_text(json.dumps(state, indent=2))
    decision_dest.write_text(json.dumps(decision, indent=2))
    rec = StepRecord(
        step=step,
        screenshot_path=str(screenshot_dest.relative_to(runs_root.parent.parent)) if keep_screenshot else "",
        state_path=str(state_dest.relative_to(runs_root.parent.parent)),
        decision_path=str(decision_dest.relative_to(runs_root.parent.parent)),
        timestamp=datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )
    return rec


def end_run(runs_root: Path, run_id: str, status: str, notes: str = "") -> None:
    meta = load_meta(runs_root, run_id)
    if meta is None:
        return
    meta.status = status
    meta.notes = notes
    save_meta(runs_root, meta)
    rd = run_dir(runs_root, run_id)
    outcome = {
        "run_id": run_id,
        "status": status,
        "notes": notes,
        "ended_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    (rd / "outcome.json").write_text(json.dumps(outcome, indent=2))


def latest_run_for_level(runs_root: Path, level: int) -> str | None:
    """Find the most recent run for a given level (sorted by run_id timestamp)."""
    if not runs_root.exists():
        return None
    candidates = []
    for p in runs_root.iterdir():
        if not p.is_dir():
            continue
        meta = load_meta(runs_root, p.name)
        if meta and meta.level == level and meta.status == "in_progress":
            candidates.append(p.name)
    return max(candidates) if candidates else None


def next_step_number(runs_root: Path, run_id: str) -> int:
    rd = run_dir(runs_root, run_id)
    existing = sorted(rd.glob("t*.state.json"))
    return len(existing)
