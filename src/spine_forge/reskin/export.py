"""Write a reskin result to disk as a Spine-loadable project.

Produces the four files the editor and the web player both need:
skeleton json, atlas text, page image, and nothing else. Deliberately dumb:
the caller decides the destination, this module only lays files out.
"""

from __future__ import annotations

import os
from typing import Any

from ..assets import atlas as atlas_io
from ..core.rig import Rig


def write_project(
    out_dir: str,
    rig: Rig,
    atlas: atlas_io.Atlas,
    page_image,
    *,
    name: str | None = None,
) -> dict[str, str]:
    """Persist a rig + atlas + page image and return the paths written."""
    os.makedirs(out_dir, exist_ok=True)
    base = name or rig.name

    json_path = os.path.join(out_dir, f"{base}.json")
    atlas_path = os.path.join(out_dir, f"{base}.atlas")

    rig.save(json_path)
    atlas_io.save(atlas, atlas_path)

    page_path = os.path.join(out_dir, atlas.pages[0].image)
    page_image.save(page_path)

    return {"json": json_path, "atlas": atlas_path, "page": page_path}
