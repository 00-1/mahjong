"""Cron-cadence scheduler for PNC gather/sapphire scripts.

Pure logic — takes a snapshot of game state and returns when the next
recheck should fire. Codifies the heuristic that worked overnight on
2026-05-09 → 2026-05-10 (see GATHER_RUN_STANDARD.md).

All times are in seconds. The caller is expected to feed the result
into CronCreate or `at` to schedule the next run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Heuristic constants. Numbers picked from observed cycle behaviour;
# don't change without re-validating across a full session.
MIN_DELAY = 5 * 60          # never recheck sooner than 5 minutes
MAX_DELAY = 60 * 60         # cap at 1 hour
DEFAULT_DELAY = 60 * 60     # 5/5 with no short timers
CLUSTER_BUFFER = 2 * 60     # for clusters of short timers, wait 2 min after the latest
SINGLE_BUFFER = 3 * 60      # for one short timer, wait 3 min after it returns
SHORT_TIMER_THRESHOLD = 15 * 60   # ≤15 min counts as "short"
CLUSTER_MIN_COUNT = 2       # need 2+ short timers to be considered a cluster


@dataclass
class TroopState:
    """One row of the world-map Troop Info panel."""
    seconds_remaining: int          # 0 means returning now / about to land
    kind: str = "gather"            # "gather" | "transit" | "speedup"


@dataclass
class CadencePlan:
    """Result of scheduling logic. `delay_seconds` is what to give cron."""
    delay_seconds: int
    reason: str
    inputs: dict = field(default_factory=dict)


def next_recheck(troops: list[TroopState], n_total: int = 5) -> CadencePlan:
    """Pick the next recheck delay given visible troop timers.

    Heuristic mirrors GATHER_RUN_STANDARD.md:
      - If ≥2 short ("Gathering"-kind) timers ≤15 min: schedule for
        max(short timers) + 2 min — they cluster.
      - Else if exactly one short timer (any kind): schedule for
        timer + 3 min, capped at 60 min.
      - Else (5/5 with all long timers, or all transit): 60 min.
    """
    free = n_total - len(troops)
    if free > 0:
        # Free slots already exist; recheck soon to use them.
        return CadencePlan(
            delay_seconds=MIN_DELAY,
            reason="free_slots_already_available",
            inputs={"free": free, "n_total": n_total},
        )

    short_gather = [t for t in troops
                    if t.seconds_remaining <= SHORT_TIMER_THRESHOLD
                    and t.kind == "gather"]
    short_any = [t for t in troops
                 if t.seconds_remaining <= SHORT_TIMER_THRESHOLD]

    if len(short_gather) >= CLUSTER_MIN_COUNT:
        latest = max(t.seconds_remaining for t in short_gather)
        delay = max(MIN_DELAY, min(MAX_DELAY, latest + CLUSTER_BUFFER))
        return CadencePlan(
            delay_seconds=delay,
            reason="cluster_of_short_gather_timers",
            inputs={"n_short_gather": len(short_gather),
                    "latest_short_seconds": latest},
        )

    if len(short_any) == 1:
        t = short_any[0]
        delay = max(MIN_DELAY, min(MAX_DELAY, t.seconds_remaining + SINGLE_BUFFER))
        return CadencePlan(
            delay_seconds=delay,
            reason="single_short_timer",
            inputs={"timer_seconds": t.seconds_remaining, "kind": t.kind},
        )

    return CadencePlan(
        delay_seconds=DEFAULT_DELAY,
        reason="no_short_timers",
        inputs={"n_troops": len(troops)},
    )


__all__ = ["TroopState", "CadencePlan", "next_recheck"]
