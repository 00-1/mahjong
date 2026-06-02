"""Validate scripts/pnc_iron_gather.py against fixtures.

Only the pure-vision decisions are tested here — actual taps need an
emulator or mock adb."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.pnc.state import (  # noqa: E402
    detect_popup,
    in_world_view,
    read_search_panel_lv,
    read_troop_count,
)

# Load scripts/pnc_iron_gather.py
_spec = importlib.util.spec_from_file_location(
    "pnc_iron_gather", ROOT / "scripts" / "pnc_iron_gather.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    bgr = cv2.imread(str(FIXTURES / name))
    assert bgr is not None, f"failed to read {name}"
    return bgr


def test_world_5of5_means_no_free_slots():
    """The world_view_clean fixture has Troop Info (5/5). Iron gather
    should bail out as 'no free slots' without sending."""
    bgr = load("world_view_clean.png")
    assert in_world_view(bgr) is True
    info = read_troop_count(bgr)
    assert info.n_active == 5
    free = info.n_total - info.n_active
    assert free == 0, f"expected 0 free slots, computed {free}"


def test_city_view_triggers_world_switch():
    """In city view, in_world_view returns False so the script will
    tap the WORLD bottom-nav button before counting troops."""
    bgr = load("city_view_clean.png")
    assert in_world_view(bgr) is False
    # And no popup blocks us
    assert detect_popup(bgr) is None


def test_search_panel_lv_returns_none_when_panel_absent():
    """On the plain world view (no search bottom-sheet) the slider
    reader must return None so the script knows to open the panel."""
    bgr = load("world_view_clean.png")
    assert read_search_panel_lv(bgr) is None


def test_iron_gather_constants_are_sane():
    """Calibrated taps from GATHER_RUN_STANDARD.md must match."""
    assert _mod.TAP_WORLD_NAV == (84, 2310)
    assert _mod.TAP_SEARCH_MAGNIFIER == (115, 1950)
    assert _mod.TAP_SLIDER_MINUS == (70, 1980)
    assert _mod.TAP_SLIDER_PLUS == (1015, 1980)
    assert _mod.TAP_SEARCH_BUTTON == (540, 2280)
    assert _mod.TAP_GATHER_MARKER == (520, 650)
    assert _mod.TAP_DEPART_CTA == (540, 2295)
    assert _mod.TARGET_LV == 5


def _run_all():
    tests = [
        test_world_5of5_means_no_free_slots,
        test_city_view_triggers_world_switch,
        test_search_panel_lv_returns_none_when_panel_absent,
        test_iron_gather_constants_are_sane,
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
