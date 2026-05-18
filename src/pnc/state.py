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

    # Alliance Duel Begins: VS shield, red-blue card split.
    # Close X at (990, 585) — the Begins popup is taller and the X
    # sits near the top.
    if _yellow_pixels_near(bgr, cx=990, cy=585, radius=40) and \
            _red_blue_split_near(bgr, cy=900):
        return Popup(name="alliance_duel", close_xy=(990, 585))

    # Alliance Duel Ends: WIN/LOSE scoreboard. Card is shorter than
    # Begins so the close X is lower at ~(970, 790), and the colour
    # split is reversed (WIN = blue on LEFT, LOSE = red on RIGHT). The
    # X is a thinner outline so yellow density at radius 40 only hits
    # ~0.10 — use a wider radius and a per-detector threshold.
    if _has_text_color(bgr, x=920, y=740, w=100, h=100,
                       hue_range=(15, 40), sat_min=100, val_min=150,
                       hit_threshold=0.06) and \
            _has_text_color(bgr, x=100, y=850, w=400, h=100,
                            hue_range=(100, 130), sat_min=80, val_min=40,
                            hit_threshold=0.15) and \
            _has_text_color(bgr, x=580, y=850, w=400, h=100,
                            hue_range=(165, 180), sat_min=80, val_min=40,
                            hit_threshold=0.15):
        # Red wraps around the hue wheel; the LOSE side reads in the
        # 165..180 band, NOT 0..15.
        return Popup(name="alliance_duel_ends", close_xy=(970, 790))

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


# ---------- post-Depart battle / mine-info screen detection ----------


