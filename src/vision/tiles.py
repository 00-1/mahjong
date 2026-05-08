"""Tile fingerprint library.

Each unique tile art is stored once with:
- a perceptual hash (pHash) for fast lookup
- a saved crop for human inspection / labeling
- an auto-assigned ID (tile_001, tile_002, ...)
- an optional human-readable label added later

Lookup: hash a new tile crop, find the closest entry within a hamming-distance
threshold; if nothing's close enough, register it as a new tile.

Not implemented yet — pending validation against a real screenshot.
"""

from dataclasses import dataclass, field


@dataclass
class TileEntry:
    tile_id: str
    phash: str  # hex string from imagehash
    label: str | None = None  # human-friendly name, e.g. "pink_daisy"
    examples: list[str] = field(default_factory=list)  # paths to crop images
