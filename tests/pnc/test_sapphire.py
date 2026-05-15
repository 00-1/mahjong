"""Validate scripts/pnc_sapphire.py target-selection against fixtures.

Tests the pure-decision logic in `select_target`. The actual tap
sequence isn't tested here — that needs an emulator or mock adb.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.pnc.state import find_mine_tiles  # noqa: E402

# Load scripts/pnc_sapphire.py without actually running its main loop
_spec = importlib.util.spec_from_file_location(
    "pnc_sapphire", ROOT / "scripts" / "pnc_sapphire.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
select_target = _mod.select_target
detect_recall_button = _mod.detect_recall_button

FIXTURES = Path(__file__).parent / "fixtures"


def test_pillage_target_picked_when_attempts_available():
    bgr = cv2.imread(str(FIXTURES / "sapphire_lv8_mine_after_depart.png"))
    tiles = find_mine_tiles(bgr)
    target = select_target(tiles, pillage_available=True)
    assert target is not None, "no target picked"
    assert target.flag == "skull_no_horns", \
        f"expected skull_no_horns, got {target.flag}"


def test_empty_target_picked_when_no_pillage():
    bgr = cv2.imread(str(FIXTURES / "sapphire_lv8_mine_after_depart.png"))
    tiles = find_mine_tiles(bgr)
    target = select_target(tiles, pillage_available=False)
    assert target is not None
    assert target.flag == "empty", \
        f"expected empty, got {target.flag}"


def test_horned_skulls_never_targeted():
    bgr = cv2.imread(str(FIXTURES / "sapphire_lv8_mine_after_depart.png"))
    tiles = find_mine_tiles(bgr)
    for pa in (True, False):
        target = select_target(tiles, pillage_available=pa)
        assert target is None or target.flag != "horned_skull", \
            f"with pillage={pa} got horned_skull target"


def test_recall_button_absent_after_depart_before_landing():
    """The 'after_depart' fixture was captured immediately after the
    Depart button was tapped — the march is still in transit, hasn't
    landed on the mine yet, so no Recall button is rendered."""
    bgr = cv2.imread(str(FIXTURES / "sapphire_lv8_mine_after_depart.png"))
    assert detect_recall_button(bgr) is False, \
        "false-positive recall: in-transit shouldn't show recall button"


def test_section1_all_horned_no_pillage_target():
    """The live-run section 1 fixture has 9 horned skulls and zero
    skull_no_horns — selector must return None so the script knows
    to page forward."""
    bgr = cv2.imread(str(FIXTURES / "lv8_grid_all_horned_section1.png"))
    tiles = find_mine_tiles(bgr)
    target = select_target(tiles, pillage_available=True)
    assert target is None, \
        f"section 1 should have no pillage target, got {target}"


def test_section2_has_pillageable_skull_no_horns():
    """The live-run section 2 fixture has one skull_no_horns at
    (799, 1713) — the target the user actually pillaged on 2026-05-15."""
    bgr = cv2.imread(str(FIXTURES / "lv8_grid_section2_has_skull.png"))
    tiles = find_mine_tiles(bgr)
    target = select_target(tiles, pillage_available=True)
    assert target is not None, "section 2 should have a pillage target"
    assert target.flag == "skull_no_horns"
    assert 750 <= target.cx <= 850 and 1670 <= target.cy <= 1760, \
        f"target coords off: ({target.cx}, {target.cy})"


def _run_all():
    tests = [
        test_pillage_target_picked_when_attempts_available,
        test_empty_target_picked_when_no_pillage,
        test_horned_skulls_never_targeted,
        test_recall_button_absent_after_depart_before_landing,
        test_section1_all_horned_no_pillage_target,
        test_section2_has_pillageable_skull_no_horns,
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
