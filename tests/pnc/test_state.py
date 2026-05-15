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
    detect_battle_skip,
    detect_mine_info_popup,
    detect_popup,
    find_mine_tiles,
    in_world_view,
    read_sapphire_sidepanel,
    read_troop_count,
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
    """The fixture has known reads: 28% (skull_no_horns), 74% & 72%
    (the two horned skulls). All three flagged tiles must have a
    percent reading, and each must fall within 5pp of the known value."""
    bgr = load("sapphire_lv8_mine_after_depart.png")
    tiles = find_mine_tiles(bgr)
    flagged = [t for t in tiles if t.flag in ("skull_no_horns", "horned_skull")]
    assert all(t.percent is not None for t in flagged), \
        f"some flagged tiles have no percent: {[(t.flag, t.percent) for t in flagged]}"

    # The skull_no_horns is the 28% target.
    snh = [t for t in flagged if t.flag == "skull_no_horns"]
    assert len(snh) == 1
    assert abs(snh[0].percent - 28) <= 5, f"expected ~28%, got {snh[0].percent}"

    # The two horned reads are 72% and 74%; require both within 5pp.
    horned = sorted([t.percent for t in flagged if t.flag == "horned_skull"])
    assert len(horned) == 2
    assert abs(horned[0] - 72) <= 5, f"low horned should be ~72%, got {horned[0]}"
    assert abs(horned[1] - 74) <= 5, f"high horned should be ~74%, got {horned[1]}"


# ---------- popup detection ----------


def test_detect_no_popup_on_mine_grid():
    """When we're inside the Lv.8 mine view, none of the launch popups
    should be detected."""
    bgr = load("sapphire_lv8_mine_after_depart.png")
    popup = detect_popup(bgr)
    assert popup is None, f"false-positive popup: {popup}"


def test_detect_connection_failed_popup():
    """The 'Connection failed. Do you want to reconnect?' Tip card
    should be recognized as generic_tip_confirm so popup_dismiss
    taps CONFIRM at (540, 1440)."""
    bgr = load("popup_connection_failed.png")
    popup = detect_popup(bgr)
    assert popup is not None, "missed the popup"
    assert popup.name == "generic_tip_confirm"
    assert popup.confirm_xy == (540, 1440)


def test_detect_mythic_hero_popup():
    """Mythic Hero promo should be recognized so popup_dismiss
    taps the close X at (1005, 390). Mythic Hero must NOT be
    classified as generic_tip_confirm — the latter taps the centre
    of the card, which on Mythic Hero hits a purchase item."""
    bgr = load("popup_mythic_hero.png")
    popup = detect_popup(bgr)
    assert popup is not None, "missed the popup"
    assert popup.name == "mythic_hero", \
        f"misclassified as {popup.name} — would have hit a purchase item"
    assert popup.close_xy == (1005, 390)


# ---------- sapphire side panel ----------


def test_view_detection():
    """City vs world view, used by other readers as a gate."""
    city = load("city_view_clean.png")
    world = load("world_view_clean.png")
    assert in_world_view(city) is False, "city misidentified as world"
    assert in_world_view(world) is True, "world misidentified as city"


def test_troop_count_5of5():
    """World fixture has Troop Info (5/5) — five active gathering rows."""
    world = load("world_view_clean.png")
    info = read_troop_count(world)
    assert info.n_active == 5, f"expected 5 active troops, got {info.n_active}"


def test_troop_count_returns_none_on_city():
    """City view has no Troop Info panel — reader returns None."""
    city = load("city_view_clean.png")
    info = read_troop_count(city)
    assert info.n_active is None, \
        f"city view should give n_active=None, got {info.n_active}"


def test_sapphire_active_in_city_view():
    """City fixture shows 'Gathering 06:35:43' on sapphire row."""
    city = load("city_view_clean.png")
    panel = read_sapphire_sidepanel(city)
    assert panel.state == "active", \
        f"expected sapphire active, got {panel.state}"


def test_sapphire_idle_in_city_view():
    """The 2026-05-15 idle fixture shows 'Sapphire Mine / IDLE' — the
    reader must classify as idle, not misread 'IDLE' bright pixels
    as an active timer (earlier brightness-ratio heuristic did)."""
    bgr = load("city_sapphire_idle_2026-05-15.png")
    panel = read_sapphire_sidepanel(bgr)
    assert panel.state == "idle", \
        f"expected idle, got {panel.state}"


# ---------- battle / popup detection on post-Depart screens ----------


def test_battle_skip_button_found_during_battle():
    """Battle animation has the SKIP chevron at ~(979, 2083)."""
    bgr = load("battle_animation.png")
    xy = detect_battle_skip(bgr)
    assert xy is not None, "missed SKIP button on battle screen"
    assert 950 <= xy[0] <= 1010, f"SKIP x outside expected band: {xy}"
    assert 2030 <= xy[1] <= 2110, f"SKIP y outside expected band: {xy}"


def test_battle_skip_false_positive_on_city_view():
    """The city view has yellow icons in the bottom-nav (BAG, etc.)
    that the previous wider battle-skip ROI was matching. Tightening
    x to 900..1010 must now reject the city-view false positive."""
    bgr = load("city_view_clean.png")
    assert detect_battle_skip(bgr) is None


def test_mine_info_popup_returns_pillage_button_xy():
    """When the Mine Info popup is on screen, detect_mine_info_popup
    returns the centre of the Pillage CTA at (772, 1689) ± a few px."""
    bgr = load("mine_info_popup.png")
    xy = detect_mine_info_popup(bgr)
    assert xy is not None, "missed Pillage CTA on Mine Info popup"
    assert 700 <= xy[0] <= 850, f"Pillage x off: {xy}"
    assert 1640 <= xy[1] <= 1740, f"Pillage y off: {xy}"


def test_mine_info_popup_none_on_pickaxe_modal():
    """Pickaxe-tip modal has TWO yellow CTAs at this y — must not
    misclassify as Mine Info (which has only one, right-side)."""
    bgr = load("pickaxe_tip_modal.png")
    assert detect_mine_info_popup(bgr) is None


def test_mine_info_popup_none_on_unprotected_pit():
    """The unprotected-pit modal has a single CENTRED yellow CTA at
    x≈540 — must not match Mine Info's right-side signature."""
    bgr = load("unprotected_pit_modal.png")
    assert detect_mine_info_popup(bgr) is None


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
        test_detect_connection_failed_popup,
        test_detect_mythic_hero_popup,
        test_view_detection,
        test_troop_count_5of5,
        test_troop_count_returns_none_on_city,
        test_sapphire_active_in_city_view,
        test_sapphire_idle_in_city_view,
        test_idle_side_panel_state_is_known,
        test_battle_skip_button_found_during_battle,
        test_battle_skip_false_positive_on_city_view,
        test_mine_info_popup_returns_pillage_button_xy,
        test_mine_info_popup_none_on_pickaxe_modal,
        test_mine_info_popup_none_on_unprotected_pit,
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
