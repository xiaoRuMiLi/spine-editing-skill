"""Rewrite dependent geometry after a part changes size.

Replacing artwork is not a single number edit. A mesh attachment carries vertex
data; a bone carries a length and a position relative to its parent; child bones
carry offsets; and child attachments carry their own placement. Shrinking the
head without shrinking the eyes leaves the eyes floating outside the new head.

This module walks that dependency tree from the replaced part downward and
applies one uniform scale to every value that is expressed in the replaced
part's local space. Anything the walk cannot verify is reported rather than
guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.rig import Rig

# Attachment types whose ``vertices`` are local positions that scale with the
# parent's geometry. Weighted vertices (``bones`` + ``weights``) are stored as
# bone-local offsets and must NOT be scaled the same way.
POSITIONAL_MESH_KEYS = ("vertices",)
PLACEMENT_KEYS = ("x", "y")
# NOTE: ``width``/``height`` are deliberately absent from every scale list.
# They describe the mesh's local sampling box, not a position. Vertices already
# shrink with the part, so scaling the box again double-counts the change and
# slides the texture off the silhouette. The runtime also expects these to stay
# integral, so rewriting them as floats breaks parsing outright.
BONE_SCALED_KEYS = ("x", "y", "length")


@dataclass
class PropagationReport:
    """What the walk changed, and what it deliberately left alone."""

    scale: float
    bones_scaled: list[str] = field(default_factory=list)
    attachments_scaled: list[str] = field(default_factory=list)
    vertices_scaled: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scale": round(self.scale, 6),
            "bones_scaled": self.bones_scaled,
            "attachments_scaled": self.attachments_scaled,
            "vertices_scaled": self.vertices_scaled,
            "skipped": self.skipped,
        }


def _scale_entry(entry: dict[str, Any], keys: tuple[str, ...], factor: float) -> bool:
    """Multiply selected numeric keys in place. Returns True if anything changed."""
    changed = False
    for key in keys:
        value = entry.get(key)
        if isinstance(value, (int, float)):
            entry[key] = round(value * factor, 4)
            changed = True
    return changed


def _parse_vertices(vertices: list[float]) -> list[list[float]]:
    """Decode Spine's flat vertex array into per-vertex runs.

    The layout is variable-length and self-describing::

        [boneCount] [boneIndex x y weight] * boneCount   per vertex

    For an unweighted mesh every vertex is ``[0] [x y]`` -- a bone count of zero
    followed by one position. Because the stride depends on the leading count,
    slicing at a fixed interval corrupts bone indices and weights, which the
    runtime then reports as an undefined pose.

    Returns one list per vertex holding the raw run, so callers can rewrite
    positions in place and leave everything else untouched.
    """
    runs: list[list[float]] = []
    index = 0
    total = len(vertices)
    while index < total:
        count = int(vertices[index])
        if count == 0:
            run_len = 3  # [0] [x] [y]
        elif count > 0:
            run_len = 1 + count * 4  # [n] then n x (boneIndex, x, y, weight)
        else:
            # Negative counts are not part of the format; stop rather than guess.
            runs.append(vertices[index:])
            break
        if index + run_len > total:
            runs.append(vertices[index:])
            break
        runs.append(vertices[index : index + run_len])
        index += run_len
    return runs


def _scale_vertices(attachment: dict[str, Any], factor: float) -> bool:
    """Scale the POSITION values of a mesh's vertex array.

    Only ``x`` and ``y`` move. Bone indices identify which bone a vertex is
    weighted to and weights are fractions that must sum to 1; scaling either
    breaks the skin while leaving geometry unchanged. Positions are bone-local,
    so a uniform scale is exactly what a size change means for them.
    """
    vertices = attachment.get("vertices")
    if not vertices:
        return False

    changed = False
    out: list[float] = []
    for run in _parse_vertices(list(vertices)):
        count = int(run[0]) if run else 0
        if count == 0 and len(run) == 3:
            out.extend([run[0], round(run[1] * factor, 4), round(run[2] * factor, 4)])
            changed = True
            continue
        if count > 0 and len(run) == 1 + count * 4:
            rewritten = [run[0]]
            for bone in range(count):
                base = 1 + bone * 4
                rewritten.extend(
                    [
                        run[base],
                        round(run[base + 1] * factor, 4),
                        round(run[base + 2] * factor, 4),
                        run[base + 3],
                    ]
                )
            out.extend(rewritten)
            changed = True
            continue
        # Unrecognised run: keep verbatim so nothing silently shifts.
        out.extend(run)

    if changed:
        attachment["vertices"] = out
    return changed


def propagate_scale(
    rig: Rig,
    *,
    slot: str,
    bone: str,
    factor: float,
    skin: str = "default",
    include_children: bool = True,
) -> PropagationReport:
    """Apply ``factor`` to the replaced part and everything hung off it.

    ``slot`` and ``bone`` identify the replaced part. ``include_children`` governs
    whether descendants of ``bone`` are shrunk too; it should stay True for a part
    that carries sub-structure such as a head with its eyes.

    The replaced attachment itself is handled by the caller, which owns the
    incoming image; this function only touches derived geometry.
    """
    report = PropagationReport(scale=factor)

    if factor == 1.0:
        return report

    # 1. The bone the part hangs on: its offsets and its drawn length.
    bone_entry = rig.bone(bone)
    if bone_entry is None:
        report.skipped.append(f"bone not found: {bone}")
    else:
        if _scale_entry(bone_entry, BONE_SCALED_KEYS, factor):
            report.bones_scaled.append(bone)

    # 2. Descendant bones and every slot riding on them.
    targets = [bone]
    if include_children:
        targets.extend(rig.descendants(bone))

    for name in targets[1:]:
        entry = rig.bone(name)
        if entry is None:
            continue
        # Parent-relative offsets shrink; rotation is an angle and must not.
        if _scale_entry(entry, ("x", "y", "length"), factor):
            report.bones_scaled.append(name)

    # 3. Attachments on those bones.
    table = rig.attachment_table(skin)
    for target_bone in targets:
        for slot_name in rig.slots_on_bone(target_bone):
            slot_entry = rig.slot(slot_name) or {}
            # Only slots that actually display something get resized. An empty
            # slot is a hidden toggle; touching it desynchronises the slot and
            # the skin.
            if not slot_entry.get("attachment"):
                continue
            slot_map = table.get(slot_name) or {}
            for att_name, attachment in slot_map.items():
                if not isinstance(attachment, dict):
                    continue
                if target_bone == bone and slot_name == slot:
                    # The replaced part's own size is set from the image later.
                    continue
                changed_placement = _scale_entry(attachment, PLACEMENT_KEYS, factor)
                if attachment.get("vertices"):
                    if _scale_vertices(attachment, factor):
                        report.vertices_scaled.append(att_name)
                if changed_placement:
                    report.attachments_scaled.append(att_name)

    return report
