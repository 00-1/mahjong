"""Agent CLI — entry point for an autonomous play loop.

The phone-side agent calls this script for each step in a run:

    # Start a new run on level 8
    python scripts/agent.py start-run --level 8
    # -> outputs run_id

    # For each step in the run:
    python scripts/agent.py decide --screenshot <path> --level 8 --run-id <id>
    # -> outputs JSON with the next tap to perform

    # When the run is over (won/lost/abandoned):
    python scripts/agent.py end-run --run-id <id> --status won

JSON output is the contract — the agent should NOT need to import any of
the Python modules; it just shells out and parses stdout JSON.

See docs/AGENT.md for the contract details.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.decide import decide as decide_fn
from src.agent.run import (
    end_run as _end_run,
    load_meta as _load_meta,
    next_step_number,
    record_step,
    start_run as _start_run,
)


RUNS_DIR = ROOT / "data" / "runs"
TILES_DIR = ROOT / "data" / "tiles"


def _label_index() -> dict:
    idx_path = TILES_DIR / "index.json"
    if not idx_path.exists():
        return {}
    return {
        e["tile_id"]: e.get("label") or e["tile_id"]
        for e in json.loads(idx_path.read_text()).get("entries", [])
    }


def _label_fn():
    labels = _label_index()
    return lambda tid: labels.get(tid, tid) if tid else "?"


@click.group()
def cli():
    pass


@cli.command("start-run")
@click.option("--level", type=int, required=True)
@click.option("--run-id", type=str, default=None)
def start_run_cmd(level: int, run_id: str | None) -> None:
    """Start a new run for the given level. Outputs the run_id."""
    meta = _start_run(RUNS_DIR, level, run_id)
    print(json.dumps({"run_id": meta.run_id, "level": meta.level, "started_at": meta.started_at}))


@cli.command("decide")
@click.option("--screenshot", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--level", type=int, required=True)
@click.option("--run-id", type=str, default=None,
              help="Optional run id; if provided, this step is logged under that run")
@click.option("--no-keep-screenshot", is_flag=True,
              help="Don't save the screenshot in the run dir (smaller logs)")
def decide_cmd(screenshot: Path, level: int, run_id: str | None, no_keep_screenshot: bool) -> None:
    """Given a screenshot, recommend the next tap. Outputs decision JSON."""
    # Run extraction (creates state.json)
    extract_result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "extract_board.py"),
         str(screenshot), "--level", str(level)],
        capture_output=True, text=True,
    )
    if extract_result.returncode != 0:
        print(json.dumps({
            "should_stop": True,
            "reason_code": "EXTRACTION_FAILED",
            "reason": extract_result.stderr.strip(),
        }))
        sys.exit(1)

    state_path = (
        ROOT / "data" / "extractions" / f"level_{level:02d}" / screenshot.stem / "state.json"
    )
    if not state_path.exists():
        print(json.dumps({
            "should_stop": True,
            "reason_code": "STATE_MISSING",
            "reason": f"expected state at {state_path} but not found",
        }))
        sys.exit(1)

    # Load image dims
    import cv2
    img = cv2.imread(str(screenshot))
    image_size = (img.shape[1], img.shape[0])

    decision = decide_fn(state_path, image_size, label_fn=_label_fn())

    # Log step if a run is active
    if run_id:
        meta = _load_meta(RUNS_DIR, run_id)
        if meta is not None:
            step = next_step_number(RUNS_DIR, run_id)
            with open(state_path) as f:
                state_dict = json.load(f)
            record_step(
                RUNS_DIR, run_id, step,
                screenshot, state_dict, decision,
                keep_screenshot=not no_keep_screenshot,
            )
            decision["run_id"] = run_id
            decision["step"] = step
            meta.last_step = step
            from src.agent.run import save_meta
            save_meta(RUNS_DIR, meta)

    print(json.dumps(decision, indent=2))


@cli.command("end-run")
@click.option("--run-id", type=str, required=True)
@click.option("--status", type=click.Choice(["won", "lost", "abandoned"]), required=True)
@click.option("--notes", type=str, default="")
def end_run_cmd(run_id: str, status: str, notes: str) -> None:
    """Finalize a run with its outcome and integrate into per-level stats."""
    _end_run(RUNS_DIR, run_id, status, notes)
    from src.agent.stats import integrate_run
    levels_root = ROOT / "data" / "levels"
    stats = integrate_run(levels_root, RUNS_DIR, run_id)
    print(json.dumps({
        "run_id": run_id, "status": status,
        "level_stats": {
            "runs_total": stats.runs_total if stats else None,
            "win_rate": stats.win_rate() if stats else None,
        } if stats else None,
    }))


@cli.command("status")
@click.option("--run-id", type=str, required=True)
def status_cmd(run_id: str) -> None:
    """Show current status of a run."""
    meta = _load_meta(RUNS_DIR, run_id)
    if meta is None:
        print(json.dumps({"error": "run not found"}))
        sys.exit(1)
    from dataclasses import asdict
    print(json.dumps(asdict(meta), indent=2))


if __name__ == "__main__":
    cli()
