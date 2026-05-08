"""Extract a board state from a screenshot.

Usage:
    python scripts/extract_board.py data/screenshots/foo.png

Right now this only loads the image and prints its dimensions — a sanity check
that the deps are installed and the path resolution works. The real extraction
logic lands once we've validated the approach against a concrete screenshot.
"""

from pathlib import Path

import click
from PIL import Image


@click.command()
@click.argument("image_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def main(image_path: Path) -> None:
    img = Image.open(image_path)
    click.echo(f"Loaded {image_path.name}: {img.size[0]}x{img.size[1]} {img.mode}")
    click.echo("(extraction not implemented yet — scaffold only)")


if __name__ == "__main__":
    main()
