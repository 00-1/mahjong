"""Multi-step lookahead solver.

For each candidate move, simulate the resulting state, recursively look
ahead to a bounded depth, evaluate leaf states, pick the move that leads
to the best expected outcome.

This is the strategic upgrade over greedy `suggest_moves`: instead of
always clearing the easiest immediate triplet, the solver considers
whether clearing it now is actually optimal, or whether holding off
keeps more triplets available later.

Search is depth-limited (default depth 3). Without occult predictions,
unknown reveals are treated as "position becomes empty" — conservative
but safe.

With occult predictions, simulation becomes deterministic-ish:
predicted reveals are used. The search becomes much more powerful
once predictions are reliable.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from src.model.state import BoardState
from src.solver.simulate import (
    candidate_locations,
    simulate_tap,
    tray_count,
    tray_filled,
)


@dataclass
class SearchResult:
    location: str
    expected_value: float
    plan: list[str]  # sequence of taps (for the principal variation)
    triplets_cleared: int


def state_value(
    state: BoardState,
    inventory: dict | None = None,
    cleared_history: Counter | None = None,
) -> float:
    """Heuristic value of a state. Higher is better.

    inventory and cleared_history together let dead-tile detection
    work correctly for mixed-multiplicity levels (e.g. level 8 mixes
    3-instance and 6-instance tile types). Without them we fall back
    to "visible+tray < 3 = dead", which is wrong for 6-instance tiles.

    Components and rough magnitudes:
    - Win/loss terminals: ±1000
    - Triplet realisable now (>=3 of a type combined visible+tray): +5/type
    - Near-triplet seeds (2-in-tray): +5/type
    - 1-in-tray seeds: +1/type
    - Orphan visible (1 visible, 0 in tray, can never reach 3): -3/type
    - DEAD TRAY TILE: tile in tray with NO chance of forming a triplet.
      Heavy penalty per dead tile (-15) — permanent occupant of slot.
    - Tray-fullness: quadratic penalty toward 7
    - Tile-remaining: -2/each (encourages clearing)
    - Diversity-of-tray bonus: +0.5 per distinct type (capped at 4).
    """
    if not state.main_board and not state.queues:
        if tray_filled(state) == 0:
            return 1000  # WIN
        return 0

    tf = tray_filled(state)
    if tf >= 7:
        return -1000

    visible_count: Counter = Counter()
    for c in state.main_board:
        if c.tile_id:
            visible_count[c.tile_id] += 1
    for q in state.queues:
        if q.tile_id:
            visible_count[q.tile_id] += 1

    tray_per_tile: Counter = Counter()
    for t in state.tray:
        if t.tile_id:
            tray_per_tile[t.tile_id] += 1

    inventory_tiles = (inventory or {}).get("tiles", {})

    def remaining_for(tid: str) -> int:
        """Best estimate of total remaining instances of tid in play
        (visible + tray + still-hidden). Uses inventory + cleared_history
        when available; otherwise falls back to visible+tray."""
        v = visible_count.get(tid, 0)
        t = tray_per_tile.get(tid, 0)
        if inventory_tiles and tid in inventory_tiles:
            total = inventory_tiles[tid].get("count", 3)
            cleared = (cleared_history or {}).get(tid, 0)
            return max(0, total - cleared)  # everything not yet cleared
        return v + t  # conservative: only counts what we observe

    score = 0.0
    all_tiles = set(visible_count) | set(tray_per_tile)
    dead_tray_tiles = 0
    for tid in all_tiles:
        v = visible_count.get(tid, 0)
        t = tray_per_tile.get(tid, 0)
        in_play = v + t
        remaining_total = remaining_for(tid)
        if remaining_total >= 3:
            score += 5.0  # triplet realisable somewhere in remaining inventory
        if t == 2:
            score += 5.0  # near-triplet seed
        elif t == 1:
            score += 1.0  # versatile seed
        if v == 1 and t == 0 and remaining_total < 3:
            score -= 3.0  # orphan visible — can't make triplet
        # Dead tray tile: tray entry whose tile_id has fewer than 3
        # remaining instances (post any clears already happened in path
        # — those are reflected in visible/tray having dropped). With
        # inventory we can correctly distinguish "1 in tray, 2 hidden"
        # (still completable) from "1 in tray, 0 anywhere else" (dead).
        if t >= 1 and remaining_total < 3:
            dead_tray_tiles += t
    score -= dead_tray_tiles * 15.0

    # Diversity bonus: tray with several distinct types is more
    # absorbent (more taps that don't push us toward overflow).
    distinct_in_tray = sum(1 for n in tray_per_tile.values() if n > 0)
    score += min(distinct_in_tray, 4) * 0.5

    # Tray penalty (quadratic — really painful as we approach 7)
    score -= (tf / 7.0) ** 2 * 30.0

    # Remaining tiles: each is a tile we still need to clear. Heavy
    # penalty so clearing 3 tiles via triplet is +6 from this term alone,
    # offsetting the +5 "triplet realisable" we lose when consumed.
    remaining = sum(1 for c in state.main_board if c.tile_id) + \
                sum(1 for q in state.queues if q.tile_id)
    score -= remaining * 2.0

    return score


def search_best(
    state: BoardState,
    depth: int = 3,
    occult_predictions: dict | None = None,
    triplets_so_far: int = 0,
    plan_so_far: list[str] | None = None,
    inventory: dict | None = None,
    cleared_history: Counter | None = None,
) -> SearchResult:
    """Depth-limited search for the best move from this state.

    inventory + cleared_history are propagated to state_value at leaves
    so dead-tile detection uses correct level-wide multiplicity counts.
    cleared_history is updated as we descend through triplet-clearing
    moves so the leaf evaluation reflects in-search clears.

    Returns SearchResult with the chosen first move and its expected value.
    """
    if plan_so_far is None:
        plan_so_far = []
    if cleared_history is None:
        cleared_history = Counter()

    if depth <= 0:
        return SearchResult(
            location=plan_so_far[0] if plan_so_far else "",
            expected_value=state_value(state, inventory, cleared_history),
            plan=plan_so_far,
            triplets_cleared=triplets_so_far,
        )

    candidates = candidate_locations(state)
    if not candidates:
        return SearchResult(
            location="", expected_value=state_value(state, inventory, cleared_history),
            plan=plan_so_far, triplets_cleared=triplets_so_far,
        )

    best_value = float("-inf")
    best_loc = candidates[0]
    best_plan = plan_so_far + [candidates[0]]
    best_triplets = triplets_so_far

    for loc in candidates:
        sim = simulate_tap(state, loc, occult_predictions=occult_predictions)
        new_triplets = triplets_so_far + (1 if sim.triplet_cleared else 0)
        # Propagate cleared_history (3 of the cleared tile_id added)
        sub_cleared = cleared_history
        if sim.triplet_cleared:
            sub_cleared = cleared_history.copy()
            sub_cleared[sim.triplet_cleared] = sub_cleared.get(sim.triplet_cleared, 0) + 3

        if sim.is_terminal:
            if sim.terminal_status == "won":
                value = 1000.0 + new_triplets * 10  # winning is great
            elif sim.terminal_status == "lost":
                value = -1000.0
            else:
                value = state_value(sim.new_state, inventory, sub_cleared)
            if value > best_value:
                best_value = value
                best_loc = loc
                best_plan = plan_so_far + [loc]
                best_triplets = new_triplets
            continue

        sub = search_best(
            sim.new_state, depth - 1, occult_predictions,
            triplets_so_far=new_triplets,
            plan_so_far=plan_so_far + [loc],
            inventory=inventory,
            cleared_history=sub_cleared,
        )
        # Discount slightly per step (prefer faster solutions)
        sub_value = sub.expected_value - 0.1
        # Triplet clears get strong reward — independent of state-value
        # accounting. Captures the fact that we've made tangible progress
        # (3 tiles permanently removed).
        if sim.triplet_cleared:
            sub_value += 30.0

        if sub_value > best_value:
            best_value = sub_value
            best_loc = loc
            best_plan = sub.plan
            best_triplets = sub.triplets_cleared

    return SearchResult(
        location=best_loc, expected_value=best_value,
        plan=best_plan, triplets_cleared=best_triplets,
    )


def lookahead_recommend(
    state: BoardState,
    depth: int = 3,
    occult_predictions: dict | None = None,
    inventory: dict | None = None,
    cleared_history: Counter | None = None,
) -> dict:
    """Top-level entry: returns a dict that mirrors the suggest_moves output
    format but uses lookahead search instead of greedy ranking."""
    result = search_best(
        state, depth=depth, occult_predictions=occult_predictions,
        inventory=inventory, cleared_history=cleared_history,
    )
    return {
        "best_location": result.location,
        "expected_value": result.expected_value,
        "plan": result.plan,
        "triplets_in_plan": result.triplets_cleared,
        "depth": depth,
    }
