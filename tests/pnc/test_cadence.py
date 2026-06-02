"""Validate src/pnc/cadence.next_recheck against the heuristic doc."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.pnc.cadence import (  # noqa: E402
    CLUSTER_BUFFER,
    DEFAULT_DELAY,
    MAX_DELAY,
    MIN_DELAY,
    SINGLE_BUFFER,
    TroopState,
    next_recheck,
)


def test_free_slots_recheck_immediately():
    """If we already have free slots, fire ASAP."""
    troops = [TroopState(seconds_remaining=3600, kind="gather")]
    plan = next_recheck(troops, n_total=5)
    assert plan.delay_seconds == MIN_DELAY
    assert plan.reason == "free_slots_already_available"


def test_cluster_of_short_gather_timers_uses_latest_plus_buffer():
    """Three short Gather timers landing close together: schedule
    for the latest + 2 min so one cycle catches all three."""
    troops = [
        TroopState(seconds_remaining=300, kind="gather"),    # 5 min
        TroopState(seconds_remaining=480, kind="gather"),    # 8 min
        TroopState(seconds_remaining=720, kind="gather"),    # 12 min — latest of cluster
        TroopState(seconds_remaining=3600, kind="gather"),
        TroopState(seconds_remaining=3600, kind="gather"),
    ]
    plan = next_recheck(troops, n_total=5)
    assert plan.reason == "cluster_of_short_gather_timers"
    assert plan.delay_seconds == 720 + CLUSTER_BUFFER


def test_single_short_timer_uses_buffer_capped_at_60min():
    """One short timer of any kind: timer + 3 min, capped at 60 min."""
    troops = [
        TroopState(seconds_remaining=600, kind="gather"),    # 10 min
        TroopState(seconds_remaining=3500, kind="gather"),
        TroopState(seconds_remaining=4000, kind="gather"),
        TroopState(seconds_remaining=5000, kind="transit"),
        TroopState(seconds_remaining=6000, kind="gather"),
    ]
    plan = next_recheck(troops, n_total=5)
    assert plan.reason == "single_short_timer"
    assert plan.delay_seconds == 600 + SINGLE_BUFFER


def test_long_timer_falls_back_to_default():
    """5/5 with all long timers → schedule the default 60 min."""
    troops = [TroopState(seconds_remaining=3600 * 4, kind="gather")] * 5
    plan = next_recheck(troops, n_total=5)
    assert plan.delay_seconds == DEFAULT_DELAY
    assert plan.reason == "no_short_timers"


def test_all_transit_with_one_short_uses_single_buffer():
    """Edge case: all marches in transit (Speedup), one near-arrival."""
    troops = [
        TroopState(seconds_remaining=120, kind="transit"),   # almost there
        TroopState(seconds_remaining=2000, kind="transit"),
        TroopState(seconds_remaining=2500, kind="transit"),
        TroopState(seconds_remaining=3000, kind="transit"),
        TroopState(seconds_remaining=3500, kind="transit"),
    ]
    plan = next_recheck(troops, n_total=5)
    # Single short → 120 + 180 = 300, but MIN_DELAY clamps to 300.
    assert plan.delay_seconds == max(MIN_DELAY, 120 + SINGLE_BUFFER)


def test_delay_never_exceeds_max():
    """Even if a short timer is technically long, cap at MAX_DELAY."""
    troops = [
        TroopState(seconds_remaining=890, kind="gather"),
        TroopState(seconds_remaining=890, kind="gather"),
        TroopState(seconds_remaining=890, kind="gather"),
        TroopState(seconds_remaining=890, kind="gather"),
        TroopState(seconds_remaining=890, kind="gather"),
    ]
    plan = next_recheck(troops, n_total=5)
    assert plan.delay_seconds <= MAX_DELAY


def _run_all():
    tests = [
        test_free_slots_recheck_immediately,
        test_cluster_of_short_gather_timers_uses_latest_plus_buffer,
        test_single_short_timer_uses_buffer_capped_at_60min,
        test_long_timer_falls_back_to_default,
        test_all_transit_with_one_short_uses_single_buffer,
        test_delay_never_exceeds_max,
    ]
    failures = []
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failures.append(t.__name__)
        except Exception as e:
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
            failures.append(t.__name__)
    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all())
