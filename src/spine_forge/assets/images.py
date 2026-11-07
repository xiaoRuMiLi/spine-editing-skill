"""Image side of an atlas: read the page, cut out regions, and rebuild pages.

Kept separate from ``atlas.py`` on purpose: that module is pure text parsing with
no image dependency, so atlas logic can be tested without Pillow. This one owns
every pixel operation.
"""

from __future__ import annotations

import os

from PIL import Image

from .atlas import Atlas, Page, Region


def load_page_image(atlas_path: str, page: Page) -> Image.Image:
    """Open the image for ``page``, resolved next to the atlas file."""
    base = os.path.dirname(os.path.abspath(atlas_path))
    path = os.path.join(base, page.image)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"atlas page image not found: {path}")
    return Image.open(path).convert("RGBA")


def cut_region(image: Image.Image, region: Region) -> Image.Image:
    """Extract one region from a page image.

    A rotated region is stored rotated on 90 degree boundaries; a ``rotate`` of
    90 means the packed pixels were turned clockwise, so undo that here.
    """
    x, y, w, h = region.bounds
    if region.rotate:
        # Packed size is swapped relative to the original for a 90 degree turn.
        box = (x, y, x + h, y + w)
        crop = image.crop(box)
        return crop.rotate(-region.rotate, expand=True)
    return image.crop((x, y, x + w, y + h))


def next_free_y(page: Page) -> int:
    """Lowest y coordinate not occupied by any region on the page.

    Regions are packed top-left downward in these exports, so appending below the
    existing content is safe and keeps every existing bounds untouched.
    """
    bottom = 0
    for region in page.regions:
        _, y, _, h = region.bounds
        bottom = max(bottom, y + h)
    return bottom


def append_to_page(
    page_image: Image.Image,
    page: Page,
    name: str,
    sprite: Image.Image,
    padding: int = 2,
    x: int = 0,
) -> Region:
    """Place ``sprite`` below existing content and return the new region.

    ``x`` requests a horizontal offset and is used to keep the new art's opaque
    box aligned with the old one it replaces: appending flush at x=0 shifts the
    subject sideways whenever the two images carry different transparent margins,
    which shows up as a few pixels of drift between the original and the reskin.
    The paste position is returned in ``Region.bounds`` so the caller can compute
    exactly where the art landed.

    The page image must be tall enough already; callers grow it with
    ``grow_page`` first. Existing region bounds are never modified, which is what
    keeps every untouched attachment rendering exactly as before.
    """
    y = next_free_y(page) + padding
    width, height = sprite.size
    if width > page_image.width:
        raise ValueError(
            f"sprite {name!r} is {width}px wide, wider than the {page_image.width}px page"
        )
    if x < 0 or x + width > page_image.width:
        raise ValueError(
            f"sprite {name!r} at x={x} would span {x}..{x + width}, "
            f"outside the {page_image.width}px page"
        )
    if y + height > page_image.height:
        raise ValueError(
            f"sprite {name!r} needs y={y}..{y + height} but page height is {page_image.height}"
        )

    if sprite.mode != "RGBA":
        sprite = sprite.convert("RGBA")
    page_image.paste(sprite, (x, y))

    region = Region(name=name, bounds=(x, y, width, height))
    page.regions.append(region)
    return region


def grow_page(page_image: Image.Image, page: Page, extra_height: int, page_size: tuple[int, int]) -> Image.Image:
    """Return a taller page image and record the new size on ``page``.

    Spine requires power-of-two page dimensions for reliable filtering, so the
    new height is rounded up to the next power of two rather than fitted exactly.
    """
    needed = page_image.height + extra_height
    height = 1
    while height < needed:
        height *= 2
    width = page_image.width

    grown = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    grown.paste(page_image, (0, 0))
    page.size = (width, height)
    return grown


def save_page_image(image: Image.Image, atlas_path: str, page: Page) -> str:
    base = os.path.dirname(os.path.abspath(atlas_path))
    path = os.path.join(base, page.image)
    image.save(path)
    return path
