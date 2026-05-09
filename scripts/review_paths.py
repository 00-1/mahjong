#!/usr/bin/env python3
"""Review the path failure log + surface patterns.

Use this after a multi-run session to identify which scripted paths
keep failing and why. Output guides what to patch in the scripts.

Usage:
    python scripts/review_paths.py
    python scripts/review_paths.py --since 2026-05-09
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "docs" / "path_library" / "failures.jsonl"


def load_failures() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    out = []
    for line in LOG_PATH.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since", default=None,
                   help="ISO date to filter from (YYYY-MM-DD)")
    p.add_argument("--top", type=int, default=20)
    args = p.parse_args()

    failures = load_failures()
    if args.since:
        threshold = args.since
        failures = [f for f in failures if f.get("ts", "") >= threshold]

    if not failures:
        print(json.dumps({"event": "no_failures", "log": str(LOG_PATH)}))
        return

    # Per-path failure counts
    by_path = Counter(f["path"] for f in failures)
    by_reason = Counter(f.get("failure_reason", "?") for f in failures)
    by_path_reason = Counter((f["path"], f.get("failure_reason", "?")) for f in failures)

    print(f"=== Path failure summary ({len(failures)} failures) ===\n")
    print(f"By path:")
    for path, n in by_path.most_common(args.top):
        print(f"  {n:3d}  {path}")
    print(f"\nBy reason:")
    for reason, n in by_reason.most_common(args.top):
        print(f"  {n:3d}  {reason}")
    print(f"\nBy (path, reason):")
    for (path, reason), n in by_path_reason.most_common(args.top):
        print(f"  {n:3d}  {path:<30}  {reason}")

    # Print recent failures for context
    print(f"\n=== Most recent {min(5, len(failures))} failures ===")
    for f in sorted(failures, key=lambda x: x.get("ts", ""))[-5:]:
        print(json.dumps(f, indent=2))


if __name__ == "__main__":
    main()
