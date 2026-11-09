"""Weighted meshes: one image that bends at a joint instead of being cut in two.

A region attachment is rigid -- the pixels move as a block with their bone, so a
leg bound to the thigh cannot bend at the knee. The Spine way to bend artwork is
a *mesh* attachment (a skinned mesh): every vertex is weighted to one or two
bones, so the vertices above the knee follow the thigh, the ones below follow the
shin, and a narrow band across the joint blends the two. Bending is then a smooth
warp of one continuous image, with no seam to hide and no duplicated pixels.

Only two places in the wire format are easy to get wrong, and both fail silently:

1. **Weighted vertex layout.** ``vertices`` is not ``x,y`` pairs. Each vertex is
   ``boneCount`` followed by ``boneCount * (boneIndex, x, y, weight)``, where
   ``boneIndex`` is the bone's index in the skeleton's ``bones`` array and
   ``x, y`` is the SAME world point expressed in that bone's local frame. Get the
   frame wrong and the mesh snaps to a different place -- no error is raised.
2. **UV orientation.** Mesh UVs are REGION-LOCAL (0..1 inside the artwork, not
   atlas coordinates -- the runtime rebases them with the region's bounds), and
   ``v = 0`` is the TOP of the image because the atlas measures y downwards.
   Pointing them at the whole page, or flipping v, mirrors the artwork inside
   the mesh.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

Frame = tuple[float, float, float]  # world x, world y, world rotation (degrees)
Point = tuple[float, float]


def bone_world_frames(
    spine_bones: Sequence[Mapping[str, Any]],
) -> dict[str, Frame]:
    """Turn local bone x/y/rotation into world x/y/rotation (y up).

    Parents must come before children, which is how ``bones.json`` is written.
    """
    frames: dict[str, Frame] = {}
    for bone in spine_bones:
        name = bone["name"]
        lx = float(bone.get("x", 0.0))
        ly = float(bone.get("y", 0.0))
        rotation = float(bone.get("rotation", 0.0))
        parent = bone.get("parent")
        if parent:
            if parent not in frames:
                raise ValueError(f"bone {name!r}: parent {parent!r} has no frame yet")
            px, py, prot = frames[parent]
            radians = math.radians(prot)
            cos, sin = math.cos(radians), math.sin(radians)
            frames[name] = (
                px + lx * cos - ly * sin,
                py + lx * sin + ly * cos,
                prot + rotation,
            )
        else:
            frames[name] = (lx, ly, rotation)
    return frames


def local_point(frame: Frame, world_x: float, world_y: float) -> Point:
    """Express one world point in a bone's local frame (rest pose)."""
    bx, by, rotation = frame
    radians = math.radians(-rotation)
    cos, sin = math.cos(radians), math.sin(radians)
    dx, dy = world_x - bx, world_y - by
    return dx * cos - dy * sin, dx * sin + dy * cos


def _smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def grid_topology(cols: int, rows: int) -> tuple[list[tuple[int, int]], dict[tuple[int, int], int], int, list[int]]:
    """Vertex order and triangles for a ``cols`` x ``rows`` grid.

    Spine stores hull vertices first, walked around the outline, then the
    interior ones. The editor needs that order to draw the mesh outline; the
    runtime only needs ``triangles`` to point at the right slots.
    """
    if cols < 2 or rows < 2:
        raise ValueError("a warp mesh needs at least 2 columns and 2 rows")

    order: list[tuple[int, int]] = []
    index: dict[tuple[int, int], int] = {}

    def push(i: int, j: int) -> None:
        index[(i, j)] = len(order)
        order.append((i, j))

    for i in range(cols):  # top edge, left to right
        push(i, 0)
    for j in range(1, rows):  # right edge, downwards
        push(cols - 1, j)
    for i in range(cols - 2, -1, -1):  # bottom edge, right to left
        push(i, rows - 1)
    for j in range(rows - 2, 0, -1):  # left edge, upwards
        push(0, j)
    hull = len(order)

    for j in range(1, rows - 1):
        for i in range(1, cols - 1):
            push(i, j)

    triangles: list[int] = []
    for j in range(rows - 1):
        for i in range(cols - 1):
            top_left = index[(i, j)]
            top_right = index[(i + 1, j)]
            bottom_left = index[(i, j + 1)]
            bottom_right = index[(i + 1, j + 1)]
            triangles += [top_left, top_right, bottom_right]
            triangles += [top_left, bottom_right, bottom_left]
    return order, index, hull, triangles


def _hull_edges(hull: int) -> list[int]:
    """Close the hull loop: [0,1, 1,2, ..., hull-1,0] as a flat index list."""
    edges: list[int] = []
    for i in range(hull):
        edges += [i, (i + 1) % hull]
    return edges


