"""Validate src/pnc/state.py against committed fixtures.

Run with: `python3 -m pytest tests/pnc/test_state.py -v`
Or:       `python3 tests/pnc/test_state.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.pnc.state import (  # noqa: E402
    detect_popup,
    find_mine_tiles,
    read_sapphire_sidepanel,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    p = FIXTURES / name
    assert p.exists(), f"fixture missing: {p}"
    bgr = cv2.imread(str(p))
    assert bgr is not None, f"failed to read: {p}"
    return bgr


# ---------- mine-tile classification ----------


def test_lv8_mine_grid_after_depart_detects_skull_no_horns():
    """The post-depart Lv.8 mine grid fixture has at least one
    skull-no-horns tile (the 28% target we pillaged) plus horned
    skulls and empty deposits."""
    bgr = load("sapphire_lv8_mine_after_depart.png")
    tiles = find_mine_tiles(bgr)

    by_flag: dict[str, list] = {}
    for t in tiles:
        by_flag.setdefault(t.flag, []).append(t)

    print(f"\nFound {len(tiles)} tiles, breakdown:")
    for flag, ts in sorted(by_flag.items()):
        print(f"  {flag}: {len(ts)}")
        for t in ts:
            print(f"    ({t.cx}, {t.cy})  pct={t.percent}")

    # At least 4 distinct tiles should be detected on this grid
    assert len(tiles) >= 4, f"expected ≥4 tiles, got {len(tiles)}"

    # The 28% mine in the bottom-left has skull-no-horns
    assert any(t.flag == "skull_no_horns" for t in tiles), \
        "expected at least one skull_no_horns tile"

    # The 74% and 72% mines have horned-skulls
    horned = [t for t in tiles if t.flag == "horned_skull"]
    assert len(horned) >= 1, f"expected ≥1 horned_skull, got {len(horned)}"

    # At least some empty deposits visible (no flag)
    empties = [t for t in tiles if t.flag == "empty"]
    assert len(empties) >= 1, f"expected ≥1 empty tile, got {len(empties)}"


def test_lv8_mine_grid_percent_reads_are_plausible():
    bgr = load("sapphire_lv8_mine_after_depart.png")
    tiles = find_mine_tiles(bgr)
    # Tiles with flags should have percent readings (they have green bars)
    flagged = [t for t in tiles if t.flag != "empty" and t.percent is not None]
    for t in flagged:
        assert 0 <= t.percent <= 100, f"impossible percent {t.percent}"


# ---------- popup detection ----------


def test_detect_no_popup_on_mine_grid():
    """When we're inside the Lv.8 mine view, none of the launch popups
    should be detected."""
    bgr = load("sapphire_lv8_mine_after_depart.png")
    popup = detect_popup(bgr)
    assert popup is None, f"false-positive popup: {popup}"


# ---------- sapphire side panel ----------


def test_idle_side_panel_state_is_known():
    """Smoke test the side-panel reader against the saved IDLE crop.
    The crop fixture isn't full-screen so we just verify the function
    doesn't crash on the crop and returns one of the known states."""
    bgr = load("city_sidepanel_idle.jpg")  # crop, not full-res
    # The reader expects 1080x2400 but should not crash on a crop —
    # it'll just return "absent" because the search window is wrong.
    # When we have a full-res IDLE fixture, switch this assertion to
    # `state == "idle"`.
    panel = read_sapphire_sidepanel(bgr)
    assert panel.state in {"idle", "active", "absent"}


# ---------- runner ----------


def _run_all():
    """Manual runner when pytest isn't available."""
    tests = [
        test_lv8_mine_grid_after_depart_detects_skull_no_horns,
        test_lv8_mine_grid_percent_reads_are_plausible,
        test_detect_no_popup_on_mine_grid,
        test_idle_side_panel_state_is_known,
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
