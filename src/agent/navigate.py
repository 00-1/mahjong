"""Menu navigation: home -> Event Center -> Festival Event -> Arcane Puzzle
-> scroll to level -> tap Continue.

Steps 1-4 use calibrated taps from data/navigation_config.json
(scaled for current resolution if different from calibration).

Step 5 (Continue button) uses vision because the button's y-coord shifts
between attempts depending on how the level list settles. We find the
yellow CTA button via HSV color masking on the full-res screenshot,
filter by aspect ratio + size, pick the one closest to expected_y if
provided (from calibration as a hint), or just pick the topmost yellow
button if only one visible.

If anything fails the check, return a "needs_llm" status so the agent
knows to take over.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class NavStep:
    name: str
    tap: tuple[int, int] | None  # None for scroll/swipe
    swipe: tuple[int, int, int, int, int] | None  # (x1, y1, x2, y2, duration_ms)
    post_settle_sec: float
    expect_screen: str  # "puzzle" | "menu" — coarse check after the step


def find_yellow_buttons(bgr: np.ndarray) -> list[dict]:
    """Find yellow CTA-button-like regions in the screenshot.

    Returns list of {x, y, w, h, cx, cy, area} for each button candidate.
    Filters by:
    - Yellow hue (HSV H 18-35) — wide range covers gold/cream/warm yellows
    - Moderate saturation (S >= 80) — captures the muted gold of in-game buttons
    - High brightness (V >= 150)
    - Aspect ratio 1.5:1 to 5:1
    - Reasonable size for a UI button (5-30% width, 1.5-7% height)

    Also filters out regions that are NEAR-CIRCLE in shape (likely
    icon-buttons rather than CTA buttons).
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = cv2.split(hsv)
    yellow_mask = ((H >= 18) & (H <= 35) & (S >= 80) & (V >= 150)).astype(np.uint8) * 255

    k = 9
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    yellow_mask = cv2.morphologyEx(yellow_mask, cv2.MORPH_CLOSE, kernel)

    img_h, img_w = bgr.shape[:2]
    contours, _ = cv2.findContours(yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        # Filter: button size — width 5-30%, height 1.5-7% of image
        if w < img_w * 0.08 or w > img_w * 0.30:
            continue
        if h < img_h * 0.018 or h > img_h * 0.07:
            continue
        if area < img_w * img_h * 0.0015:  # min ~5k px on full-res screens
            continue
        aspect = w / max(1, h)
        if aspect < 1.5 or aspect > 5.0:
            continue
        candidates.append({
            "x": int(x), "y": int(y), "w": int(w), "h": int(h),
            "cx": int(x + w / 2), "cy": int(y + h / 2),
            "area": int(area),
        })
    candidates.sort(key=lambda c: c["cy"])
    return candidates


def find_continue_button(
    bgr: np.ndarray,
    expected_y_hint: int | None = None,
    y_search_range: int = 200,
) -> dict | None:
    """Locate the Continue button on the level-list screen.

    Strategy:
    - If only ONE yellow button visible: that's it.
    - If expected_y_hint given AND a button is within y_search_range of
      it: that's it.
    - Multiple yellow buttons with no hint: ambiguous, return None
      (caller can retry / fall back to LLM).
    """
    buttons = find_yellow_buttons(bgr)
    if not buttons:
        return None
    if len(buttons) == 1:
        return buttons[0]
    if expected_y_hint is not None:
        nearest = min(buttons, key=lambda b: abs(b["cy"] - expected_y_hint))
        if abs(nearest["cy"] - expected_y_hint) <= y_search_range:
            return nearest
    # Ambiguous
    return None


def detect_screen(bgr: np.ndarray) -> str:
    """Coarse classification of which screen we're on. Used to verify
    nav steps landed where we expect.

    Returns one of: "puzzle", "level_list", "festival_list",
    "event_center", "home", "unknown".
    """
    from src.vision.detect import DetectConfig, detect_tile_faces

    img_h, img_w = bgr.shape[:2]
    tile_faces = len(detect_tile_faces(bgr, DetectConfig()))
    if tile_faces >= 6:
        return "puzzle"

    yellow_buttons = find_yellow_buttons(bgr)
    if len(yellow_buttons) >= 1 and tile_faces < 6:
        # Yellow buttons in vertical list = level list
        # (Continue + Restart pairs)
        if len(yellow_buttons) >= 2:
            return "level_list"
        return "level_list"

    # Other heuristics could be added (e.g., look for "Festival Event"
    # text via OCR). For now, if we don't detect puzzle/level_list,
    # call it unknown.
    return "unknown"
