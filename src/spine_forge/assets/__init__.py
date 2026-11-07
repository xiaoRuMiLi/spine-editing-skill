"""Asset layer: atlas text, atlas pixels.

``atlas`` is pure text parsing with no image dependency, so format logic can be
tested in isolation. ``images`` owns every pixel operation.
"""

from .atlas import Atlas, Page, Region, dumps, load, parse, save
from .images import (
    append_to_page,
    cut_region,
    grow_page,
    load_page_image,
    next_free_y,
    save_page_image,
)
from .matting import remove_background

__all__ = [
    "Atlas",
    "Page",
    "Region",
    "load",
    "parse",
    "dumps",
    "save",
    "append_to_page",
    "cut_region",
    "grow_page",
    "load_page_image",
    "next_free_y",
    "save_page_image",
    "remove_background",
]
