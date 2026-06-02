"""Single-determinization UCT search for the bounded-buffer triple-match
puzzle.

At each decision point:
1. Sample one consistent assignment of hidden state (d2 tiles at every
   anchor) from anchor_priors, conditioned on inventory + cleared_history.
   Call this a "determinization" — a hypothesised perfect-info game
   that's plausible given what we've observed.
2. Run UCT on the resulting perfect-info MDP. Each iteration:
     - Selection: walk the tree using UCB1 to a leaf
     - Expansion: add a child for an unexplored action at the leaf
     - Rollout: simulate forward (greedy or random) until terminal or
       a depth cutoff; evaluate the leaf with state_value.
     - Backpropagation: update visit counts + values along the path.
3. Pick the action with the highest visit count at the root (more
   robust than highest value — exploits the law of large numbers).

This addresses the depth-3 lookahead's blind spot for unblock sequences
that take 5+ taps to set up. UCT can stretch effective horizons via
its rollouts.

This is "single-determinization UCT" — we sample one determinization
per decision and treat it as truth for that decision's planning. The
strategy-fusion pathology (UCT confidently picks a move whose
goodness depends on the specific determinization) is mitigated by
using priors that are highly concentrated on a few anchors. For
broadly-uniform anchors, the determinization is more random and
strategy fusion can hurt — graduating to ISMCTS would fix that
fully (next step if needed).

References:
- Cowling, Powley, Whitehouse 2012 (ISMCTS): the principled fix
  https://eprints.whiterose.ac.uk/id/eprint/75048/1/CowlingPowleyWhitehouse2012.pdf
- Silver & Veness 2010 (POMCP): full POMDP-MCTS, more general
  https://dspace.mit.edu/bitstream/handle/1721.1/100395/Silver_Monte-carlo.pdf
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field

from src.model.state import BoardState
from src.solver.lookahead import state_value
from src.solver.simulate import (
    candidate_locations,
    simulate_tap,
    tray_filled,
)


# UCB1 exploration constant. sqrt(2) is theoretical, but we lean a bit
# higher (1.5) to encourage exploration in our short-horizon problem
# where rollouts are noisy.
UCB1_C = 1.5


@dataclass
class UCTNode:
    state: BoardState
    parent: "UCTNode | None" = None
    action_from_parent: str | None = None  # the tap that got us here
    children: dict[str, "UCTNode"] = field(default_factory=dict)
    visits: int = 0
    total_value: float = 0.0
    untried_actions: list[str] = field(default_factory=list)
    is_terminal: bool = False
    terminal_status: str | None = None
    triplets_along_path: int = 0

    def expanded(self) -> bool:
        return not self.untried_actions

    def best_child_ucb(self, c: float = UCB1_C) -> "UCTNode":
        """Pick child by UCB1: argmax over (Q + c * sqrt(ln(N)/n))."""
        log_n = math.log(self.visits) if self.visits > 0 else 0.0
        best = None
        best_score = float("-inf")
        for child in self.children.values():
            if child.visits == 0:
                # Unvisited child — UCB infinite, take immediately
                return child
            avg = child.total_value / child.visits
            ucb = avg + c * math.sqrt(log_n / child.visits)
            if ucb > best_score:
                best_score = ucb
                best = child
        assert best is not None
        return best

    def avg_value(self) -> float:
        return self.total_value / self.visits if self.visits else 0.0


def determinize(
    state: BoardState,
    anchor_priors: dict,
    inventory: dict | None,
    cleared_history: dict | None = None,
    rng: random.Random | None = None,
    target_depth: int = 2,
) -> dict[tuple, str]:
    """Sample a per-anchor d2 assignment from priors, conditioned on
    inventory remaining + cleared_history.

    Returns: anchor_key (tuple) -> tile_id. Used by simulate_tap as
    occult_predictions.

    Sampling strategy:
    - For each anchor with d_target prior data, sample a tile_id from
      the empirical distribution, weighted by remaining-inventory.
    - For anchors with no prior data, leave unassigned (simulate_tap
      will treat the position as becoming empty — same conservative
      fallback as before).
    """
    rng = rng or random.Random()
    out: dict[tuple, str] = {}
    if not anchor_priors:
        return out
    # Build remaining pool
    remaining: dict[str, int] = {}
    if inventory and inventory.get("tiles"):
        remaining = {tid: int(info.get("count", 3)) for tid, info in inventory["tiles"].items()}
    for c in state.main_board:
        if c.tile_id and c.tile_id in remaining:
            remaining[c.tile_id] = max(0, remaining[c.tile_id] - 1)
    for q in state.queues:
        if q.tile_id and q.tile_id in remaining:
            remaining[q.tile_id] = max(0, remaining[q.tile_id] - 1)
    for t in state.tray:
        if t.tile_id and t.tile_id in remaining:
            remaining[t.tile_id] = max(0, remaining[t.tile_id] - 1)
    for tid, n in (cleared_history or {}).items():
        if tid in remaining:
            remaining[tid] = max(0, remaining[tid] - n)

    for anchor_key, anchor_data in anchor_priors.get("anchors", {}).items():
        try:
            r, c = [int(x) for x in anchor_key.strip("()").split(",")]
        except (ValueError, AttributeError):
            continue
        depth_data = anchor_data.get(f"d{target_depth}", {})
        total = depth_data.get("total", 0)
        if total < 3:
            continue
        counts = depth_data.get("tiles", {})
        if not counts:
            continue
        # Weight each candidate by prior * remaining
        weighted: list[tuple[str, float]] = []
        for tid, n in counts.items():
            weight = (n / total)
            if remaining:
                if remaining.get(tid, 0) <= 0:
                    continue
                weight *= remaining[tid]
            weighted.append((tid, weight))
        if not weighted:
            continue
        total_w = sum(w for _, w in weighted)
        if total_w <= 0:
            continue
        # Sample
        roll = rng.random() * total_w
        cumulative = 0.0
        chosen = weighted[0][0]
        for tid, w in weighted:
            cumulative += w
            if cumulative >= roll:
                chosen = tid
                break
        out[("main_board", r, c)] = chosen
    return out


def _make_node(
    state: BoardState,
    parent: UCTNode | None = None,
    action_from_parent: str | None = None,
    triplets_along_path: int = 0,
    is_terminal: bool = False,
    terminal_status: str | None = None,
) -> UCTNode:
    untried: list[str] = []
    if not is_terminal:
        untried = list(candidate_locations(state))
    return UCTNode(
        state=state, parent=parent,
        action_from_parent=action_from_parent,
        untried_actions=untried,
        is_terminal=is_terminal,
        terminal_status=terminal_status,
        triplets_along_path=triplets_along_path,
    )


def _rollout_value(
    state: BoardState,
    determinization: dict,
    inventory: dict | None,
    cleared_history: Counter,
    max_depth: int = 8,
    rng: random.Random | None = None,
) -> float:
    """Bounded-depth random rollout. Greedy on triplet-clearing taps when
    available, else random. Returns state_value at leaf or terminal value.

    Greedy-prefer-triplets is a strong domain-specific bias that makes
    rollouts much more informative than purely random play. Triplet
    completions are always strictly good; never simulating them would
    drastically underestimate values."""
    rng = rng or random.Random()
    cur = state
    cur_cleared = cleared_history.copy()
    triplets = 0
    for _ in range(max_depth):
        if not cur.main_board and not cur.queues:
            if tray_filled(cur) == 0:
                return 1000.0 + triplets * 30.0
            return 0.0
        if tray_filled(cur) >= 7:
            return -1000.0
        candidates = candidate_locations(cur)
        if not candidates:
            return state_value(cur, inventory, cur_cleared)
        # Triplet-completing taps: tile_id where tray_count == 2 AND that
        # tile_id is at the candidate's location (would auto-clear).
        from collections import Counter as _C
        tray_count = _C(t.tile_id for t in cur.tray if t.tile_id)
        triplet_candidates = []
        for loc in candidates:
            sim = simulate_tap(cur, loc, occult_predictions=determinization)
            if sim.triplet_cleared:
                triplet_candidates.append((loc, sim))
        if triplet_candidates:
            loc, sim = triplet_candidates[0]
            if sim.triplet_cleared:
                triplets += 1
                cur_cleared[sim.triplet_cleared] = cur_cleared.get(sim.triplet_cleared, 0) + 3
        else:
            # Pick the candidate with highest greedy state_value
            best = None
            best_v = float("-inf")
            for loc in candidates:
                sim = simulate_tap(cur, loc, occult_predictions=determinization)
                if sim.is_terminal:
                    if sim.terminal_status == "won":
                        return 1000.0 + triplets * 30.0
                    if sim.terminal_status == "lost":
                        v = -1000.0
                    else:
                        v = state_value(sim.new_state, inventory, cur_cleared)
                else:
                    v = state_value(sim.new_state, inventory, cur_cleared)
                if v > best_v:
                    best_v = v
                    best = (loc, sim)
            if best is None:
                return state_value(cur, inventory, cur_cleared)
            loc, sim = best
        if sim.is_terminal:
            if sim.terminal_status == "won":
                return 1000.0 + triplets * 30.0
            if sim.terminal_status == "lost":
                return -1000.0
            return state_value(sim.new_state, inventory, cur_cleared)
        cur = sim.new_state
    return state_value(cur, inventory, cur_cleared) + triplets * 30.0


def uct_search(
    state: BoardState,
    *,
    n_iterations: int = 200,
    determinization: dict | None = None,
    inventory: dict | None = None,
    cleared_history: Counter | None = None,
    rollout_max_depth: int = 8,
    seed: int | None = None,
) -> dict:
    """Run UCT for `n_iterations` from `state`. Returns dict with
    best_location, expected_value, visit counts per root action."""
    rng = random.Random(seed)
    cleared_history = cleared_history or Counter()
    determinization = determinization or {}

    root = _make_node(state)
    if not root.untried_actions:
        return {
            "best_location": "",
            "expected_value": state_value(state, inventory, cleared_history),
            "visits": {},
            "method": "uct",
            "iterations": 0,
        }

    for _ in range(n_iterations):
        node = root
        path_cleared = cleared_history.copy()
        # Selection: walk down the tree
        while node.expanded() and node.children and not node.is_terminal:
            node = node.best_child_ucb()
            # Update path_cleared if this transition cleared a triplet.
            # We don't store cleared_history per node (memory) — recompute
            # from the parent->child transition by inspecting the action.
            # Simpler: track triplets_along_path on each node.
        # Expansion: add a new child for an untried action
        if not node.is_terminal and node.untried_actions:
            action = node.untried_actions.pop(rng.randrange(len(node.untried_actions)))
            sim = simulate_tap(node.state, action, occult_predictions=determinization)
            new_triplets = node.triplets_along_path + (1 if sim.triplet_cleared else 0)
            child = _make_node(
                sim.new_state, parent=node, action_from_parent=action,
                triplets_along_path=new_triplets,
                is_terminal=sim.is_terminal, terminal_status=sim.terminal_status,
            )
            node.children[action] = child
            node = child
        # Rollout: estimate value from this node (or terminal-eval if leaf)
        if node.is_terminal:
            if node.terminal_status == "won":
                value = 1000.0 + node.triplets_along_path * 30.0
            elif node.terminal_status == "lost":
                value = -1000.0
            else:
                value = state_value(node.state, inventory, path_cleared)
        else:
            # Construct cleared_history at this node by walking up
            from collections import Counter as _C
            walk_cleared = path_cleared.copy()
            # Track path's accumulated clears via the simulate's per-action result.
            # Simplest: recompute by replaying from root. Cheap since depth is small.
            replay_cleared = cleared_history.copy()
            chain: list[UCTNode] = []
            cursor = node
            while cursor.parent is not None:
                chain.append(cursor)
                cursor = cursor.parent
            chain.reverse()
            replay_state = root.state
            for n in chain:
                sim = simulate_tap(replay_state, n.action_from_parent, occult_predictions=determinization)
                if sim.triplet_cleared:
                    replay_cleared[sim.triplet_cleared] = replay_cleared.get(sim.triplet_cleared, 0) + 3
                replay_state = sim.new_state
            value = _rollout_value(
                node.state, determinization, inventory, replay_cleared,
                max_depth=rollout_max_depth, rng=rng,
            )
        # Backpropagation
        cursor = node
        while cursor is not None:
            cursor.visits += 1
            cursor.total_value += value
            cursor = cursor.parent

    # Pick action with highest visit count at root (more robust than value)
    if not root.children:
        return {
            "best_location": root.untried_actions[0] if root.untried_actions else "",
            "expected_value": 0.0,
            "visits": {},
            "method": "uct",
            "iterations": n_iterations,
        }
    best_action = max(root.children, key=lambda a: root.children[a].visits)
    visits = {a: c.visits for a, c in root.children.items()}
    avg_values = {a: c.avg_value() for a, c in root.children.items()}
    return {
        "best_location": best_action,
        "expected_value": avg_values[best_action],
        "visits": visits,
        "avg_values": avg_values,
        "method": "uct",
        "iterations": n_iterations,
    }


def uct_recommend(
    state: BoardState,
    *,
    anchor_priors: dict | None = None,
    inventory: dict | None = None,
    cleared_history: Counter | None = None,
    n_iterations: int = 200,
    rollout_max_depth: int = 8,
    seed: int | None = None,
) -> dict:
    """Top-level entry analogous to lookahead_recommend. Samples one
    determinization from priors and runs UCT on it."""
    determinization = {}
    if anchor_priors:
        rng = random.Random(seed)
        determinization = determinize(state, anchor_priors, inventory,
                                      cleared_history, rng=rng)
    result = uct_search(
        state, n_iterations=n_iterations,
        determinization=determinization,
        inventory=inventory, cleared_history=cleared_history,
        rollout_max_depth=rollout_max_depth, seed=seed,
    )
    result["determinization_size"] = len(determinization)
    return result
