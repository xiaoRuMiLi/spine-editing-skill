"""Parse and rewrite Spine ``.atlas`` files.

An atlas is plain text in two levels: page blocks (one image file) and region
blocks packed inside them. This module keeps the parsed form structured so the
reskin pipeline can move a region without re-parsing text.

Observed 4.3 format (tab-indented attributes)::

    owl.png                 <- page block, starts at column 0
    \tsize: 1024, 1024
    \tfilter: Linear, Linear
    \tscale: 0.5
    L_eye-closed            <- region block, also at column 0
    \tbounds: 721, 342, 90, 86
    L_foot
    \tbounds: 63, 316, 64, 48
    \trotate: 90

Older exports used separate ``xy`` / ``size`` / ``orig`` / ``offset`` keys; both
shapes are accepted so an updated tool can still read an old atlas.

Indentation is the whole grammar: a non-indented line is either a page image or
a region name. A page is a non-indented line followed by page-level keys
(``size``, ``format``, ``filter``, ``repeat``, ``pma``, ``scale``); anything else
is a region.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

PAGE_KEYS = {"size", "format", "filter", "repeat", "pma", "scale"}
REGION_KEYS = {"bounds", "xy", "size", "orig", "offset", "rotate", "index", "degrees"}


@dataclass
class Region:
    """One packed image region."""

    name: str
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    rotate: int = 0
    index: int = -1
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def position(self) -> tuple[int, int]:
        return self.bounds[0], self.bounds[1]

    @property
    def size(self) -> tuple[int, int]:
        return self.bounds[2], self.bounds[3]


@dataclass
class Page:
    """One atlas page: one image file plus the regions packed into it."""

    image: str
    size: tuple[int, int] = (0, 0)
    format: str = "RGBA8888"
    filter: str = "Linear, Linear"
    repeat: str = "none"
    scale: float = 1.0
    extra: dict[str, str] = field(default_factory=dict)
    regions: list[Region] = field(default_factory=list)

    def find(self, name: str) -> Region | None:
        for region in self.regions:
            if region.name == name:
                return region
        return None


@dataclass
class Atlas:
    pages: list[Page] = field(default_factory=list)

    def find_region(self, name: str) -> tuple[Page, Region] | None:
        for page in self.pages:
            region = page.find(name)
            if region is not None:
                return page, region
        return None

    def region_names(self) -> list[str]:
        return [r.name for p in self.pages for r in p.regions]


def _ints(text: str) -> list[int]:
    return [int(part.strip()) for part in text.split(",") if part.strip()]


def _pair(text: str) -> tuple[int, int]:
    values = _ints(text)
    if len(values) < 2:
        raise ValueError(f"expected two numbers, got {text!r}")
    return values[0], values[1]


def parse(text: str) -> Atlas:
    """Parse atlas text into pages and regions."""
    atlas = Atlas()
    page: Page | None = None
    region: Region | None = None

    for raw in text.splitlines():
        if not raw.strip():
            continue

        if raw[0] not in " \t":
            # Column 0: either a page image or a region name. Peek ahead is not
            # needed because page keys arrive indented under the page line.
            name = raw.strip()
            # Decide by looking at whether the previous page already has regions
            # or page attributes. A new page starts when the name looks like an
            # image file, otherwise it is a region of the current page.
            if page is None or name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                page = Page(image=name)
                atlas.pages.append(page)
                region = None
            else:
                region = Region(name=name)
                page.regions.append(region)
            continue

        key, _, value = raw.strip().partition(":")
        key = key.strip()
        value = value.strip()

        if key in PAGE_KEYS and region is None:
            if key == "size":
                page.size = _pair(value)  # type: ignore[union-attr]
            elif key == "format":
                page.format = value  # type: ignore[union-attr]
            elif key == "filter":
                page.filter = value  # type: ignore[union-attr]
            elif key == "repeat":
                page.repeat = value  # type: ignore[union-attr]
            elif key == "scale":
                page.scale = float(value)  # type: ignore[union-attr]
            else:
                page.extra[key] = value  # type: ignore[union-attr]
            continue

        if region is None:
            if page is None:
                raise ValueError(f"attribute before any page: {raw!r}")
            page.extra[key] = value
            continue

        if key == "bounds":
            values = _ints(value)
            if len(values) != 4:
                raise ValueError(f"bounds needs 4 numbers, got {value!r}")
            region.bounds = (values[0], values[1], values[2], values[3])
        elif key == "rotate":
            region.rotate = 90 if value in ("90", "true") else 0
        elif key == "index":
            region.index = int(value)
        elif key == "degrees":
            region.rotate = int(value)
        else:
            region.extra[key] = value

    return atlas


def dumps(atlas: Atlas) -> str:
    """Serialise back to atlas text, preserving unknown keys."""
    out: list[str] = []
    for page in atlas.pages:
        out.append(page.image)
        out.append(f"\tsize: {page.size[0]}, {page.size[1]}")
        out.append(f"\tformat: {page.format}")
        out.append(f"\tfilter: {page.filter}")
        out.append(f"\trepeat: {page.repeat}")
        if page.scale != 1.0:
            out.append(f"\tscale: {page.scale:g}")
        for key, value in page.extra.items():
            out.append(f"\t{key}: {value}")
        for region in page.regions:
            out.append(region.name)
            out.append(
                f"\tbounds: {region.bounds[0]}, {region.bounds[1]}, "
                f"{region.bounds[2]}, {region.bounds[3]}"
            )
            if region.rotate:
                out.append(f"\trotate: {region.rotate}")
            if region.index >= 0:
                out.append(f"\tindex: {region.index}")
            for key, value in region.extra.items():
                out.append(f"\t{key}: {value}")
    return "\n".join(out) + "\n"


def load(path: str) -> Atlas:
    with open(path, encoding="utf-8") as handle:
        return parse(handle.read())


def save(atlas: Atlas, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(dumps(atlas))
