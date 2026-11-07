"""Stage: rig.json -> a Spine project on disk.

Outputs skeleton.json, an atlas page PNG, skeleton.atlas, and copies the part
images into images/. The skeleton.json is the file you open in the Spine editor.
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any

from ..core import Bone, RegionAttachment, Skeleton, Slot, to_spine_json
from ..io import pack_atlas


def load_rig(rig_path: str) -> dict[str, Any]:
    with open(rig_path, encoding="utf-8") as handle:
        return json.load(handle)


def rig_to_skeleton(rig: dict[str, Any], images_dir: str) -> Skeleton:
    """Translate the editable rig.json document into the core model."""
    meta = rig.get("skeleton", {})
    skeleton = Skeleton(
        name=meta.get("name", "character"),
        width=int(meta.get("width", 400)),
        height=int(meta.get("height", 600)),
        images=meta.get("images", "./images/"),
    )

    for entry in rig.get("bones", []):
        skeleton.add_bone(
            Bone(
                name=entry["name"],
                parent=entry.get("parent"),
                x=float(entry.get("x", 0.0)),
                y=float(entry.get("y", 0.0)),
                rotation=float(entry.get("rotation", 0.0)),
                length=float(entry.get("length", 0.0)),
            )
        )

    for entry in rig.get("slots", []):
        skeleton.add_slot(
            Slot(
                name=entry["name"],
                bone=entry["bone"],
                attachment=entry.get("attachment") or entry["name"],
            )
        )

    for name, entry in rig.get("attachments", {}).items():
        skeleton.add_attachment(
            RegionAttachment(
                name=name,
                width=float(entry["width"]),
                height=float(entry["height"]),
                x=float(entry.get("x", 0.0)),
                y=float(entry.get("y", 0.0)),
            )
        )

    # Images are resolved relative to rig.json's own directory so a rig can be
    # edited and rebuilt from anywhere.
    base = os.path.dirname(os.path.abspath(rig_path_holder[0]))
    for source in rig.get("source_parts", []):
        src = os.path.join(base, source)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(images_dir, os.path.basename(src)))

    return skeleton


# `rig_to_skeleton` needs rig.json's directory to resolve relative image paths;
# a module-level holder keeps the signature simple. Set it in `run`.
rig_path_holder: list[str] = [""]


def run(rig_path: str, out_dir: str) -> dict[str, Any]:
    rig_path_holder[0] = rig_path
    rig = load_rig(rig_path)

    images_dir = os.path.join(out_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    skeleton = rig_to_skeleton(rig, images_dir)
    doc = to_spine_json(skeleton)

    skeleton_path = os.path.join(out_dir, "skeleton.json")
    with open(skeleton_path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2, ensure_ascii=False)

    name = skeleton.name
    atlas_info = pack_atlas(
        [{"name": att.name, "path": os.path.join(images_dir, att.name + ".png")}
         for att in skeleton.attachments.values()
         if os.path.isfile(os.path.join(images_dir, att.name + ".png"))],
        atlas_path=os.path.join(out_dir, f"{name}.atlas"),
        page_path=os.path.join(out_dir, f"{name}.png"),
        page_name=f"{name}.png",
    )

    return {
        "skeleton": skeleton_path,
        "atlas": os.path.join(out_dir, f"{name}.atlas"),
        "page": atlas_info["page"],
        "bones": len(skeleton.bones),
        "slots": len(skeleton.slots),
    }