def _chain_param(
    chain: Sequence[Point], x: float, y: float
) -> tuple[float, float, float]:
    """Where (x, y) sits along a polyline: (arc length, total length, joint length).

    Projecting onto a single bone's axis is not enough: a corner of the artwork's
    bounding box can be 80 px away from the knee and still project onto the joint,
    and would then be handed to the shin bone -- the upper thigh gets dragged
    along and the leg looks torn apart. Walking the whole chain and taking the
    NEAREST point puts every vertex on the segment it actually belongs to.
    """
    best_distance = float("inf")
    best_s = 0.0
    travelled = 0.0
    joint = 0.0
    for index, (start, end) in enumerate(zip(chain, chain[1:])):
        x0, y0 = float(start[0]), float(start[1])
        x1, y1 = float(end[0]), float(end[1])
        dx, dy = x1 - x0, y1 - y0
        segment = math.hypot(dx, dy)
        if segment <= 1e-9:
            continue
        t = ((x - x0) * dx + (y - y0) * dy) / (segment * segment)
        t = min(1.0, max(0.0, t))
        closest_x, closest_y = x0 + t * dx, y0 + t * dy
        distance = math.hypot(x - closest_x, y - closest_y)
        if distance < best_distance:
            best_distance = distance
            best_s = travelled + t * segment
        travelled += segment
        if index == 0:
            joint = travelled
    return best_s, travelled, joint


def build_warp_mesh(
    *,
    box: Sequence[float],
    frames: Mapping[str, Frame],
    bone_names: Sequence[str],
    upper: str,
    lower: str,
    chain: Sequence[Point],
    canvas_height: float,
    cols: int = 5,
    rows: int = 14,
    band: float = 10.0,
) -> dict[str, Any]:
    """Build a mesh attachment whose vertices blend from ``upper`` to ``lower``.

    Parameters are in source-image pixels (y down) so they line up with
    ``parts.json``:

    * ``box``   -- (left, top, right, bottom) of the artwork in the canvas.
    * ``chain`` -- the bone chain that runs through the limb, as pixels:
                   [hip, knee, ankle]. The knee is where the two bones meet.
    * ``band``  -- half-width of the blend band, measured ALONG the chain.
                   Roughly half the limb thickness gives a knee-like fold
                   without pinching.

    The mesh is a regular grid over the artwork's bounding box; the transparent
    corners of that box are harmless because the texture is transparent there --
    but they must still be weighted to the bone whose segment is closest to them,
    which is what ``_chain_param`` provides.
    """
    left, top, right, bottom = (float(v) for v in box)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise ValueError(f"degenerate warp box: {tuple(box)}")
    for name in (upper, lower):
        if name not in frames:
            raise ValueError(f"warp mesh references unknown bone {name!r}")
    if len(chain) != 3:
        raise ValueError("a warp chain needs exactly three points: hip, knee, ankle")

    bone_index = {name: i for i, name in enumerate(bone_names)}

    order, _, hull, triangles = grid_topology(cols, rows)

    uvs: list[float] = []
    vertices: list[float] = []
    for i, j in order:
        px = left + width * i / (cols - 1)
        py = top + height * j / (rows - 1)
        uvs += [round(i / (cols - 1), 6), round(j / (rows - 1), 6)]

        world_x = px
        world_y = canvas_height - py
        along, _, joint = _chain_param(chain, px, py)
        weight_lower = _smoothstep((along - joint) / (2.0 * band) + 0.5)

        if weight_lower <= 0.0:
            entries = [(upper, 1.0)]
        elif weight_lower >= 1.0:
            entries = [(lower, 1.0)]
        else:
            entries = [(upper, round(1.0 - weight_lower, 4)), (lower, round(weight_lower, 4))]

        vertices.append(float(len(entries)))
        for name, weight in entries:
            lx, ly = local_point(frames[name], world_x, world_y)
            vertices += [float(bone_index[name]), round(lx, 3), round(ly, 3), weight]

    # Fail here rather than in a screenshot: a vertex whose weights do not sum to
    # 1 sinks between its bones and the limb looks torn.
    cursor = 0
    while cursor < len(vertices):
        count = int(vertices[cursor])
        block = vertices[cursor + 1 : cursor + 1 + count * 4]
        total = sum(block[i] for i in range(3, len(block), 4))
        if abs(total - 1.0) > 1e-3:
            raise ValueError(f"warp mesh vertex weights sum to {total:.4f}, not 1")
        cursor += 1 + count * 4

    return {
        "type": "mesh",
        "width": round(width, 3),
        "height": round(height, 3),
        "uvs": uvs,
        "triangles": triangles,
        "vertices": vertices,
        "hull": hull,
        # The hull IS the mesh boundary here, so the outline is the hull loop.
        # The runtime only uses this for debug drawing, but the editor wants it.
        "edges": _hull_edges(hull),
    }
