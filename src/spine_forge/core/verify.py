"""Check a built Spine document before it reaches the editor or the runtime.

Every bug this project has hit in the wire format failed *silently*: a wrong UV
convention paints a solid rectangle, a wrong weight frame throws the leg across
the canvas, a bad triangle index draws nothing. None of them raise. So the cheap
insurance is a structural check that runs after building and says "this document
cannot be drawn the way it is written" -- before a person has to spot it in a
screenshot.

Zero dependencies on purpose: pure dict/JSON inspection, so it can run in tests
and in CI without Pillow or numpy.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

MAX_BONES_PER_VERTEX = 4
WEIGHT_SUM_TOLERANCE = 0.01
MIN_UV_SPAN = 0.25
"""A mesh covers its image rect, so its UVs span ~1.0. Far less means the writer
used page coordinates (the bug that painted the legs as solid rectangles)."""


def _decode_vertices(flat: list[float]) -> list[list[tuple[int, float, float, float]]]:
    """Weighted vertex layout: ``boneCount`` then ``(boneIndex, x, y, weight)`` each."""
    out: list[list[tuple[int, float, float, float]]] = []
    i = 0
    while i < len(flat):
        count = int(flat[i])
        i += 1
        entries: list[tuple[int, float, float, float]] = []
        for _ in range(count):
            if i + 3 >= len(flat) + 1:
                raise ValueError("vertex data ends in the middle of a bone entry")
            entries.append((int(flat[i]), float(flat[i + 1]), float(flat[i + 2]), float(flat[i + 3])))
            i += 4
        out.append(entries)
    return out


def _check_mesh(
    name: str, mesh: Mapping[str, Any], bone_count: int
) -> list[str]:
    problems: list[str] = []
    uvs = mesh.get("uvs") or []
    triangles = mesh.get("triangles") or []
    vertices = mesh.get("vertices") or []

    if not uvs:
        problems.append(f"{name}: mesh has no uvs")
        return problems
    if len(uvs) % 2:
        problems.append(f"{name}: uvs length {len(uvs)} is odd (should be 2 per vertex)")

    vertex_count = len(uvs) // 2
    hull = int(mesh.get("hull") or 0)
    if hull < 0 or hull > vertex_count:
        problems.append(f"{name}: hull={hull} outside 0..{vertex_count}")

    # Region-local UVs: anything outside 0..1 means someone wrote atlas coordinates.
    if any(value < -1e-6 or value > 1 + 1e-6 for value in uvs):
        problems.append(f"{name}: uvs are not region-local 0..1 (atlas coordinates?)")
    else:
        # The other half of that bug: UVs that stay inside 0..1 but only cover a
        # sliver of it (page coordinates divided by the page size). A mesh built
        # over an image rect always spans nearly the whole 0..1 square.
        us = uvs[0::2]
        vs = uvs[1::2]
        if (max(us) - min(us)) < MIN_UV_SPAN or (max(vs) - min(vs)) < MIN_UV_SPAN:
            problems.append(
                f"{name}: uvs span only {max(us) - min(us):.3f} x {max(vs) - min(vs):.3f} "
                "of the texture (atlas coordinates?)"
            )

    if not triangles:
        problems.append(f"{name}: mesh has no triangles")
    elif len(triangles) % 3:
        problems.append(f"{name}: triangles length {len(triangles)} is not a multiple of 3")
    else:
        bad = [index for index in triangles if index < 0 or index >= vertex_count]
        if bad:
            problems.append(f"{name}: triangle index {bad[0]} outside 0..{vertex_count - 1}")

    if not vertices:
        problems.append(f"{name}: mesh has no vertices")
        return problems

    try:
        decoded = _decode_vertices(list(vertices))
    except ValueError as exc:
        problems.append(f"{name}: {exc}")
        return problems

    if len(decoded) != vertex_count:
        problems.append(f"{name}: {len(decoded)} vertices decoded but uvs says {vertex_count}")

    for index, entries in enumerate(decoded):
        if not entries:
            problems.append(f"{name}: vertex {index} has no bone influence")
            continue
        if len(entries) > MAX_BONES_PER_VERTEX:
            problems.append(
                f"{name}: vertex {index} has {len(entries)} bones (max {MAX_BONES_PER_VERTEX})"
            )
        for bone_index, _, _, weight in entries:
            if not 0 <= bone_index < bone_count:
                problems.append(f"{name}: vertex {index} references bone {bone_index} (of {bone_count})")
            if weight < -1e-6:
                problems.append(f"{name}: vertex {index} has negative weight {weight}")
        total = sum(entry[3] for entry in entries)
        if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
            problems.append(f"{name}: vertex {index} weights sum to {total:.3f}, not 1")
    return problems


def _check_path(name: str, attachment: Mapping[str, Any]) -> list[str]:
    """Path attachments: the count must be divisible by 3 or the loader throws."""
    problems: list[str] = []
    count = int(attachment.get("vertexCount") or 0)
    vertices = attachment.get("vertices") or []
    lengths = attachment.get("lengths") or []
    if count <= 0:
        problems.append(f"{name}: path has no vertexCount")
        return problems
    if count % 3:
        problems.append(
            f"{name}: path vertexCount {count} is not divisible by 3 "
            "(the loader sizes lengths as vertexCount/3)"
        )
    if len(vertices) != count * 2:
        problems.append(f"{name}: path has {len(vertices)} vertex values for {count} points")
    if count / 3 != len(lengths):
        problems.append(f"{name}: path has {len(lengths)} lengths, expected {count / 3:g}")
    if length_monotonic(lengths) is False:
        problems.append(f"{name}: path lengths are not cumulative (must increase)")
    return problems


def length_monotonic(values: Iterable[float]) -> bool | None:
    seen: list[float] = []
    for value in values:
        if seen and value < seen[-1] - 1e-6:
            return False
        seen.append(value)
    return True


def check_document(document: Mapping[str, Any]) -> list[str]:
    """Return every structural problem found; an empty list means it is drawable."""
    problems: list[str] = []

    bones = document.get("bones") or []
    bone_names: list[str] = []
    for index, bone in enumerate(bones):
        name = bone.get("name")
        if not name:
            problems.append(f"bones[{index}]: missing name")
            continue
        if name in bone_names:
            problems.append(f"bone {name!r}: duplicate")
        parent = bone.get("parent")
        if parent is not None and parent not in bone_names:
            problems.append(f"bone {name!r}: parent {parent!r} is not defined before it")
        bone_names.append(name)

    slots = document.get("slots") or []
    slot_names: list[str] = []
    for slot in slots:
        name = slot.get("name")
        if not name:
            problems.append("slot without a name")
            continue
        if name in slot_names:
            problems.append(f"slot {name!r}: duplicate")
        slot_names.append(name)
        if slot.get("bone") not in bone_names:
            problems.append(f"slot {name!r}: unknown bone {slot.get('bone')!r}")

    if not document.get("skins"):
        problems.append("no skins; nothing can be drawn")
    for skin in document.get("skins") or []:
        for slot_name, attachments in (skin.get("attachments") or {}).items():
            if slot_name not in slot_names:
                problems.append(f"skin {skin.get('name')!r}: attachment on unknown slot {slot_name!r}")
            for name, attachment in (attachments or {}).items():
                kind = attachment.get("type")
                if kind == "mesh":
                    problems += _check_mesh(name, attachment, len(bone_names))
                elif kind == "path":
                    problems += _check_path(name, attachment)
                elif kind in ("region", None):
                    if float(attachment.get("width") or 0) <= 0:
                        problems.append(f"{name}: region width must be positive")
                    if float(attachment.get("height") or 0) <= 0:
                        problems.append(f"{name}: region height must be positive")
                # path/point/boundingbox/... are not emitted by this pipeline.

    problems += _check_constraints(document.get("constraints") or [], bone_names, slot_names)
    return problems


def _check_constraints(
    constraints: Iterable[Mapping[str, Any]], bone_names: list[str], slot_names: list[str]
) -> list[str]:
    problems: list[str] = []
    for constraint in constraints:
        kind = constraint.get("type")
        name = constraint.get("name", "?")
        chain = constraint.get("bones") or []
        for bone in chain:
            if bone not in bone_names:
                problems.append(f"constraint {name!r}: unknown bone {bone!r}")
        if kind == "ik":
            if constraint.get("target") not in bone_names:
                problems.append(f"constraint {name!r}: unknown IK target {constraint.get('target')!r}")
            if len(chain) < 2:
                problems.append(f"constraint {name!r}: IK needs at least two bones")
        elif kind == "path":
            if constraint.get("slot") not in slot_names:
                problems.append(f"constraint {name!r}: unknown path slot {constraint.get('slot')!r}")
        elif kind == "transform":
            if constraint.get("source") not in bone_names:
                problems.append(f"constraint {name!r}: unknown source {constraint.get('source')!r}")
        else:
            problems.append(f"constraint {name!r}: unsupported type {kind!r}")
    return problems
