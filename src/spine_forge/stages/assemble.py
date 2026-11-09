"""Stage: parts + skeleton -> a Spine project (skeleton.json + atlas + page).

This is the step that puts the artwork ON the bones. Each part becomes one slot
with one region attachment, and the attachment is placed so the art lands exactly
where it was in the source picture.

Three conversions are unavoidable here, and each of them silently ruins the
result if skipped:

1. **Space.** Parts are measured in image pixels (y DOWN). Spine is y UP. The flip
   happens once, when world positions are derived, and nowhere else.
2. **Bone frame.** A bone is rotated; an attachment offset written in that bone's
   frame therefore arrives rotated. The art must stay upright on screen, so the
   attachment carries ``rotation = -bone_world_rotation`` and its offset is the
   inverse-rotated displacement.
3. **Packing.** Region bounds in the atlas are page pixels at the page's ``scale``.
   We pack at full resolution (scale 1) to keep this step free of half-pixel
   surprises; a page scale other than 1 is applied by the editor later.

Draw order is explicit, not alphabetical: back layers first, then the pieces that
overlap them. Slots are emitted in that order because slot order IS z order.

Limbs that must bend (legs) can instead be emitted as ONE weighted mesh
(``warp="legs"``): the halves produced by the knee cut are re-merged into the
original artwork and skinned across the two bones, so the knee bends by warping
the texture rather than by swinging two rigid pieces. See ``rig/mesh.py``.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any

import numpy as np
from PIL import Image

from ..rig.mesh import bone_world_frames, build_warp_mesh

# Part names come from the colour splitter (``leg-left`` means the CHARACTER's
# left leg); bones use underscores. The mapping is explicit so a rename in one
# stage can never silently bind a limb to the wrong bone.
PART_BINDING: dict[str, tuple[str, int]] = {
    "leg-right-up": ("leg_r", 10),
    "leg-right-down": ("shin_r", 11),
    "foot-right": ("foot_r", 12),
    "leg-left-up": ("leg_l", 13),
    "leg-left-down": ("shin_l", 14),
    "foot-left": ("foot_l", 15),
    "shorts": ("hips", 20),
    "hair": ("hair", 25),
    "shirt": ("chest", 30),
    "arm-right": ("fore_r", 35),
    "head": ("head", 40),
    "accent": ("head", 45),
    "arm-left": ("fore_l", 50),
}

# Limbs to bend as one weighted mesh instead of two rigid halves:
#   merged slot -> (upper bone, lower bone, the cut halves it is assembled from)
WARP_LIMBS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "leg-right": ("leg_r", "shin_r", ("leg-right-up", "leg-right-down")),
    "leg-left": ("leg_l", "shin_l", ("leg-left-up", "leg-left-down")),
}

PAGE_PADDING = 2


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _bone_world(joint: dict[str, Any]) -> tuple[float, float, float]:
    """Bone base in Spine world space (y up) and its world rotation in degrees."""
    bx = float(joint["base"][0])
    by = float(joint["base"][1])
    tx = float(joint["tip"][0])
    ty = float(joint["tip"][1])
    return bx, by, math.degrees(math.atan2(-(ty - by), tx - bx))


def _pack(regions: list[tuple[str, Image.Image]], width_hint: int):
    """Shelf pack: tallest first, left to right, wrapping at the hint width."""
    ordered = sorted(regions, key=lambda item: -item[1].height)
    width = max(width_hint, max(image.width for _, image in ordered) + 2 * PAGE_PADDING)
    placed: list[tuple[str, Image.Image, int, int]] = []
    x = PAGE_PADDING
    y = PAGE_PADDING
    shelf_height = 0
    for name, image in ordered:
        if x + image.width + PAGE_PADDING > width:
            x = PAGE_PADDING
            y += shelf_height + PAGE_PADDING
            shelf_height = 0
        placed.append((name, image, x, y))
        x += image.width + PAGE_PADDING
        shelf_height = max(shelf_height, image.height)
    height = y + shelf_height + PAGE_PADDING
    power = 1
    while power < height:
        power *= 2
    return placed, width, power


def merge_halves(images: list[Image.Image]) -> Image.Image:
    """Re-join pieces cut from one drawing, pixel for pixel.

    The knee cut split the leg's alpha channel along a line with a one-pixel
    feather, so the halves overlap slightly. At every pixel both halves carry the
    SAME colour (they came from the same source); only their alpha differs. Taking
    whichever half is more opaque therefore restores the original exactly, while
    ``Image.alpha_composite`` would push the overlap over 1.0 and leave a seam.
    """
    if not images:
        raise ValueError("merge_halves needs at least one image")
    if len(images) == 1:
        return images[0]
    sizes = {image.size for image in images}
    if len(sizes) != 1:
        raise ValueError(f"cannot merge halves of different sizes: {sorted(sizes)}")

    merged = np.array(images[0].convert("RGBA"), dtype=np.uint8)
    for image in images[1:]:
        other = np.array(image.convert("RGBA"), dtype=np.uint8)
        pick = other[:, :, 3] > merged[:, :, 3]
        merged[pick] = other[pick]
    return Image.fromarray(merged, mode="RGBA")


def alpha_box(image: Image.Image) -> list[int]:
    """Tight (left, top, right, bottom) around the non-transparent pixels."""
    alpha = np.asarray(image.convert("RGBA"))[:, :, 3]
    ys, xs = np.nonzero(alpha)
    if len(xs) == 0:
        raise ValueError("part image is fully transparent")
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def grid_for(width: int, height: int) -> tuple[int, int]:
    """Mesh resolution: ~12 px cells, clamped to a sane range."""
    cols = max(3, min(10, int(round(width / 12)) + 1))
    rows = max(4, min(20, int(round(height / 12)) + 1))
    return cols, rows


def run(
    parts_path: str,
    bones_path: str,
    out_dir: str,
    *,
    name: str | None = None,
    mode: str = "atlas",
    warp: str = "none",
) -> dict[str, Any]:
    """Write a Spine project.

    ``mode="atlas"`` packs every part into one page plus a ``.atlas`` (what the
    web runtime wants). ``mode="images"`` writes one PNG per part and points the
    skeleton at ``./images/`` instead; the Spine editor loads that without any
    atlas, which is what a machine that cannot read our atlas needs.

    ``warp="legs"`` replaces the cut leg halves with one weighted mesh per leg.
    """
    if mode not in ("atlas", "images"):
        raise ValueError(f"unknown mode: {mode!r}")
    warp = (warp or "none").lower()
    if warp not in ("none", "legs"):
        raise ValueError(f"unknown warp mode: {warp!r}")
    parts_doc = _load(parts_path)
    rig = _load(bones_path)

    skeleton_name = name or rig.get("name") or "character"
    canvas = rig["canvas"]
    canvas_w, canvas_h = int(canvas["width"]), int(canvas["height"])

    joints = {joint["name"]: joint for joint in rig["joints"]}
    world = {joint_name: _bone_world(joint) for joint_name, joint in joints.items()}
    frames = bone_world_frames(rig["spine_bones"])
    bone_names = [bone["name"] for bone in rig["spine_bones"]]

    warped = WARP_LIMBS if warp == "legs" else {}
    cut_parts = {half for _, _, halves in warped.values() for half in halves}

    by_name = {part["name"]: part for part in parts_doc["parts"]}
    missing = [part for part in PART_BINDING if part not in by_name and part not in cut_parts]
    if missing:
        raise ValueError(f"parts.json is missing: {missing}")

    os.makedirs(out_dir, exist_ok=True)
    images_dir = os.path.join(out_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    parts_dir = os.path.dirname(os.path.abspath(parts_path))

    regions: list[tuple[str, Image.Image]] = []
    placements: list[dict[str, Any]] = []

    for part_name, (bone_name, order) in PART_BINDING.items():
        if part_name in cut_parts:
            continue
        part = by_name[part_name]
        if bone_name not in joints:
            raise ValueError(f"part {part_name!r} is bound to unknown bone {bone_name!r}")

        left, top, right, bottom = part["box"]
        box_image = (
            Image.open(os.path.join(parts_dir, part["image"]))
            .convert("RGBA")
            .crop((left, top, right, bottom))
        )
        regions.append((part_name, box_image))

        bx, by, bone_rotation = world[bone_name]
        # Part centre in Spine world space (y up).
        centre_x = (left + right) / 2.0
        centre_y = (top + bottom) / 2.0
        offset_x = centre_x - bx
        offset_y = -(centre_y - by)

        radians = math.radians(-bone_rotation)
        local_x = offset_x * math.cos(radians) - offset_y * math.sin(radians)
        local_y = offset_x * math.sin(radians) + offset_y * math.cos(radians)

        placements.append(
            {
                "slot": part_name,
                "bone": bone_name,
                "order": order,
                "x": round(local_x, 3),
                "y": round(local_y, 3),
                "rotation": round(-bone_rotation, 3),
                "width": box_image.width,
                "height": box_image.height,
            }
        )

    # --- weighted-mesh limbs ------------------------------------------------
    for slot_name, (upper, lower, halves) in warped.items():
        absent = [half for half in halves if half not in by_name]
        if absent:
            raise ValueError(
                f"warp={warp!r} needs the cut halves {list(halves)}; missing {absent}"
            )
        if lower not in joints or upper not in joints:
            raise ValueError(f"warp slot {slot_name!r} references unknown bones")

        whole = merge_halves(
            [
                Image.open(os.path.join(parts_dir, by_name[half]["image"])).convert("RGBA")
                for half in halves
            ]
        )
        left, top, right, bottom = alpha_box(whole)
        crop = whole.crop((left, top, right, bottom))

        # The joint is where the two bones meet: the lower bone's base.
        knee = joints[lower]["base"]
        chain = [
            joints[upper]["base"],
            knee,
            joints[lower]["tip"],
        ]
        cols, rows = grid_for(crop.width, crop.height)
        mesh = build_warp_mesh(
            box=[left, top, right, bottom],
            frames=frames,
            bone_names=bone_names,
            upper=upper,
            lower=lower,
            chain=[(float(p[0]), float(p[1])) for p in chain],
            canvas_height=float(canvas_h),
            cols=cols,
            rows=rows,
        )
        regions.append((slot_name, crop))
        placements.append(
            {
                "slot": slot_name,
                "bone": upper,
                "order": PART_BINDING[halves[0]][1],
                "width": crop.width,
                "height": crop.height,
                "mesh": mesh,
                "grid": [cols, rows],
            }
        )

    page_path: str | None = None
    atlas_path: str | None = None
    page_size: list[int] = [0, 0]

    if mode == "images":
        # One file per part, named after the attachment. The skeleton then carries
        # ``"images": "./images/"`` and needs no atlas at all.
        for stale in os.listdir(images_dir):
            if stale.endswith(".png"):
                os.remove(os.path.join(images_dir, stale))
        for region_name, image in regions:
            image.save(os.path.join(images_dir, f"{region_name}.png"))
    else:
        placed, page_width, page_height = _pack(regions, canvas_w)
        page = Image.new("RGBA", (page_width, page_height), (0, 0, 0, 0))
        atlas_entries: list[str] = []
        for region_name, image, x, y in placed:
            page.paste(image, (x, y))
            atlas_entries.append(
                f"{region_name}\n\tbounds: {x}, {y}, {image.width}, {image.height}"
            )

        page_name = f"{skeleton_name}.png"
        # The atlas page line resolves relative to the ATLAS file, so the page must
        # sit next to it. A subdirectory here is the classic "image not found at
        # runtime" that looks like a broken export.
        page_path = os.path.join(out_dir, page_name)
        page.save(page_path)
        atlas_path = os.path.join(out_dir, f"{skeleton_name}.atlas")
        with open(atlas_path, "w", encoding="utf-8") as handle:
            handle.write(f"{page_name}\n")
            handle.write(f"\tsize: {page_width}, {page_height}\n")
            handle.write("\tformat: RGBA8888\n")
            handle.write("\tfilter: Linear, Linear\n")
            handle.write("\trepeat: none\n")
            handle.write("\n".join(atlas_entries) + "\n")
        page_size = [page_width, page_height]

    # --- skeleton.json -----------------------------------------------------
    bones_json = [
        {
            "name": bone["name"],
            **({"parent": bone["parent"]} if bone["parent"] else {}),
            "x": bone["x"],
            "y": bone["y"],
            "rotation": bone["rotation"],
            "length": bone["length"],
        }
        for bone in rig["spine_bones"]
    ]

    placements.sort(key=lambda entry: entry["order"])
    slots_json = [{"name": p["slot"], "bone": p["bone"], "attachment": p["slot"]} for p in placements]
    attachments: dict[str, dict[str, Any]] = {}
    for p in placements:
        if "mesh" in p:
            # Weighted meshes carry their own world placement in the vertex data,
            # so x/y/rotation stay out of the attachment.
            attachments[p["slot"]] = {p["slot"]: p["mesh"]}
        else:
            attachments[p["slot"]] = {
                p["slot"]: {
                    "x": p["x"],
                    "y": p["y"],
                    "rotation": p["rotation"],
                    "width": p["width"],
                    "height": p["height"],
                }
            }

    document = {
        "skeleton": {
            "hash": "girl-draft",
            "spine": "4.3.75",
            "x": -canvas_w / 2.0,
            "y": 0,
            "width": canvas_w,
            "height": canvas_h,
            **({"images": "./images/"} if mode == "images" else {}),
        },
        "bones": bones_json,
        "slots": slots_json,
        "skins": [{"name": "default", "attachments": attachments}],
        "constraints": rig.get("constraints", []),
    }

    skeleton_path = os.path.join(out_dir, f"{skeleton_name}.json")
    with open(skeleton_path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)

    result: dict[str, Any] = {
        "mode": mode,
        "warp": warp,
        "skeleton": skeleton_path,
        "slots": len(slots_json),
        "bones": len(bones_json),
        "constraints": len(document["constraints"]),
    }
    if warp == "legs":
        result["meshes"] = {
            p["slot"]: {
                "grid": p["grid"],
                "vertices": len(p["mesh"]["uvs"]) // 2,
                "triangles": len(p["mesh"]["triangles"]) // 3,
            }
            for p in placements
            if "mesh" in p
        }
    if mode == "images":
        result["images"] = images_dir
    else:
        result["atlas"] = atlas_path
        result["page"] = page_path
        result["page_size"] = page_size
    return result
