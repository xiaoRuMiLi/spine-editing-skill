"""Path attachments: one draggable curve that the limb's bones follow.

A path constraint moves BONES along a curve; it does not deform artwork by itself.
Paired with a weighted mesh (``rig/mesh.py``) that is the official recipe for a
limb you can bend by dragging a curve instead of a single target point.

The wire format is not documented anywhere I could find, and every wrong guess
fails loudly but cryptically ("Invalid array length"). Measured against
spine-player 4.3, an OPEN path with two curves needs:

* ``vertexCount`` divisible by 3 -- the loader does ``newArray(vertexCount / 3)``
  for ``lengths`` and a fractional length throws;
* **point 0 is a phantom**: the first curve starts at point 1. Curve ``k`` reads
  points ``3k+1 .. 3k+4``, so two curves need points 1..7;
* ``vertexCount = 9`` therefore: points 1..7 carry the geometry, point 8 is only
  there to keep the count a multiple of three;
* ``lengths`` are CUMULATIVE per curve (``[l1, l1+l2]``), not per-segment;
* vertices live in the slot bone's local space, like every other attachment, and
  -- as the official export shows -- they are written in the WEIGHTED form
  (``boneCount`` then ``boneIndex, x, y, weight``), one bone at weight 1.

Verified: with the path drawn straight through hip/knee/ankle, the constraint puts
the two bones exactly back on those joints (positions 100,300 / 100,180 / 60,60).
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

Point = tuple[float, float]

THIRD = 1.0 / 3.0
TWO_THIRDS = 2.0 / 3.0


def cubic_length(p0: Point, c1: Point, c2: Point, p1: Point, steps: int = 64) -> float:
    """Arc length of one cubic Bezier, sampled (Spine does the same numerically)."""
    total = 0.0
    previous = p0
    for i in range(1, steps + 1):
        t = i / steps
        u = 1.0 - t
        x = u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p1[0]
        y = u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p1[1]
        total += math.hypot(x - previous[0], y - previous[1])
        previous = (x, y)
    return total


def _lerp(a: Point, b: Point, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def build_path_attachment(
    *,
    chain: Sequence[Point],
    frame: tuple[float, float, float],
    bone_index: int = 0,
    name: str | None = None,
    bulge: float = 0.0,
) -> dict[str, Any]:
    """Emit a two-curve path through ``chain`` (hip, knee, ankle) in Spine space.

    ``bulge`` pushes the two control points perpendicular to the limb; 0 keeps the
    path exactly on the bone polyline, which is what the rest pose needs.
    """
    if len(chain) != 3:
        raise ValueError("a limb path needs three points: hip, knee, ankle")
    hip = (float(chain[0][0]), float(chain[0][1]))
    knee = (float(chain[1][0]), float(chain[1][1]))
    ankle = (float(chain[2][0]), float(chain[2][1]))

    def control(a: Point, b: Point) -> tuple[Point, Point]:
        first = _lerp(a, b, THIRD)
        second = _lerp(a, b, TWO_THIRDS)
        if bulge:
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy) or 1.0
            # Perpendicular, scaled by the bulge, peaking in the middle.
            nx, ny = -dy / length, dx / length
            first = (first[0] + nx * bulge * 0.5, first[1] + ny * bulge * 0.5)
            second = (second[0] + nx * bulge * 0.5, second[1] + ny * bulge * 0.5)
        return first, second

    thigh_c1, thigh_c2 = control(hip, knee)
    shin_c1, shin_c2 = control(knee, ankle)

    # 9 points: phantom 0, then the two curves' 7 points, then a phantom tail.
    points = [
        hip,          # 0 phantom
        hip,          # 1 curve 0 starts here
        thigh_c1,     # 2
        thigh_c2,     # 3
        knee,         # 4 shared
        shin_c1,      # 5
        shin_c2,      # 6
        ankle,        # 7 curve 1 ends here
        ankle,        # 8 phantom
    ]

    first_length = cubic_length(points[1], points[2], points[3], points[4])
    second_length = cubic_length(points[4], points[5], points[6], points[7])
    total = first_length + second_length

    ox, oy, rotation = frame
    radians = math.radians(-rotation)
    cos, sin = math.cos(radians), math.sin(radians)
    local: list[float] = []
    for x, y in points:
        dx, dy = x - ox, y - oy
        # Weighted vertex: one bone, weight 1 (same shape as the official export).
        local += [
            1.0,
            float(bone_index),
            round(dx * cos - dy * sin, 3),
            round(dx * sin + dy * cos, 3),
            1.0,
        ]

    attachment: dict[str, Any] = {
        "type": "path",
        "closed": False,
        "constantSpeed": True,
        "vertexCount": 9,
        "vertices": local,
        # Cumulative per curve; the third slot keeps newArray(vertexCount/3) happy.
        "lengths": [
            round(first_length, 3),
            round(total, 3),
            round(total, 3),
        ],
    }
    if name:
        attachment["name"] = name
    return attachment


def build_path_constraint(
    *,
    name: str,
    slot: str,
    bones: Sequence[str],
    spacing_mode: str = "length",
    rotate_mode: str = "chain",
    spacing: float = 0.0,
) -> dict[str, Any]:
    """Constraint dict that makes ``bones`` follow the path in ``slot``.

    Two things matter a lot here:

    * **the enums are lowercase** (``length``, ``chain``, ``percent``,
      ``chainScale``). ``"Chain"`` parses in the JS runtime but the Spine EDITOR
      runs Enum.valueOf and refuses the whole file: ``No enum constant Percent``.
    * **length spacing** (``spacing: 0``) puts each bone where the previous one
      ended, which keeps the joints exactly on the curve. The official project
      uses percent + chainScale because its eight deform bones are all the same
      length; with a 166 px thigh and a 152 px shin, 50% of the path lands 7 px
      away from the knee and the whole limb shifts.
    """
    if len(bones) < 2:
        raise ValueError("a path constraint needs at least two bones")
    # Exact spellings from the official export: spacing modes are all lowercase
    # (``length``, ``percent``, ``proportional``) but rotate modes are camelCase
    # (``tangent``, ``chain``, ``chainScale``). Enum.valueOf is case-sensitive,
    # so ``.lower()`` here would turn chainScale into an invalid constant.
    for value, allowed in (
        (spacing_mode, ("length", "percent", "proportional")),
        (rotate_mode, ("tangent", "chain", "chainScale")),
    ):
        if value not in allowed:
            raise ValueError(f"{value!r} is not one of {allowed}")
    return {
        "type": "path",
        "name": name,
        "slot": slot,
        "bones": list(bones),
        "spacingMode": spacing_mode,
        "rotateMode": rotate_mode,
        "spacing": spacing,
    }


def build_path_constraint_equal_chain(
    *, name: str, slot: str, bones: Sequence[str]
) -> dict[str, Any]:
    """The official recipe: equal-length bones, each owning 1/N of the curve."""
    return build_path_constraint(
        name=name,
        slot=slot,
        bones=bones,
        spacing_mode="percent",
        rotate_mode="chainScale",
        spacing=round(1.0 / len(bones), 4),
    )


def frame_of(frames: Mapping[str, tuple[float, float, float]], bone: str) -> tuple[float, float, float]:
    if bone not in frames:
        raise ValueError(f"path attachment references unknown bone {bone!r}")
    return frames[bone]
