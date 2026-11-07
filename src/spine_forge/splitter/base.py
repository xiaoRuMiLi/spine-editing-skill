"""Splitter interface.

A splitter turns ONE source image into labelled part images. It is the only
place where the "understand the picture" step lives, so implementations are
swappable: the v1 connected-component splitter, a later SAM-based one, or a
remote model call, all behind the same signature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Part:
    """One extracted body part, in source-image coordinates.

    ``box`` is (left, top, right, bottom) of the part's bounding box inside the
    ORIGINAL image, so downstream stages can rebuild the layout without
    guessing where each piece came from.
    """

    name: str
    image_path: str
    width: int
    height: int
    box: tuple[int, int, int, int]
    # Horizontal centre of the part in the source image. Used to order parts
    # left-to-right and to seed bone positions.
    center_x: float = 0.0
    center_y: float = 0.0


class Splitter(Protocol):
    """Contract every splitter implementation must satisfy."""

    def split(self, source_path: str, out_dir: str) -> list[Part]:
        """Extract parts from ``source_path`` into ``out_dir`` and describe them."""
        ...
