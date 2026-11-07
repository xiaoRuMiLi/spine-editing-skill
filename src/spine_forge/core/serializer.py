"""Serialize a rig into Spine 4.2 JSON.

This is the single place where Spine wire-format knowledge lives. Four details
are easy to get wrong and fail *silently* in the runtime, so they are handled
explicitly here:

1. Rotations use ``value``, not ``angle``. A 4.x runtime reading ``angle`` sees
   a rotation of 0 and the animation appears to do nothing.

2. Bezier curves are stored PER ANIMATED PROPERTY, not per keyframe. ``rotate``
   animates one property and needs 4 numbers, but ``translate``/``scale``/
   ``shear`` animate two (x and y) and need 8. Supplying only 4 makes the
   runtime index past the array, read undefined, and spread NaN through the
   bone transforms until the skeleton fails to rasterize at all.

3. Control points are ABSOLUTE, in the same units as ``time`` and ``value`` --
   not normalized to the segment. Normalized points land outside the segment
   they belong to and the interpolation lurches.

4. A keyframe's curve governs the segment that STARTS at it, while authors
   naturally attach curves to the frame they END at. Curves therefore shift
   one frame earlier.

Pure JSON in and out. No third-party imports.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .model import RegionAttachment, Skeleton

SPINE_VERSION = "4.2.0"

# Timeline type -> the properties it animates and their default values.
# The defaults matter: they are what the bezier conversion subtracts from, so
# scale must default to 1.0, not 0.0.
TIMELINE_PROPERTIES: dict[str, tuple[tuple[str, float], ...]] = {
    "rotate": (("value", 0.0),),
    "translate": (("x", 0.0), ("y", 0.0)),
    "scale": (("x", 1.0), ("y", 1.0)),
    "shear": (("x", 0.0), ("y", 0.0)),
    "translatex": (("value", 0.0),),
    "translatey": (("value", 0.0),),
    "scalex": (("value", 1.0),),
    "scaley": (("value", 1.0),),
    "shearx": (("value", 0.0),),
    "sheary": (("value", 0.0),),
}


def skeleton_hash(rig: Skeleton) -> str:
    """Stable content hash used by Spine to detect stale editor data."""
    payload = {
        "name": rig.name,
        "width": rig.width,
        "height": rig.height,
        "bones": [[b.name, b.parent] for b in rig.bones],
        "slots": [[s.name, s.bone] for s in rig.slots],
        "attachments": sorted(rig.attachments),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.md5(blob).hexdigest()[:20]


def _bone_dict(bone) -> dict[str, Any]:
    out: dict[str, Any] = {"name": bone.name}
    if bone.parent:
        out["parent"] = bone.parent
    if bone.length:
        out["length"] = round(bone.length, 3)
    if bone.x:
        out["x"] = round(bone.x, 3)
    if bone.y:
        out["y"] = round(bone.y, 3)
    if bone.rotation:
        out["rotation"] = round(bone.rotation, 3)
    return out


def _slot_dict(slot) -> dict[str, Any]:
    return {"name": slot.name, "bone": slot.bone, "attachment": slot.attachment}


def _attachment_dict(att: RegionAttachment) -> dict[str, Any]:
    # Region attachments need width/height; x/y offset it from the bone origin.
    # Scaling the image to the attachment size is what makes the region land
    # on the right pixels, so these must match the source PNG dimensions.
    out: dict[str, Any] = {
        "width": round(att.width, 3),
        "height": round(att.height, 3),
    }
    if att.x:
        out["x"] = round(att.x, 3)
    if att.y:
        out["y"] = round(att.y, 3)
    return out


def _convert_timeline(kind: str, frames: list[dict[str, Any]]) -> None:
    """Rewrite one authored timeline into Spine 4.2 wire format, in place.

    Input frames are authored with the friendlier shorthand: ``angle`` for
    rotation and a normalized 4-number ``curve`` attached to the END of the
    segment it describes. Output matches the runtime's expectations: ``value``,
    one absolute bezier parameter set per animated property, and the curve
    moved to the START of its segment.
    """
    properties = TIMELINE_PROPERTIES.get(kind)
    if not properties or len(frames) < 2:
        return

    if kind == "rotate":
        for frame in frames:
            if "angle" in frame:
                frame["value"] = frame.pop("angle")

    authored = [frame.pop("curve", None) for frame in frames]

    for i in range(len(frames) - 1):
        curve = authored[i + 1]
        if curve is None:
            continue
        if curve == "stepped":
            frames[i]["curve"] = "stepped"
            continue
        if not isinstance(curve, list) or len(curve) < 4:
            raise ValueError(
                f"timeline {kind!r} frame {i}: curve must be a 4-number list or 'stepped'"
            )

        cx1, cy1, cx2, cy2 = curve[:4]
        time1 = frames[i]["time"]
        span = frames[i + 1]["time"] - time1

        absolute: list[float] = []
        for name, default in properties:
            value1 = frames[i].get(name, default)
            value2 = frames[i + 1].get(name, default)
            delta = value2 - value1
            absolute.extend(
                [
                    round(time1 + span * cx1, 6),
                    round(value1 + delta * cy1, 6),
                    round(time1 + span * cx2, 6),
                    round(value1 + delta * cy2, 6),
                ]
            )
        frames[i]["curve"] = absolute


def to_spine_json(rig: Skeleton) -> dict[str, Any]:
    """Build the complete Spine 4.2 JSON document for a rig."""
    problems = rig.validate()
    if problems:
        raise ValueError("invalid rig:\n  " + "\n  ".join(problems))

    # Spine's setup pose comes from the "bones" array, not from the skeleton
    # metadata. The editor derives the displayed skeleton name from
    # ``skeleton.name`` when present, so it is emitted here.

    for key, animation in rig.animations.items():
        for bone_timelines in (animation.get("bones") or {}).values():
            for kind, frames in bone_timelines.items():
                _convert_timeline(kind, frames)

    # Sketch of the document. Empty collections are emitted so the editor does
    # not show a broken tree when nothing was authored yet.
    doc: dict[str, Any] = {
        "skeleton": {
            "hash": skeleton_hash(rig),
            "name": rig.name,
            "spine": SPINE_VERSION,
            # Spine's origin sits at the horizontal centre, so a rig exported
            # from an image of width W must shift left by W/2.
            "x": -(rig.width // 2),
            "y": 0,
            "width": rig.width,
            "height": rig.height,
            "images": rig.images,
        },
        "bones": [_bone_dict(b) for b in rig.bones],
        "slots": [_slot_dict(s) for s in rig.slots],
        "skins": [
            {
                "name": "default",
                # Outer key is the slot name, inner key is the attachment name.
                "attachments": {
                    slot.name: {slot.attachment: _attachment_dict(rig.attachments[slot.attachment])}
                    for slot in rig.slots
                    if slot.attachment in rig.attachments
                },
            }
        ],
        "animations": rig.animations,
    }
    return doc


def dumps(rig: Skeleton, indent: int = 2) -> str:
    return json.dumps(to_spine_json(rig), indent=indent, ensure_ascii=False)
