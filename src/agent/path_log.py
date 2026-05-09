"""Append-only failure log for scripted paths.

When a script returns needs_llm or fails for a reason we'd want to fix,
call log_path_failure to record it. Periodic review surfaces patterns.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "docs" / "path_library" / "failures.jsonl"


def log_path_failure(
    path: str,
    script: str,
    failure_reason: str,
    *,
    run_id: str | None = None,
    step: str | None = None,
    expected: str | None = None,
    observed: str | None = None,
    extra: dict | None = None,
) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "path": path,
        "script": script,
        "failure_reason": failure_reason,
    }
    if run_id is not None: rec["run_id"] = run_id
    if step is not None: rec["step"] = step
    if expected is not None: rec["expected"] = expected
    if observed is not None: rec["observed"] = observed
    if extra: rec.update(extra)
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(rec) + "\n")
