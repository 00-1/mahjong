"""PNC state-detection: pull structured information out of a screenshot.

All public functions take a `bgr` ndarray (cv2 BGR, full-res
1080x2400) and return either a dataclass or a primitive. No I/O,
no taps — pure vision.

Coordinate convention: phone pixels, origin top-left, x right, y down.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


PHONE_W = 1080
PHONE_H = 2400


# ---------- popup detection ----------

# Each known popup has a signature pixel range (small rectangle in
# the centre of the popup card that's unique enough to identify it)
# plus the (x,y) coord of its close button.
#
# Detection: crop the signature region, compute the dominant colour
# bucket, compare against the expected. If matched, that popup is up.
#
# We avoid OCR here — too slow and fragile. Colour + position is
# enough because popups have distinct visual styles.

@dataclass
class Popup:
    name: str            # e.g. "mythic_hero", "curio", "alliance_duel"
    close_xy: tuple[int, int]   # tap coord to dismiss
    confirm_xy: tuple[int, int] | None = None  # set when "CONFIRM"-style action


def _crop_mean_hsv(bgr: np.ndarray, x: int, y: int, w: int, h: int) -> tuple[float, float, float]:
    """Mean HSV of a rectangle. Used as a cheap fingerprint."""
    crop = bgr[y:y + h, x:x + w]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    return tuple(hsv.reshape(-1, 3).mean(axis=0))


def _is_mostly_dark(bgr: np.ndarray) -> bool:
    """Whole image average brightness check. True when phone screen is
    off or in a loading splash."""
    if bgr is None or bgr.size == 0:
        return True
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return float(gray.mean()) < 15.0


# These detectors are loose — each finds a "yellow CTA" or specific
# header text colour at a known location. We may produce false positives
# in edge cases, so the caller should snap-tap-resnap to verify the
# popup actually closed.


def detect_popup(bgr: np.ndarray) -> Optional[Popup]:
    """Return the topmost popup if a known one is on screen, else None.

    Detection order matters — the launch chain shows multiple popups
    one after another. We check them in roughly-decreasing card size
    (largest covers more).
    """
    if _is_mostly_dark(bgr):
        return None

    # All popups have an "X" close button as a yellow/gold circle near
    # the top-right of the card. The card position varies, but the X
    # is always on a darkblue panel background.
    # We sample distinctive header pixels to disambiguate.

    # Detection ordered: most-specific signatures FIRST. The
    # generic_tip_confirm fallback is intentionally last because it
    # matches on a generic navy-blue panel that several other popups
    # also have.

    # Mythic Hero: tall card with prominent orange/fire flames bottom
    # and a yellow GBP-price button about (540, 1900). The close X
    # itself is whitish, not a reliable signal.
    if _orange_pixels_near(bgr, cx=540, cy=900, radius=60) and \
            _yellow_pixels_near(bgr, cx=540, cy=1907, radius=80):
        return Popup(name="mythic_hero", close_xy=(1005, 390))

    # Alliance Duel Begins: VS shield, red-blue card split
    if _yellow_pixels_near(bgr, cx=990, cy=585, radius=40) and \
            _red_blue_split_near(bgr, cy=900):
        return Popup(name="alliance_duel", close_xy=(990, 585))

    # Curio (Rusty Alloy): hammer-style card
    if _yellow_pixels_near(bgr, cx=1005, cy=435, radius=40) and \
            _has_text_color(bgr, x=420, y=900, w=200, h=80,
                            hue_range=(20, 30), sat_min=80, val_min=120,
                            hit_threshold=0.05):
        return Popup(name="curio", close_xy=(1005, 435))

    # Limited Offer: tabs at top (Daily Discount / Limited Offer / Hero Sale)
    # No close X — needs back keyevent
    if _has_text_color(bgr, x=80, y=80, w=300, h=80,
                       hue_range=(20, 35), sat_min=100, val_min=180,
                       hit_threshold=0.10) and \
            _has_text_color(bgr, x=80, y=130, w=300, h=80,
                            hue_range=(20, 35), sat_min=100, val_min=180,
                            hit_threshold=0.10):
        return Popup(name="limited_offer", close_xy=(540, 0))  # back-key sentinel

    # Battery saver Android dialog: dark background, "Got it" button
    # Distinguished from PNC popups by overall darkness above y=1900
    if _has_text_color(bgr, x=80, y=2270, w=200, h=80,
                       hue_range=(0, 180), sat_min=0, val_min=80,
                       hit_threshold=0.30) and \
            _crop_mean_hsv(bgr, 0, 1900, 1080, 100)[2] < 50:
        return Popup(name="battery_saver", close_xy=(285, 2310))

    # Generic Tip + CONFIRM card: must come LAST because the
    # navy-blue interior matches many other popups too. Distinguish
    # via panel SIZE: this Tip card has a CONFIRM button centered
    # around (540, 1440) AND no other distinctive popup signature
    # higher up. We require the centered CONFIRM-shaped grey button.
    if _has_text_color(bgr, x=320, y=1320, w=440, h=160,
                       hue_range=(100, 130), sat_min=60, val_min=50,
                       hit_threshold=0.40) and \
            _has_grey_button_near(bgr, cx=540, cy=1440):
        return Popup(name="generic_tip_confirm",
                     close_xy=(540, 1440),
                     confirm_xy=(540, 1440))

    return None


def _has_grey_button_near(bgr: np.ndarray, cx: int, cy: int, w: int = 200, h: int = 80) -> bool:
    """The generic Tip CONFIRM button is a desaturated light-blue/grey
    rounded rectangle (HSV mean ~ hue 110, sat 90, val 165 from
    fixtures). Distinguishes from the saturated-yellow Mythic /
    Curio CTAs."""
    x0 = max(0, cx - w // 2)
    y0 = max(0, cy - h // 2)
    crop = bgr[y0:y0 + h, x0:x0 + w]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # Light desaturated blue/grey button colour
    button = cv2.inRange(hsv, np.array([90, 30, 130]), np.array([130, 130, 220]))
    return (button > 0).mean() > 0.20


def _yellow_pixels_near(bgr: np.ndarray, cx: int, cy: int, radius: int) -> bool:
    """Check that a yellow/gold blob is near (cx, cy)."""
    x0, y0 = max(0, cx - radius), max(0, cy - radius)
    x1, y1 = min(bgr.shape[1], cx + radius), min(bgr.shape[0], cy + radius)
    crop = bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([15, 100, 100]), np.array([40, 255, 255]))
    return (mask > 0).mean() > 0.20


def _orange_pixels_near(bgr: np.ndarray, cx: int, cy: int, radius: int) -> bool:
    x0, y0 = max(0, cx - radius), max(0, cy - radius)
    x1, y1 = min(bgr.shape[1], cx + radius), min(bgr.shape[0], cy + radius)
    crop = bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # Orange/red flames
    mask = cv2.inRange(hsv, np.array([0, 100, 100]), np.array([20, 255, 255]))
    return (mask > 0).mean() > 0.15


def _red_blue_split_near(bgr: np.ndarray, cy: int, band_h: int = 100) -> bool:
    """Detect the Alliance Duel VS card: left half reddish, right half blueish."""
    y0, y1 = max(0, cy - band_h // 2), min(bgr.shape[0], cy + band_h // 2)
    left = bgr[y0:y1, 100:500]
    right = bgr[y0:y1, 580:980]
    if left.size == 0 or right.size == 0:
        return False
    lh = cv2.cvtColor(left, cv2.COLOR_BGR2HSV)
    rh = cv2.cvtColor(right, cv2.COLOR_BGR2HSV)
    left_red = cv2.inRange(lh, np.array([0, 80, 60]), np.array([15, 255, 255])).mean() / 255
    right_blue = cv2.inRange(rh, np.array([100, 80, 40]), np.array([130, 255, 255])).mean() / 255
    return left_red > 0.05 and right_blue > 0.05


def _has_text_color(bgr: np.ndarray, x: int, y: int, w: int, h: int,
                    hue_range: tuple[int, int], sat_min: int, val_min: int,
                    hit_threshold: float) -> bool:
    """Generic hue/sat/val check in a region."""
    crop = bgr[y:y + h, x:x + w]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array([hue_range[0], sat_min, val_min]),
        np.array([hue_range[1], 255, 255]),
    )
    return (mask > 0).mean() > hit_threshold


# ---------- sapphire mine tile classification ----------

@dataclass
class MineTile:
    """One sapphire deposit tile on the Lv.8 mine grid view."""
    cx: int                       # tap target (centre of deposit + cart)
    cy: int
    flag: str                     # "empty", "horned_skull", "skull_no_horns",
                                  # "friendly_person", "unknown"
    percent: int | None = None    # remaining capacity 0-100, None if no bar
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h of flag


# The Lv.8 mine view is rendered as an isometric grid. Sapphire
# deposits are clusters of cyan crystals on grey rock. Flags appear
# in the upper-right of each tile — a red banner with a white emblem.
#
# Detection approach:
#   1. Find cyan-crystal blobs (the deposits). These are the candidate
#      mine centres.
#   2. For each crystal blob, look in a small box up-and-right for a
#      red banner. If found, the tile is occupied.
#   3. Classify the banner's emblem by template matching against
#      reference crops we'll keep in `tests/pnc/fixtures/flags/`.


def find_mine_tiles(bgr: np.ndarray) -> list[MineTile]:
    """Return all sapphire-deposit tiles found in the Lv.8 mine view.

    Works on the grid area only — y from ~800 to ~2050 in the
    canonical 1080x2400 screen.
    """
    grid = bgr[800:2050, :]
    hsv = cv2.cvtColor(grid, cv2.COLOR_BGR2HSV)

    # Cyan crystals: hue ~85-100, sat high
    crystal_mask = cv2.inRange(
        hsv,
        np.array([85, 100, 100]),
        np.array([105, 255, 255]),
    )
    # Dilate so each cluster forms a single blob
    kernel = np.ones((15, 15), np.uint8)
    dilated = cv2.dilate(crystal_mask, kernel, iterations=2)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    tiles: list[MineTile] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # Reject tiny blobs (noise) and very large ones (background)
        if w * h < 8000 or w * h > 80000:
            continue
        cx = x + w // 2
        cy_full = (y + h // 2) + 800  # shift back into full-image y

        flag, banner_bbox = _classify_flag(bgr, cx, cy_full)
        pct = _read_percent_bar(bgr, cx, cy_full)
        tiles.append(MineTile(cx=cx, cy=cy_full, flag=flag,
                              percent=pct, bbox=banner_bbox))
    # De-duplicate near-coincident tiles (same crystal cluster seen twice)
    tiles = _dedupe_tiles(tiles)
    return tiles


def _classify_flag(bgr: np.ndarray, deposit_cx: int, deposit_cy: int) -> tuple[str, tuple[int, int, int, int]]:
    """Look up-and-right of the deposit for a red banner; if found,
    classify the emblem.

    Returns (flag_label, banner_bbox). banner_bbox is (0,0,0,0) for empty.
    """
    # Look in a box upper-right of the deposit centre
    x0 = max(0, deposit_cx)
    y0 = max(0, deposit_cy - 100)
    x1 = min(bgr.shape[1], deposit_cx + 200)
    y1 = min(bgr.shape[0], deposit_cy)
    roi = bgr[y0:y1, x0:x1]
    if roi.size == 0:
        return "empty", (0, 0, 0, 0)

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # Red banner: hue near 0 (or near 180), high sat, mid value
    red1 = cv2.inRange(hsv, np.array([0, 120, 80]), np.array([10, 255, 255]))
    red2 = cv2.inRange(hsv, np.array([170, 120, 80]), np.array([180, 255, 255]))
    red = cv2.bitwise_or(red1, red2)
    if (red > 0).mean() < 0.03:
        return "empty", (0, 0, 0, 0)

    # Find the banner contour
    contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return "empty", (0, 0, 0, 0)
    banner = max(contours, key=cv2.contourArea)
    bx, by, bw, bh = cv2.boundingRect(banner)
    bbox = (x0 + bx, y0 + by, bw, bh)

    # Classify the emblem inside the banner. The emblem is white-ish,
    # so look at the shape of the white blob. Horned skulls produce
    # two upward spikes above the skull dome — show up as a wider top
    # extent. Skull-no-horns is a uniform oval/round.
    emblem_roi = roi[by:by + bh, bx:bx + bw]
    emblem_hsv = cv2.cvtColor(emblem_roi, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(emblem_hsv, np.array([0, 0, 180]), np.array([180, 60, 255]))
    if (white > 0).mean() < 0.03:
        return "unknown", bbox

    # Tighten the bounding box to just the white-emblem rows. The
    # red banner has a shaped top (extends above the skull) so the
    # raw bbox includes a lot of red-only area at top; trimming to
    # rows that actually contain white gives a fair comparison.
    rows_with_white = np.where(white.any(axis=1))[0]
    if rows_with_white.size < 4:
        return "unknown", bbox
    y_top = int(rows_with_white[0])
    y_bot = int(rows_with_white[-1])
    emblem = white[y_top: y_bot + 1]
    eh, ew = emblem.shape
    if eh < 8 or ew < 5:
        return "unknown", bbox

    # Density check: count the white-pixel FRACTION in the top
    # quartile vs the middle half of the emblem.
    #
    # Horned skull: thin horn strokes give LOW density in the top
    #               quartile (lots of dark/red between the horns).
    # No-horns:    wide rounded cranium fills the top quartile
    #               densely.
    top_q = emblem[: max(1, eh // 4)]
    mid_q = emblem[eh // 4: 3 * eh // 4]
    top_density = (top_q > 0).mean()
    mid_density = (mid_q > 0).mean()
    if mid_density < 0.05:
        return "unknown", bbox
    ratio = top_density / mid_density
    # Empirically:
    #   horned skull ratio < 0.35 (sparse top from thin horns)
    #   no-horns skull ratio > 0.55 (dense rounded cranium)
    if ratio < 0.45:
        return "horned_skull", bbox
    return "skull_no_horns", bbox


def _read_percent_bar(bgr: np.ndarray, deposit_cx: int, deposit_cy: int) -> Optional[int]:
    """Read the green progress-bar fill ratio below a deposit, if any.

    Returns int 0-100 estimated from green-bar span / total-bar-width,
    or None if no bar visible. Calibrated 2026-05-09 against the
    sapphire_lv8_mine_after_depart fixture (known 28/72/74 %): the
    bar sits ~50 px below the deposit centre and a full bar spans
    roughly 226 px. The 28%-known tile reads as 30% with these
    constants — within tolerance for the gameplay decision (we just
    want low-vs-high to pick a pillage target).
    """
    # The strip is below the deposit at dy ≈ +75..+100 (calibrated
    # against fixture 2026-05-09). Earlier probe at +30..+90 hit
    # noise and missed the real bar.
    y0 = min(bgr.shape[0], deposit_cy + 60)
    y1 = min(bgr.shape[0], deposit_cy + 110)
    x0 = max(0, deposit_cx - 120)
    x1 = min(bgr.shape[1], deposit_cx + 120)
    roi = bgr[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([35, 100, 100]), np.array([85, 255, 255]))
    if (green > 0).mean() < 0.04:
        return None
    # Pick the densest single green-row band — protects against
    # stray green specks (isometric tile shading) elsewhere in the ROI.
    row_green = (green > 0).sum(axis=1)
    if row_green.max() < 30:
        return None
    best_row = int(np.argmax(row_green))
    band = green[max(0, best_row - 2): best_row + 3]
    cols = np.where(band.any(axis=0))[0]
    if cols.size == 0:
        return None
    bar_width = int(cols[-1] - cols[0] + 1)
    total_bar = 226   # calibrated from the 72% / 74% reference tiles
    pct = int(round(100 * bar_width / total_bar))
    return min(100, max(0, pct))


def _dedupe_tiles(tiles: list[MineTile], min_dist: int = 80) -> list[MineTile]:
    """Merge tiles whose centres are within `min_dist` pixels of each
    other — these are the same physical deposit detected twice (e.g.
    upper-vs-lower cluster of the same isometric pile).
    """
    out: list[MineTile] = []
    for t in tiles:
        merged = False
        for o in out:
            if abs(t.cx - o.cx) < min_dist and abs(t.cy - o.cy) < min_dist:
                # Prefer the one with a known flag over "empty"
                if t.flag != "empty" and o.flag == "empty":
                    out.remove(o)
                    out.append(t)
                merged = True
                break
        if not merged:
            out.append(t)
    return out


# ---------- header reads on the Lv.8 mine view ----------


def read_lv8_header(bgr: np.ndarray) -> dict:
    """Read the Lv.8 Mine header: pillage attempts, excavation time,
    output rate, sapphire balance.

    Returns a dict (or empty dict if not on the Lv.8 mine screen).
    Currently a placeholder — populate fields as we add OCR for each
    line. Pillage attempts is the highest priority since the script
    branches on it.
    """
    out: dict = {}

    # "Pillage Attempts:N" appears around y=180..220 on the right side
    # (after "Excavation Time"). Detection: find the white text strip
    # right of x=600 in that y range.
    header = bgr[100:240, 500:1080]
    if header.size == 0:
        return out

    # Cheap binary read: find the digit right after "Pillage Attempts:"
    # Without OCR, we estimate by counting the bright pixel area in
    # the digit column. Fallback: return None and let the caller
    # treat unknown as "play it safe — find empty mine, not pillage".
    out["pillage_attempts"] = None  # TODO OCR
    return out


# ---------- sapphire side-panel state ----------

@dataclass
class SapphireSidePanel:
    state: str   # "idle", "active", "absent"
    timer_seconds: int | None = None   # seconds remaining if active


def read_sapphire_sidepanel(bgr: np.ndarray) -> SapphireSidePanel:
    """Read the sapphire row from the city-view left side panel.

    The sapphire row has a blue-crystal icon. State is one of:
      - "absent": no sapphire row visible (e.g. world view, or a
        post-update screen where it hasn't loaded yet)
      - "idle": shows "Sapphire Mine IDLE" text
      - "active": shows a timer like "HH:MM:SS"

    Returns the state plus the timer seconds when active.
    """
    # Search the left-side panel column for a cyan crystal icon
    panel = bgr[400:1300, 0:200]
    hsv = cv2.cvtColor(panel, cv2.COLOR_BGR2HSV)
    cyan = cv2.inRange(hsv, np.array([85, 120, 120]), np.array([105, 255, 255]))
    contours, _ = cv2.findContours(cyan, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # Filter to icon-sized blobs (~60x60)
    icon_blobs = [c for c in contours if 1500 < cv2.contourArea(c) < 8000]
    if not icon_blobs:
        return SapphireSidePanel(state="absent")

    # Take the topmost crystal icon — that's the sapphire row.
    icon_blobs.sort(key=lambda c: cv2.boundingRect(c)[1])
    x, y, w, h = cv2.boundingRect(icon_blobs[0])
    label_y0 = 400 + y + h
    # Bottom line of the 2-line label is "IDLE" (4 chars) when idle
    # or "HH:MM:SS" (~8 chars) when actively gathering. Count
    # glyph-sized connected components in the LEFT half of that line
    # (x < 100 in the label crop) to dodge background noise from the
    # building behind the panel.
    bot = bgr[label_y0 + 40: label_y0 + 80, x: x + 100]
    if bot.size == 0:
        return SapphireSidePanel(state="absent")
    gray = cv2.cvtColor(bot, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
    n_lbl, _, stats, _ = cv2.connectedComponentsWithStats(bw)
    glyph_count = 0
    for i in range(1, n_lbl):
        w_, h_, a_ = stats[i, 2], stats[i, 3], stats[i, 4]
        if 3 <= w_ <= 25 and 5 <= h_ <= 35 and 12 <= a_ <= 400:
            glyph_count += 1
    # IDLE: ~4 glyphs (I D L E). Timer: ~7+ (digits + colon dots).
    # Threshold at 5 leaves headroom either way.
    if glyph_count >= 5:
        return SapphireSidePanel(state="active", timer_seconds=None)
    if glyph_count >= 2:
        return SapphireSidePanel(state="idle")
    return SapphireSidePanel(state="absent")


__all__ = [
    "Popup",
    "MineTile",
    "SapphireSidePanel",
    "TroopInfo",
    "detect_popup",
    "find_mine_tiles",
    "read_lv8_header",
    "read_sapphire_sidepanel",
    "read_troop_count",
    "read_search_panel_lv",
    "in_world_view",
]


# ---------- world-map troop count ----------

@dataclass
class TroopInfo:
    """Header reads off the world-map Troop Info panel."""
    n_active: int | None     # 0..5 (None when panel not visible)
    n_total: int = 5         # always 5 for our castle


def read_troop_count(bgr: np.ndarray) -> TroopInfo:
    """Parse the 'Troop Info (N/5)' header in the world-view top-left.

    Approach: count the visible Gathering / Marching / Returning rows
    in the panel. Each row is the same height (~70px) and starts at
    a known y. Counting by row-detection avoids needing OCR for the
    header text.

    Returns n_active=None when not on world view (panel absent).
    """
    if not in_world_view(bgr):
        return TroopInfo(n_active=None)

    # The Troop Info panel is in the top-left of world view at
    # roughly x=0..420, y=240..830.
    panel = bgr[240:830, 0:420]
    if panel.size == 0:
        return TroopInfo(n_active=None)

    # Each row has a tealish-cyan timer text and a row separator.
    # Detect rows via the timer-text colour band.
    hsv = cv2.cvtColor(panel, cv2.COLOR_BGR2HSV)
    # Tealish: hue ~70-100, mid-high sat
    teal = cv2.inRange(hsv, np.array([70, 60, 120]), np.array([100, 255, 255]))
    # Sum per row
    row_signal = teal.sum(axis=1)
    # Find local peaks above a threshold
    threshold = max(row_signal.max() * 0.15, 200)
    in_row = row_signal > threshold
    # Count contiguous true regions
    n_rows = 0
    i = 0
    while i < len(in_row):
        if in_row[i]:
            n_rows += 1
            while i < len(in_row) and in_row[i]:
                i += 1
        i += 1
    if n_rows == 0:
        return TroopInfo(n_active=None)
    return TroopInfo(n_active=min(5, n_rows), n_total=5)


def in_world_view(bgr: np.ndarray) -> bool:
    """Heuristic: in world view the leftmost bottom-nav label is
    'WORLD' rendered in WHITE (inactive label colour). In city view
    the same slot is 'HOME' rendered in GOLD (active label colour).
    Detect via gold-pixel mass in the leftmost bottom-nav region.
    """
    nav = bgr[2300:2400, 50:200]
    if nav.size == 0:
        return False
    hsv = cv2.cvtColor(nav, cv2.COLOR_BGR2HSV)
    gold = cv2.inRange(hsv, np.array([15, 100, 100]), np.array([40, 255, 255]))
    # City: HOME label is gold (lots of gold pixels)
    # World: WORLD label is white (low gold pixels)
    gold_density = (gold > 0).mean()
    return bool(gold_density < 0.05)


# ---------- search-panel slider ----------


def read_search_panel_lv(bgr: np.ndarray) -> int | None:
    """Read the Lv.N indicator above the slider in the search panel.

    The label is gold "Lv.N" text at approximately (550, 1955) above
    the slider. Without OCR we estimate N from the slider thumb
    position: the slider track spans roughly x=130..1000 with N steps
    (Lv1..Lv7 for Furnace).

    Returns 1..7 for Furnace, 1..40 for Monster, etc., or None if
    the panel isn't open.
    """
    # First confirm the search panel is up by looking for the
    # "SEARCH" header text white-pixels at a known location.
    header_band = bgr[1500:1580, 350:750]
    if header_band.size == 0:
        return None
    hsv_h = cv2.cvtColor(header_band, cv2.COLOR_BGR2HSV)
    hdr_blue = cv2.inRange(hsv_h, np.array([85, 50, 130]), np.array([110, 255, 255]))
    if (hdr_blue > 0).mean() < 0.04:
        return None

    # Find the slider thumb — a small oval shape on the slider track
    # at y ≈ 1985. Detect by white-pixel mass in narrow rows.
    track = bgr[1965:2010, 90:1040]
    if track.size == 0:
        return None
    gray = cv2.cvtColor(track, cv2.COLOR_BGR2GRAY)
    # Thumb is bright white; find the brightest column band
    col_brightness = gray.mean(axis=0)
    # Smooth a bit
    if col_brightness.size < 30:
        return None
    smooth = np.convolve(col_brightness, np.ones(20) / 20, mode="same")
    thumb_x = int(np.argmax(smooth))
    track_width = track.shape[1]
    # Thumb position fraction
    frac = thumb_x / max(1, track_width - 1)
    # We don't know whether it's Furnace (1-7) or Monster (1-40) just
    # from this — caller decides. Return the fraction-rounded position
    # assuming Furnace 1-7.
    lv = int(round(frac * 6)) + 1
    return max(1, min(7, lv))
