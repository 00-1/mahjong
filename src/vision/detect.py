"""First-pass tile-cell detection.

Strategy: bright cream tile faces stand out hard against the dark green
background. Threshold on Value (HSV) + low-to-mid Saturation, clean up with
morphology, find contours, filter by area and aspect ratio.

This catches *visible* (top-of-stack) tile fronts. Ghosted tiles peeking out
from below show up as much darker patches and are deliberately excluded —
we'll handle stack depth in a later pass.

Tunables live in DetectConfig; we'll iterate them against debug overlays.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class DetectConfig:
    # HSV thresholds for "bright cream tile face"
    v_min: int = 180
    s_max: int = 90
    # Morphology kernel for cleanup
    morph_kernel: int = 7
    # Contour area filter (fraction of image area)
    min_area_frac: float = 0.0015
    max_area_frac: float = 0.02
    # Aspect ratio (w/h) acceptable range — tiles are roughly square
    min_aspect: float = 0.7
    max_aspect: float = 1.3


@dataclass
class Detection:
    x: int
    y: int
    w: int
    h: int
    area: int

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2

    def as_dict(self) -> dict:
        return {
            "x": self.x, "y": self.y, "w": self.w, "h": self.h,
            "cx": self.cx, "cy": self.cy, "area": self.area,
        }


def detect_tile_faces(bgr: np.ndarray, cfg: DetectConfig | None = None) -> list[Detection]:
    cfg = cfg or DetectConfig()
    h, w = bgr.shape[:2]
    img_area = h * w

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = cv2.split(hsv)
    mask = ((V >= cfg.v_min) & (S <= cfg.s_max)).astype(np.uint8) * 255

    k = cfg.morph_kernel
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    detections: list[Detection] = []
    min_area = cfg.min_area_frac * img_area
    max_area = cfg.max_area_frac * img_area
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue
        x, y, ww, hh = cv2.boundingRect(cnt)
        aspect = ww / hh if hh else 0
        if aspect < cfg.min_aspect or aspect > cfg.max_aspect:
            continue
        detections.append(Detection(x=x, y=y, w=ww, h=hh, area=int(area)))

    # Sort top-to-bottom, left-to-right for stable output
    detections.sort(key=lambda d: (d.cy, d.cx))
    return detections


def draw_overlay(bgr: np.ndarray, detections: list[Detection]) -> np.ndarray:
    out = bgr.copy()
    for i, d in enumerate(detections):
        cv2.rectangle(out, (d.x, d.y), (d.x + d.w, d.y + d.h), (0, 255, 0), 3)
        cv2.putText(
            out, str(i), (d.x + 4, d.y + 24),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA,
        )
    return out


def write_mask_debug(bgr: np.ndarray, cfg: DetectConfig, path: str) -> None:
    """Dump just the binary mask for tuning."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    _, S, V = cv2.split(hsv)
    mask = ((V >= cfg.v_min) & (S <= cfg.s_max)).astype(np.uint8) * 255
    cv2.imwrite(path, mask)
