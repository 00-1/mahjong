"""Block-aware unblocking suggestions.

When a tile type has bright + dim >= 3 but bright + tray < 3, we need to
make some dim tile tappable to complete the triplet. This module finds
adjacent brights that *might* be blocking each dim tile, and suggests
unblocking sequences.

This is heuristic — we don't know the exact mahjong-style blocking rule
in this game. We use a generous "adjacent" definition: a bright tile B
blocks a dim tile D if B's bbox shares an edge with D's bbox OR B is
directly to the left/right/above of D within ~tile_w distance.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Blocker:
    bright_location: str  # e.g., "(r,c)" for main_board
    bright_tile_id: str
    dim_position: tuple[int, int]  # (cx, cy) of the dim tile
    dim_tile_id: str
    relation: str  # "left", "right", "above", "below"


def _bbox_distance(bx: int, by: int, bw: int, bh: int,
                   dx: int, dy: int, dw: int, dh: int) -> tuple[int, int]:
    """Minimum horizontal and vertical gap between two bboxes (0 if overlapping)."""
    h_gap = max(0, max(bx, dx) - min(bx + bw, dx + dw))
    v_gap = max(0, max(by, dy) - min(by + bh, dy + dh))
    return h_gap, v_gap


def find_blockers(
    bright_dets: list,  # list of detection objects with bbox
    bright_locations: list[str],  # parallel list of locations like "(r,c)" for indexing into state
    bright_ids: list[str | None],
    dim_dets: list,
    dim_ids: list[str | None],
    tile_w: int,
    tile_h: int,
) -> dict[tuple[int, int], list[Blocker]]:
    """Return: dim_position -> list of brights that potentially block it.

    A bright is "potentially blocking" a dim tile if it's adjacent in any
    direction within ~tile_size proximity.
    """
    by_dim: dict[tuple[int, int], list[Blocker]] = {}
    h_tol = int(tile_w * 0.5)
    v_tol = int(tile_h * 0.5)

    for di, dim in enumerate(dim_dets):
        dim_tid = dim_ids[di] if di < len(dim_ids) else None
        if dim_tid is None:
            continue
        dim_pos = (dim.cx, dim.cy)
        blockers: list[Blocker] = []
        for bi, bright in enumerate(bright_dets):
            bright_tid = bright_ids[bi] if bi < len(bright_ids) else None
            if bright_tid is None:
                continue
            h_gap, v_gap = _bbox_distance(
                bright.x, bright.y, bright.w, bright.h,
                dim.x, dim.y, dim.w, dim.h,
            )
            if h_gap <= h_tol and v_gap <= v_tol:
                # Determine relation
                if abs(bright.cx - dim.cx) < tile_w * 0.3:
                    relation = "above" if bright.cy < dim.cy else "below"
                elif bright.cx < dim.cx:
                    relation = "left"
                else:
                    relation = "right"
                blockers.append(Blocker(
                    bright_location=bright_locations[bi],
                    bright_tile_id=bright_tid,
                    dim_position=dim_pos,
                    dim_tile_id=dim_tid,
                    relation=relation,
                ))
        if blockers:
            by_dim[dim_pos] = blockers
    return by_dim


@dataclass
class UnblockingPlan:
    target_tile_id: str
    sequence: list[str]  # taps in order: blockers first, then dim
    risk: str  # human-readable note about cost / risk


def suggest_unblocking(
    target_tile_ids: list[str],
    dim_dets: list,
    dim_ids: list[str | None],
    blockers_by_dim: dict[tuple[int, int], list],
    label_fn=None,
) -> list[UnblockingPlan]:
    """For each target tile we want to triplet (already 2+ visible), find
    the cheapest unblocking sequence."""
    if label_fn is None:
        label_fn = lambda t: t  # noqa: E731
    plans: list[UnblockingPlan] = []
    for target in set(target_tile_ids):
        # Find dim tiles of this target
        dim_targets = [
            (i, dim) for i, dim in enumerate(dim_dets)
            if i < len(dim_ids) and dim_ids[i] == target
        ]
        if not dim_targets:
            continue
        # For each dim, get its blocker list — limit to MIN blockers needed
        # (tapping just one blocker may be enough; we don't know exact rules
        # so we suggest tapping the L+R neighbors that bracket the dim)
        for i, dim in dim_targets:
            blockers = blockers_by_dim.get((dim.cx, dim.cy), [])
            if not blockers:
                continue
            # Heuristic: pick at most 2 blockers (left + right typical for
            # mahjong-style blocking)
            chosen_blockers = blockers[:2]
            tap_seq = [b.bright_location for b in chosen_blockers] + [f"DIM@({dim.cx},{dim.cy})"]
            risk = (
                f"adds {len(chosen_blockers)} to tray (blocker tiles), "
                f"then makes dim {label_fn(target)} tappable"
            )
            plans.append(UnblockingPlan(
                target_tile_id=target,
                sequence=tap_seq,
                risk=risk,
            ))
    # Dedup by target — keep the cheapest plan per target
    by_target: dict[str, UnblockingPlan] = {}
    for p in plans:
        if p.target_tile_id not in by_target or len(p.sequence) < len(by_target[p.target_tile_id].sequence):
            by_target[p.target_tile_id] = p
    return list(by_target.values())
