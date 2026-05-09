"""Decision module: given a screenshot, recommend the next tap.

Returns a dict (JSON-serializable) with:
- tap: { "x": int, "y": int, "location": str }      target tap in screen pixel coords
- tile_id, label                                     identity of the tile
- confidence: 0..1                                   how confident the recommendation is
- score                                              raw move score
- reason                                             human-readable explanation
- alternatives: list of 2-3 backup taps
- state: brief summary of board (for logging)
- should_stop: bool                                  true if the agent should bail out
                                                     (game over, no good moves, etc.)
- reason_code: machine-readable (TRIPLET, EXPLORE, NO_MOVES, GAME_OVER, ...)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.model.diff import load_state
from src.solver.lookahead import lookahead_recommend
from src.solver.reactive import plan_triplets, suggest_moves


def decide(
    state_path: Path,
    image_size: tuple[int, int],
    label_fn=None,
    *,
    use_lookahead: bool = False,
    lookahead_depth: int = 3,
    occult_predictions: dict | None = None,
    inventory: dict | None = None,
    cleared_history: dict | None = None,
    surrender_threshold: float = -500.0,
    allow_surrender: bool = True,
) -> dict:
    if label_fn is None:
        label_fn = lambda t: t  # noqa: E731
    state = load_state(state_path)

    tray_filled = sum(1 for t in state.tray if t.tile_id is not None)
    moves = suggest_moves(state, label_fn=label_fn)
    plans = plan_triplets(state)

    # If we extracted essentially nothing, this probably isn't a puzzle screen.
    # Tell the agent so it can navigate / dismiss popups instead of trying to play.
    if len(state.main_board) == 0 and len(state.queues) == 0:
        return {
            "should_stop": True,
            "reason_code": "NOT_A_PUZZLE",
            "reason": (
                "no tile faces detected in main board or queues — "
                "screen is probably not the puzzle gameplay view "
                "(could be a popup, level list, or load screen)"
            ),
            "looks_like_puzzle": False,
            "state": _state_summary(state, label_fn),
        }

    # Game-over heuristic: tray full means no taps allowed by the game,
    # even if a triplet would be completable. Game is lost.
    if tray_filled >= 7:
        from collections import Counter
        tray_tiles = Counter(t.tile_id for t in state.tray if t.tile_id is not None)
        has_tray_triplet = any(c >= 3 for c in tray_tiles.values())
        if has_tray_triplet:
            # If tray contains a triplet directly, the game would auto-clear
            # on the next animation frame — this is rare but possible.
            return {
                "should_stop": False,
                "reason_code": "WAIT_FOR_AUTOCLEAR",
                "reason": "tray contains a triplet — wait for the game to auto-clear, then re-screenshot",
                "state": _state_summary(state, label_fn),
            }
        return {
            "should_stop": True,
            "reason_code": "GAME_OVER",
            "reason": "tray full (7/7) with no triplet — game lost",
            "state": _state_summary(state, label_fn),
        }

    if not moves:
        return {
            "should_stop": True,
            "reason_code": "NO_MOVES",
            "reason": "no tappable tiles detected",
            "state": _state_summary(state, label_fn),
        }

    # If lookahead is enabled AND there are no immediate triplets, use the
    # search-based recommendation (it's only better than greedy in the
    # explore regime; greedy is correct when triplets are immediately
    # available).
    has_immediate_triplet = any(p.taps_needed > 0 and p.taps_needed <= 3 for p in plans) and plans
    lookahead_recommendation = None
    if use_lookahead and not has_immediate_triplet:
        try:
            from collections import Counter as _Counter
            ch = _Counter(cleared_history) if cleared_history else None
            lookahead_recommendation = lookahead_recommend(
                state,
                depth=lookahead_depth,
                occult_predictions=occult_predictions,
                inventory=inventory,
                cleared_history=ch,
            )
        except Exception:
            lookahead_recommendation = None

    lookahead_used = False
    lookahead_expected_value = None
    if lookahead_recommendation is not None and lookahead_recommendation["best_location"]:
        # Find the matching move in the existing list (for tap coords)
        target_loc = lookahead_recommendation["best_location"]
        matching = [m for m in moves if m.location == target_loc]
        if matching:
            best = matching[0]
            lookahead_used = True
            lookahead_expected_value = lookahead_recommendation.get("expected_value")
        else:
            best = moves[0]
    else:
        best = moves[0]

    # Surrender guard: if lookahead unambiguously says we're losing within
    # depth (every continuation falls below surrender_threshold), stop
    # tapping. Continuing would just burn tray slots and drag the run to
    # the inevitable game-over modal.
    #
    # The "is it safe to surrender NOW" decision is delegated to the
    # caller via `allow_surrender`. autoplay.py uses that to encode:
    #   - "haven't played enough yet to trust the lookahead" (step floor)
    #   - "vision is suspect (sparse main_board) AND we're early in the
    #      run, so the lookahead might be reasoning about a broken
    #      extraction"
    # These checks live in autoplay because it has the full step/state
    # context. decide() just respects the bool.
    if (allow_surrender
            and lookahead_used and lookahead_expected_value is not None
            and lookahead_expected_value <= surrender_threshold):
        return {
            "should_stop": True,
            "reason_code": "UNRECOVERABLE",
            "reason": (
                f"lookahead expected_value={lookahead_expected_value:.1f} "
                f"<= surrender_threshold={surrender_threshold}; "
                f"every continuation within depth-{lookahead_depth} ends in loss"
            ),
            "lookahead_used": True,
            "lookahead_expected_value": round(lookahead_expected_value, 3),
            "score": round(best.score, 3),
            "state": _state_summary(state, label_fn),
        }

    bbox = _location_to_bbox(state, best.location)

    # If the top move is part of a triplet that's fully tappable now (all
    # locations in plans[0].tap_locations are visible top tiles), include
    # the full sequence so the agent can blast all taps without re-snapping.
    triplet_sequence = None
    if plans and best.score >= 8:
        top_plan = plans[0]
        if top_plan.tile_id == best.tile_id:
            seq = []
            for loc in top_plan.tap_locations:
                lb = _location_to_bbox(state, loc)
                if lb is None:
                    seq = None
                    break
                seq.append({
                    "x": lb[0] + lb[2] // 2,
                    "y": lb[1] + lb[3] // 2,
                    "location": loc,
                })
            if seq:
                triplet_sequence = seq

    if bbox is None:
        return {
            "should_stop": True,
            "reason_code": "NO_MAPPING",
            "reason": f"could not map location {best.location} to screen coords",
            "state": _state_summary(state, label_fn),
        }
    cx, cy = bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2

    # Confidence: we trust triplet-completion moves; risky scores get low confidence
    if best.score >= 8:
        confidence = 0.95
        reason_code = "TRIPLET"
    elif best.score >= 0:
        confidence = 0.65
        reason_code = "PROBABLE"
    else:
        # All moves are negative-score (just exploring, no triplet available).
        # Pick the LEAST risky and flag low confidence.
        confidence = max(0.1, 0.5 + best.score / 20.0)
        reason_code = "EXPLORE"

    alternatives = []
    for m in moves[1:4]:
        bbox_alt = _location_to_bbox(state, m.location)
        if bbox_alt is None:
            continue
        ax, ay = bbox_alt[0] + bbox_alt[2] // 2, bbox_alt[1] + bbox_alt[3] // 2
        alternatives.append({
            "x": ax, "y": ay, "location": m.location,
            "tile_id": m.tile_id, "label": label_fn(m.tile_id),
            "score": m.score, "reason": m.reason,
        })

    return {
        "should_stop": False,
        "reason_code": reason_code,
        "tap": {"x": cx, "y": cy, "location": best.location},
        "tile_id": best.tile_id,
        "label": label_fn(best.tile_id),
        "confidence": round(confidence, 3),
        "score": round(best.score, 3),
        "lookahead_used": lookahead_used,
        "lookahead_expected_value": (
            round(lookahead_expected_value, 3) if lookahead_expected_value is not None else None
        ),
        "reason": best.reason,
        "alternatives": alternatives,
        "triplet_sequence": triplet_sequence,
        "state": _state_summary(state, label_fn),
        "image_size": {"w": image_size[0], "h": image_size[1]},
    }


def _location_to_bbox(state, location: str):
    """Map a logical location like '(r,c)' or 'queue:left_upper' back to bbox."""
    if location.startswith("("):
        r, c = [int(x) for x in location.strip("()").split(",")]
        for cell in state.main_board:
            if (cell.row, cell.col) == (r, c):
                return cell.bbox
    elif location.startswith("queue:"):
        qid = location.split(":", 1)[1]
        for q in state.queues:
            if q.queue_id == qid:
                return q.bbox
    elif location.startswith("tray:"):
        slot = int(location.split(":", 1)[1])
        for t in state.tray:
            if t.slot == slot:
                return t.bbox
    return None


def _state_summary(state, label_fn) -> dict:
    return {
        "level": state.level,
        "image_size": list(state.image_size) if state.image_size else None,
        "tray_filled": sum(1 for t in state.tray if t.tile_id is not None),
        "tray": [label_fn(t.tile_id) for t in state.tray if t.tile_id is not None],
        "main_board_count": len(state.main_board),
        "queue_count": len(state.queues),
        "tile_counts": _count_visible(state, label_fn),
        "looks_like_puzzle": len(state.main_board) > 0 or len(state.queues) > 0,
    }


def _count_visible(state, label_fn) -> dict:
    from collections import Counter
    c: Counter = Counter()
    for cell in state.main_board:
        if cell.tile_id:
            c[label_fn(cell.tile_id)] += 1
    for q in state.queues:
        if q.tile_id:
            c[label_fn(q.tile_id)] += 1
    for t in state.tray:
        if t.tile_id:
            c[label_fn(t.tile_id)] += 1
    return dict(c)
