"""Image helpers: read part metadata and pack an atlas."""

from __future__ import annotations

import os
from typing import Any

from PIL import Image


def image_size(path: str) -> tuple[int, int]:
    with Image.open(path) as img:
        return img.size


def pack_atlas(
    entries: list[dict[str, Any]],
    atlas_path: str,
    page_path: str,
    page_name: str,
    padding: int = 2,
) -> dict[str, Any]:
    """Pack part images into one atlas page.

    ``entries`` each need ``name`` and ``path``. The simplest layout that stays
    correct is a vertical stack: predictable, debuggable, and good enough while
    the rig is a prototype. Rotation and irregular packing are deliberately out
    of scope.
    """
    if not entries:
        raise ValueError("cannot pack an atlas with no entries")

    images = []
    total_height = padding
    max_width = 0
    for entry in entries:
        img = Image.open(entry["path"]).convert("RGBA")
        images.append((entry["name"], img))
        total_height += img.height + padding
        max_width = max(max_width, img.width)

    if max_width == 0:
        raise ValueError("atlas page would have zero width")

    page = Image.new("RGBA", (max_width, total_height), (0, 0, 0, 0))
    regions: dict[str, Any] = {}

    cursor = padding
    for name, img in images:
        page.paste(img, (0, cursor))
        regions[name] = {
            "bounds": (0, cursor, img.width, img.height),
            "offsets": (0, 0),
        }
        cursor += img.height + padding

    os.makedirs(os.path.dirname(os.path.abspath(page_path)) or ".", exist_ok=True)
    page.save(page_path)

    lines = [page_name, f"size: {max_width},{total_height}", "format: RGBA8888", "filter: Linear,Linear", "repeat: none"]
    for name, _img in images:
        left, top, width, height = regions[name]["bounds"]
        lines.append(name)
        lines.append("  rotate: false")
        lines.append(f"  xy: {left}, {top}")
        lines.append(f"  size: {width}, {height}")
        lines.append("  orig: {0}, {1}".format(width, height))
        lines.append("  offset: 0, 0")
        lines.append("  index: -1")

    with open(atlas_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    return {"page": page_path, "width": max_width, "height": total_height, "regions": len(regions)}