def detect_battle_skip(bgr: np.ndarray) -> tuple[int, int] | None:
    """Return the tap point of the yellow SKIP chevron during a
    sapphire-mine battle animation, or None if the screen isn't a
    battle.

    Signature: a small yellow chevron-arrow at x≈980 y≈2080 on the
    bottom-right of the battle screen. Tight x bounds (900..1010)
    exclude the BAG/Mail icon-row in city view, which also has
    yellow blobs in this y-band but at x>1019.
    """
    roi = bgr[2030:2110, 900:1010]
    if roi.size == 0:
        return None
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, np.array([15, 100, 150]), np.array([30, 255, 255]))
    contours, _ = cv2.findContours(yellow, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = [c for c in contours if 400 < cv2.contourArea(c) < 3000]
    if not candidates:
        return None
    c = max(candidates, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(c)
    return (900 + x + w // 2, 2030 + y + h // 2)


def detect_mine_info_popup(bgr: np.ndarray) -> tuple[int, int] | None:
    """Return the tap point of the Pillage button on the Mine Info
    popup, or None.

    Signature: very large yellow CTA (≈45 000 px² in the canonical
    fixture) on the lower-right of the popup card around y=1689. The
    twin pickaxe-tip modal also has yellow CTAs at this y but PAIRED
    (one each at x≈308 and x≈772) — we treat single-yellow at right
    as Mine Info.
    """
    band = bgr[1640:1740, :]
    if band.size == 0:
        return None
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, np.array([15, 70, 120]), np.array([30, 255, 255]))
    contours, _ = cv2.findContours(yellow, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    big = [c for c in contours if cv2.contourArea(c) > 20000]
    if len(big) != 1:
        return None
    x, y, w, h = cv2.boundingRect(big[0])
    cx = x + w // 2
    if cx < 540:
        return None   # Left-side CTA → not Mine Info
    return (cx, 1640 + y + h // 2)


# ---------- header reads on the Lv.8 mine view ----------


def read_pillage_attempts_available(bgr: np.ndarray) -> bool | None:
    """Return True if the Lv.8 mine header is visible and the "Pillage
    Attempts:" row has a digit on the right, None if the header isn't
    visible at all.

    We currently don't distinguish 0 from N>0 — that requires a digit
    OCR pass we haven't built and a "Pillage Attempts:0" fixture we
    don't have. For now this returns True (header up, row present) or
    None (no header), and the caller treats both as "safe to attempt".

    The richer return signature is preserved so a future commit can
    plug in the 0-vs-N classifier without breaking callers.
    """
    # Look across the full y=280..315 row width — "Pillage Attempts:N"
    # is rendered as ~15+ contiguous glyph blobs because every letter
    # is a separate connected component. World/city fixtures have a
    # scattered handful (5-8) of bright UI blobs in this band.
    band = bgr[280:315, 600:1080]
    if band.size == 0:
        return None
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    bw = (gray > 140).astype(np.uint8) * 255
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw)
    digit_like = [i for i in range(1, n)
                  if 60 < stats[i, 4] < 500 and 5 < stats[i, 3] < 30]
    if len(digit_like) < 12:
        return None
    return True


def read_lv8_header(bgr: np.ndarray) -> dict:
    """Read the Lv.8 Mine header: pillage attempts, excavation time,
    output rate, sapphire balance.

    Currently exposes only pillage_attempts (True/False/None). The
    other fields (timer parse, output rate) require digit OCR and
    are deferred until needed.
    """
    return {
        "pillage_attempts": read_pillage_attempts_available(bgr),
    }


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
    "detect_battle_skip",
    "detect_mine_info_popup",
    "detect_popup",
    "find_mine_tiles",
    "read_lv8_header",
    "read_pillage_attempts_available",
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

    # The Troop Info panel has up to 5 fixed-position rows; the panel
    # COLLAPSES vertically when fewer rows are active. Below the last
    # active row the world map background shows through. Per-row
    # algorithm:
    #   1. confirm the panel still extends to row cy by checking the
    #      LEFT edge (x≈10) is dark-navy panel-background; if it's
    #      bright world-map, this and later rows don't exist
    #   2. sample the row's timer-text area for teal+orange pixel mass
    #
    # PNC renders timer text in two colour families: TEAL (hue ~85..100)
    # for long Gathering timers, ORANGE/GOLD (hue ~20..35) for short
    # Returning... / Marching timers. Calibrated 2026-05-17.
    ROW_CENTERS_Y = [345, 435, 525, 615, 705]
    ROW_HALF_HEIGHT = 20
    PER_ROW_MIN_PIXELS = 200
    PANEL_BG_V_MAX = 100      # panel background V is ~50..70; world map > 110

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    # Narrow ranges with high V — real timer text is bright (V > 190)
    # whereas world-map oranges (banners, dirt) are darker (V < 170).
    teal = cv2.inRange(hsv, np.array([85, 60, 190]), np.array([105, 255, 255]))
    gold = cv2.inRange(hsv, np.array([18, 50, 190]), np.array([32, 200, 255]))
    timer_mask = cv2.bitwise_or(teal, gold)

    n_rows = 0
    for i, cy in enumerate(ROW_CENTERS_Y):
        # Step 1: for rows 2..5, confirm the panel still extends here.
        # The empty middle column (x=250..320) is dark navy (V<100)
        # when the panel is present and bright (V>110) when the world
        # map shows through. Row 1's middle has the row-separator
        # gradient and reads bright in BOTH cases, so we skip the
        # check for row 1 — its timer mass alone tells us whether
        # row 1 is active.
        if i > 0:
            middle_strip = bgr[cy - 15: cy + 15, 250:320]
            if middle_strip.size == 0:
                break
            mean_v = float(cv2.cvtColor(middle_strip, cv2.COLOR_BGR2HSV)[:, :, 2].mean())
            if mean_v > PANEL_BG_V_MAX:
                break   # Panel ended above this row
        # Step 2: enough timer-coloured pixels in the timer-text area?
        # NOTE: when the panel is collapsed to ≤2 rows, the bottom
        # edge of the panel sometimes leaks orange/gold pixels into
        # the row 2/3 sample band even though no timer text is there.
        # That over-counts. Tracked as a known issue — for now the
        # caller (pnc_iron_gather) handles n_active>=N_TOTAL by
        # bailing, which is safe even if the true count is lower.
        band = timer_mask[cy - ROW_HALF_HEIGHT: cy + ROW_HALF_HEIGHT, 50:300]
        if int((band > 0).sum()) >= PER_ROW_MIN_PIXELS:
            n_rows += 1
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


def is_furnace_tab_active(bgr: np.ndarray) -> bool:
    """Detect whether the search panel's Furnace tab is currently
    selected. The active tab has a yellow diamond underline that's
    visibly brighter than the other tabs' borders.

    Calibrated 2026-05-17 against:
      - search_reopen fixture (Monster active): yellow at x≈940 = 0.013
      - furnace_tapped fixture (Furnace active): yellow at x≈940 = 0.039
    Threshold 0.025 separates cleanly.
    """
    roi = bgr[1800:1950, 890:990]
    if roi.size == 0:
        return False
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, np.array([20, 100, 180]), np.array([35, 255, 255]))
    return bool((yellow > 0).mean() > 0.025)


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
    # "SEARCH" header text — cyan/blue glow at y ≈ 1450..1530.
    # Earlier band y=1500..1580 missed the text on a Monster-tab panel
    # captured 2026-05-17; recentred + widened the search.
    header_band = bgr[1450:1530, 350:750]
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
