"""Stage: joint marks + joint table -> bones.json + a review image.

Input : the artwork, optionally a copy with the human's ring marks on it, and a
        joint table (JSON). Missing table? The stage still reads the marks and
        writes them out, which is what a person needs to write the table.
Output: <out>/bones.json, <out>/skeleton_panel.png, <out>/marks.json,
        <out>/marks_numbered.png

The joint table is the editable artifact, exactly like ``rig.json`` in the older
stage: an agent drafts it, a human nudges numbers (or redraws a mark), and the
panel is re-rendered. Nothing here guesses anatomy -- placement comes from the
marks, or from the table when a mark is missing.
"""

from __future__ import annotations

import os
from typing import Any

from PIL import Image

from ..rig import (
    annotate,
    default_constraints,
    load_document,
    load_marks,
    nearest_mark,
    read_marks,
    render_panel,
    save_marks,
    save_spec,
    validate,
)
from ..rig.markers import Mark
from ..rig.skeleton import Skeleton

SNAP_TOLERANCE = 12.0
"""How far a table point may be from a mark and still be snapped onto it."""


def _snap(skeleton: Skeleton, marks: list[Mark]) -> list[dict[str, Any]]:
    """Pull each joint endpoint onto the nearest mark, and report every move."""
    report: list[dict[str, Any]] = []
    for joint in skeleton.joints:
        # Anything under a pixel is a control bone: treat it as zero length.
        zero_length = joint.length < 1.0
        snapped_base, base_distance = nearest_mark(marks, *joint.base)
        if snapped_base is not None and base_distance <= SNAP_TOLERANCE:
            joint.base = (snapped_base.x, snapped_base.y)
            if base_distance > 1.0:
                report.append(
                    {
                        "joint": joint.name,
                        "end": "base",
                        "moved": round(base_distance, 1),
                        "to": [round(snapped_base.x, 1), round(snapped_base.y, 1)],
                    }
                )
        if zero_length:
            # A control / IK target has no direction: moving its tip to a different
            # mark would invent a length and quietly break the constraint.
            joint.tip = joint.base
            continue
        snapped_tip, tip_distance = nearest_mark(marks, *joint.tip)
        if snapped_tip is not None and tip_distance <= SNAP_TOLERANCE and snapped_tip is not snapped_base:
            joint.tip = (snapped_tip.x, snapped_tip.y)
            if tip_distance > 1.0:
                report.append(
                    {
                        "joint": joint.name,
                        "end": "tip",
                        "moved": round(tip_distance, 1),
                        "to": [round(snapped_tip.x, 1), round(snapped_tip.y, 1)],
                    }
                )
    return report


def run(
    image_path: str,
    out_dir: str,
    *,
    marks_path: str | None = None,
    spec_path: str | None = None,
    name: str = "character",
    snap: bool = True,
) -> dict[str, Any]:
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"artwork not found: {image_path}")

    os.makedirs(out_dir, exist_ok=True)
    with Image.open(image_path) as probe:
        width, height = probe.size

    mark_source = marks_path or image_path
    if marks_path and marks_path.endswith(".json"):
        marks = load_marks(marks_path)
    else:
        marks = read_marks(mark_source)

    marks_json = save_marks(marks, os.path.join(out_dir, "marks.json"))
    numbered = annotate(mark_source, marks, os.path.join(out_dir, "marks_numbered.png"))

    result: dict[str, Any] = {
        "marks": len(marks),
        "marks_json": marks_json,
        "marks_preview": numbered,
        "canvas": [width, height],
    }

    if not spec_path:
        # No table yet: the marks are the deliverable, and that is a valid stop.
        return result

    skeleton = Skeleton(joints=load_document(spec_path)[0], name=name)
    spec_constraints = load_document(spec_path)[1]
    snapped: list[dict[str, Any]] = _snap(skeleton, marks) if snap else []

    # Constraints: the spec's own list wins; otherwise apply the house recipe
    # (IK on feet and hands, hair trailing the head). Validation runs either way,
    # so a typo in a bone name fails here instead of inside Spine.
    constraints = spec_constraints or default_constraints(skeleton)
    problems = validate(constraints, skeleton)
    if problems:
        raise ValueError("; ".join(problems))

    bones = skeleton.spine_bones(height)
    payload = {
        "name": name,
        "space": "image pixels, y down (origin top-left)",
        "canvas": {"width": width, "height": height},
        "joints": [joint.as_dict() for joint in skeleton.joints],
        "spine_bones": bones,
        "constraints": constraints,
        "marks": [mark.as_dict() for mark in marks],
        "snapped": snapped,
    }

    import json

    bones_path = os.path.join(out_dir, "bones.json")
    with open(bones_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    save_spec(skeleton, os.path.join(out_dir, "joints.json"), constraints)

    panel = render_panel(image_path, skeleton.joints, os.path.join(out_dir, "skeleton_panel.png"))

    result.update(
        {
            "bones": len(bones),
            "constraints": len(constraints),
            "bones_json": bones_path,
            "panel": panel,
            "snapped": snapped,
        }
    )
    return result

