"""Stage: parts.json -> rig.json

Turns a flat list of extracted parts into a bone hierarchy, slots, and
attachments. The output is a plain, hand-editable JSON file -- that is the
whole point: an agent writes a first draft, a human nudges the numbers, and
``build`` turns whatever is on disk into a Spine project.

The heuristic here is intentionally dumb and predictable. Bone placement is
derived from each part's position in the source image, so the result lines up
with the artwork without any model call.
"""

from __future__ import annotations

import json
import os
from typing import Any


def _load_parts(parts_path: str) -> dict[str, Any]:
    with open(parts_path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not data.get("parts"):
        raise ValueError(f"{parts_path}: no parts found; run `split` first")
    return data


def _source_size(data: dict[str, Any]) -> tuple[int, int]:
    """Infer canvas size from the outermost part bounds."""
    right = max(p["box"][2] for p in data["parts"])
    bottom = max(p["box"][3] for p in data["parts"])
    return int(right), int(bottom)


def build_rig(data: dict[str, Any], name: str = "character") -> dict[str, Any]:
    """Compose the rig document. Pure function so it is easy to test."""
    width, height = _source_size(data)
    parts = sorted(data["parts"], key=lambda p: (p["center"][1], p["center"][0]))

    # The root sits at the bottom centre of the canvas, which is where Spine
    # users expect a character's feet to pivot.
    root_x = 0.0
    root_y = 0.0

    bones: list[dict[str, Any]] = [{"name": "root", "x": root_x, "y": root_y}]
    slots: list[dict[str, Any]] = []
    attachments: dict[str, dict[str, Any]] = {}

    # Vertical stack: each part's bone hangs off whatever part was closest
    # above it. Crude, but it produces a usable parent chain for the common
    # "discrete parts" case and never invents a cycle.
    previous_name: str | None = None

    for index, part in enumerate(parts):
        bone_name = part["name"]
        parent = previous_name or "root"

        center_x, center_y = part["center"]
        if previous_name is None:
            # First (topmost) part anchors directly under root in absolute-ish
            # terms: Spine coordinates grow upward, so flip the image axis.
            rel_x = center_x - width / 2
            rel_y = height - center_y
        else:
            parent_part = next(p for p in parts if p["name"] == previous_name)
            p_x, p_y = parent_part["center"]
            rel_x = center_x - p_x
            rel_y = -(center_y - p_y)

        bones.append(
            {
                "name": bone_name,
                "parent": parent,
                "x": round(rel_x, 2),
                "y": round(rel_y, 2),
                "length": round(max(part["width"], part["height"]) * 0.5, 2),
            }
        )

        slots.append({"name": bone_name, "bone": bone_name, "attachment": bone_name})
        attachments[bone_name] = {
            "width": part["width"],
            "height": part["height"],
            # Centre the image on its bone so rotation looks right.
            "x": round(-part["width"] / 2, 2),
            "y": round(-part["height"] / 2, 2),
        }
        previous_name = bone_name

    return {
        "skeleton": {
            "name": name,
            "width": width,
            "height": height,
            "images": "./images/",
        },
        "bones": bones,
        "slots": slots,
        "attachments": attachments,
        "source_parts": [p["image"] for p in parts],
    }


def run(parts_path: str, out_path: str, name: str = "character") -> dict[str, Any]:
    data = _load_parts(parts_path)
    rig = build_rig(data, name=name)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(rig, handle, indent=2, ensure_ascii=False)

    return {
        "bones": len(rig["bones"]),
        "slots": len(rig["slots"]),
        "rig": out_path,
    }
