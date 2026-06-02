"""Tile fingerprint library.

Each unique tile face is registered once with:
- a perceptual hash (pHash) computed from a centered crop of the tile face
- an auto-assigned ID (tile_001, tile_002, ...)
- a saved sample image for labeling later
- an optional human-readable label

Lookup: hash a new crop, find the closest existing entry; if hamming distance
< threshold, return that ID, else register a new entry.

Persistent storage: data/tiles/index.json + data/tiles/samples/<id>.jpg
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image


HASH_SIZE = 16  # 16x16 = 256-bit phash
DEFAULT_HAMMING_THRESHOLD = 60  # out of 256: same-art pairs observed up to 44; different-art >= 108

MAX_SAMPLES_PER_TILE = 4  # keep a few example crops per tile for inspection; skip saving once full


@dataclass
class TileEntry:
    tile_id: str
    phash: str
    label: str | None = None
    samples: list[str] = field(default_factory=list)
    first_seen: str | None = None  # screenshot path

    def hash_obj(self) -> imagehash.ImageHash:
        return imagehash.hex_to_hash(self.phash)


def crop_face_center(bgr: np.ndarray, x: int, y: int, w: int, h: int, frac: float = 0.78) -> np.ndarray:
    """Centered crop of a tile bbox to ignore the cream border + small art halo."""
    cx, cy = x + w // 2, y + h // 2
    cw, ch = int(w * frac / 2), int(h * frac / 2)
    return bgr[cy - ch:cy + ch, cx - cw:cx + cw].copy()


def phash_of(bgr_crop: np.ndarray) -> imagehash.ImageHash:
    pil = Image.fromarray(cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2RGB))
    return imagehash.phash(pil, hash_size=HASH_SIZE)


class TileLibrary:
    def __init__(self, root: Path):
        self.root = root
        self.index_path = root / "index.json"
        self.samples_dir = root / "samples"
        self.entries: list[TileEntry] = []
        self._load()

    def _load(self) -> None:
        if self.index_path.exists():
            data = json.loads(self.index_path.read_text())
            self.entries = [TileEntry(**e) for e in data.get("entries", [])]
        # Cache per-entry sample-phash list for multi-sample distance.
        # Computed lazily on first match request.
        self._sample_phashes: dict[str, list[imagehash.ImageHash]] = {}

    def _sample_hashes(self, entry: TileEntry) -> list[imagehash.ImageHash]:
        """All phashes for this entry: the canonical phash plus any saved
        sample crops. Used to compute multi-sample matching distance — a
        new crop matches the entry if it's close to ANY of the entry's
        samples, not just the entry's primary phash. This captures
        same-tile variation across runs / contexts (tray vs main, lighting
        differences, depth-2 vs depth-1 background)."""
        if entry.tile_id in self._sample_phashes:
            return self._sample_phashes[entry.tile_id]
        hashes = [entry.hash_obj()]
        for sp in entry.samples:
            full = self.root.parent / sp if not Path(sp).is_absolute() else Path(sp)
            try:
                bgr = cv2.imread(str(full))
                if bgr is None:
                    continue
                hashes.append(phash_of(bgr))
            except Exception:
                continue
        self._sample_phashes[entry.tile_id] = hashes
        return hashes

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.samples_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(
            {"entries": [asdict(e) for e in self.entries]},
            indent=2,
        ))

    def _next_id(self) -> str:
        return f"tile_{len(self.entries) + 1:03d}"

    def lookup_or_add(
        self,
        bgr_crop: np.ndarray,
        source: str,
        threshold: int = DEFAULT_HAMMING_THRESHOLD,
    ) -> tuple[TileEntry, int, bool]:
        """Return (entry, hamming_distance, was_added).
        was_added=True means we registered a new tile.
        hamming_distance is 0 for new entries."""
        h = phash_of(bgr_crop)
        # Multi-sample distance: for each entry, take min distance to any
        # of its sample crops (not just the canonical phash). Catches
        # same-tile crops that drift in pHash space across contexts —
        # tray vs main_board, depth-2 reveals with peeking neighbours,
        # subtle scaling/lighting changes between runs.
        best: tuple[TileEntry, int] | None = None
        for e in self.entries:
            d = min((h - hh) for hh in self._sample_hashes(e))
            if best is None or d < best[1]:
                best = (e, d)

        if best is not None and best[1] <= threshold:
            entry = best[0]
            if len(entry.samples) < MAX_SAMPLES_PER_TILE:
                sample_path = self._save_sample(bgr_crop, entry.tile_id, len(entry.samples))
                entry.samples.append(sample_path)
                # Invalidate the cached sample-hash list — new sample changes the
                # min-distance for this entry.
                self._sample_phashes.pop(entry.tile_id, None)
                self.save()
            return entry, best[1], False

        tile_id = self._next_id()
        sample_path = self._save_sample(bgr_crop, tile_id, 0)
        entry = TileEntry(
            tile_id=tile_id,
            phash=str(h),
            samples=[sample_path],
            first_seen=source,
        )
        self.entries.append(entry)
        self.save()
        return entry, 0, True

    def _save_sample(self, bgr_crop: np.ndarray, tile_id: str, sample_idx: int) -> str:
        self.samples_dir.mkdir(parents=True, exist_ok=True)
        path = self.samples_dir / f"{tile_id}_{sample_idx:02d}.jpg"
        cv2.imwrite(str(path), bgr_crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return str(path.relative_to(self.root.parent))
