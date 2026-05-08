"""Board region detection and tile-cell extraction.

First-pass strategy (to be validated against a real screenshot):

1. Detect the bright tile faces against the dark/green background by
   thresholding luminance + saturation. Tile faces are pale cream; background
   is dark green; ghosted/lower tiles are mid-luminance.
2. Find connected components, filter by size + aspect ratio (~1:1.25 portrait).
3. Cluster centers into rows and columns to recover an integer (row, col) grid.
4. Read stack depth at each cell from the count of partially-visible "ghost"
   tiles flanking each visible tile (left/right edge strips show up as darker
   bands).
5. Detect the tray region (vine-bordered rectangle near the bottom) and slice
   it into 7 slots.

Nothing here is implemented yet — we want to look at a real screenshot first.
"""

from dataclasses import dataclass


@dataclass
class TileCell:
    row: int
    col: int
    stack_depth: int  # how many tiles below this one
    bbox: tuple[int, int, int, int]  # (x, y, w, h) in screenshot pixels
    tile_id: str  # assigned by the tile fingerprint library


@dataclass
class BoardState:
    level: int
    cells: list[TileCell]
    tray: list[str]  # tile_ids currently in the 7-slot tray (length <= 7)
    queues: list[list[str]]  # for levels with side-feeding queues; head first
