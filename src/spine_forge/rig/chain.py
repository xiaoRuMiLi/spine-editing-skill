"""A chain of equal-length deform bones along a limb.

This is the layer the official mix-and-match project uses between the artwork and
the path constraint: player-facing bones (``leg_r`` / ``shin_r``) are driven by IK,
a *separate* chain of deform bones is driven by the path, and the skin is weighted
to the chain. That separation is what lets both controls work at once:

    IK target  ->  leg_r/shin_r  ->  (path, skinned to them)  ->  chain  ->  skin
    path control points -------------------------------------->  chain  ->  skin

Equal lengths matter: with equal bones the path constraint can use
``percent`` spacing (every bone owns exactly 1/N of the curve) plus
``chainScale``, which is the recipe the official export uses. Unequal bones would
need ``length`` spacing instead.
"""

from __future__ import annotations

import math
from typing import Sequence

Point = tuple[float, float]


def subdivide(points: Sequence[Point], count: int) -> list[tuple[Point, Point]]:
    """Split a polyline into ``count`` segments of equal length.

    Returns [(base, tip)] in the same space as ``points`` (Spine world, y up).
    """
    if count < 1:
        raise ValueError("a chain needs at least one segment")
    if len(points) < 2:
        raise ValueError("a chain needs at least two points")

    lengths = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    total = sum(lengths)
    if total <= 0:
        raise ValueError("degenerate polyline: zero length")

    def at(distance: float) -> Point:
        """Point at ``distance`` along the polyline."""
        travelled = 0.0
        for index, length in enumerate(lengths):
            if travelled + length >= distance - 1e-9:
                t = 0.0 if length <= 0 else (distance - travelled) / length
                t = min(1.0, max(0.0, t))
                a, b = points[index], points[index + 1]
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            travelled += length
        return points[-1]

    step = total / count
    return [(at(i * step), at((i + 1) * step)) for i in range(count)]


def chain_bones(
    *,
    segments: Sequence[tuple[Point, Point]],
    names: Sequence[str],
    parent: str,
    parent_rotation: float,
) -> list[dict]:
    """Local bone transforms for a tip-to-tail chain.

    ``parent_rotation`` is the world rotation (degrees) of the bone the chain hangs
    off, because a child's local rotation is relative to it. Each bone's local
    ``x`` is the previous bone's length and ``y`` is 0: that is what makes the
    chain visually connected.
    """
    if len(segments) != len(names):
        raise ValueError("segments and names must line up")

    bones: list[dict] = []
    previous_world = parent_rotation
    previous_length = 0.0
    previous_parent = parent

    for (base, tip), name in zip(segments, names):
        dx, dy = tip[0] - base[0], tip[1] - base[1]
        length = math.hypot(dx, dy)
        world = math.degrees(math.atan2(dy, dx)) if length > 1e-9 else previous_world
        bones.append(
            {
                "name": name,
                "parent": previous_parent,
                "x": round(previous_length, 3),
                "y": 0.0,
                "rotation": round(world - previous_world, 3),
                "length": round(length, 3),
            }
        )
        previous_world = world
        previous_length = length
        previous_parent = name
    return bones
