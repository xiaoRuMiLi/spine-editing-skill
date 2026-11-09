"""Weighted-mesh tests: one image that bends at a joint (no cut, no seam)."""

from __future__ import annotations

import math

import pytest

from spine_forge.rig.mesh import (
    bone_world_frames,
    build_warp_mesh,
    grid_topology,
    local_point,
)

# A minimal leg: thigh from (100,100) to (100,200) in image pixels (y down),
# shin from (100,200) to (100,300). Canvas is 400 tall, so in Spine's y-up
# space the thigh runs 300 -> 200 and the shin 200 -> 100.
CANVAS_H = 400.0
BOX = (80.0, 100.0, 120.0, 300.0)
CHAIN = ((100.0, 100.0), (100.0, 200.0), (100.0, 300.0))  # hip, knee, ankle
BONE_NAMES = ["root", "thigh", "shin"]
FRAMES = {
    "root": (0.0, 0.0, 0.0),
    "thigh": (100.0, 300.0, -90.0),
    "shin": (100.0, 200.0, -90.0),
}


def test_frames_are_derived_from_the_bone_table():
    frames = bone_world_frames(
        [
            {"name": "root", "x": 100.0, "y": 300.0, "rotation": 0.0},
            {"name": "thigh", "parent": "root", "x": 0.0, "y": 0.0, "rotation": -90.0},
        ]
    )
    # The thigh's own frame is not rotated by the (unrotated) root.
    assert frames["thigh"] == (100.0, 300.0, -90.0)


def _mesh(**overrides):
    kwargs = dict(
        box=BOX,
        frames=FRAMES,
        bone_names=BONE_NAMES,
        upper="thigh",
        lower="shin",
        chain=CHAIN,
        canvas_height=CANVAS_H,
        cols=5,
        rows=11,
        band=10.0,
    )
    kwargs.update(overrides)
    return build_warp_mesh(**kwargs)


def _vertex_count(mesh) -> int:
    return len(mesh["uvs"]) // 2


def _vertices(mesh):
    """Decode the weighted layout into [[(bone_index, x, y, weight), ...]]."""
    flat = mesh["vertices"]
    out = []
    i = 0
    while i < len(flat):
        count = int(flat[i])
        i += 1
        entries = []
        for _ in range(count):
            entries.append((int(flat[i]), flat[i + 1], flat[i + 2], flat[i + 3]))
            i += 4
        out.append(entries)
    return out


def _world(entries, rotations: dict[str, float] | None = None):
    """Linear-blend skinning, the same maths the runtime does."""
    rotations = rotations or {}
    x = y = 0.0
    for bone_index, lx, ly, weight in entries:
        name = BONE_NAMES[bone_index]
        bx, by, rotation = FRAMES[name]
        radians = math.radians(rotation + rotations.get(name, 0.0))
        cos, sin = math.cos(radians), math.sin(radians)
        x += (lx * cos - ly * sin + bx) * weight
        y += (lx * sin + ly * cos + by) * weight
    return x, y


# --------------------------------------------------------------- topology


def test_hull_vertices_are_walked_around_the_outline():
    order, index, hull, _ = grid_topology(4, 3)
    # 2*cols + 2*rows - 4 is the perimeter of a grid.
    assert hull == 2 * 4 + 2 * 3 - 4
    perimeter = order[:hull]
    assert perimeter[0] == (0, 0)
    assert perimeter[3] == (3, 0)  # top edge runs left to right
    assert (0, 1) in perimeter  # the left edge closes the loop
    assert len(order) == len(set(order)) == 4 * 3
    assert len(index) == len(order)


def test_interior_vertices_come_after_the_hull():
    order, _, hull, _ = grid_topology(4, 3)
    assert order[hull:] == [(1, 1), (2, 1)]


def test_triangles_cover_every_cell_and_stay_in_range():
    cols, rows = 5, 6
    order, _, _, triangles = grid_topology(cols, rows)
    assert len(triangles) == 2 * (cols - 1) * (rows - 1) * 3
    assert all(0 <= index < len(order) for index in triangles)


def test_uvs_count_matches_vertices():
    mesh = _mesh()
    assert mesh["type"] == "mesh"
    assert len(mesh["uvs"]) == 2 * _vertex_count(mesh)
    assert len(mesh["triangles"]) % 3 == 0
    assert mesh["hull"] > 0


def test_every_vertex_has_weights_summing_to_one():
    for entries in _vertices(_mesh()):
        assert sum(entry[3] for entry in entries) == pytest.approx(1.0, abs=1e-3)
        assert 1 <= len(entries) <= 2


def test_above_the_knee_follows_only_the_thigh():
    entries = _vertices(_mesh(cols=2, rows=3))[0]  # top-left, above the knee
    assert entries[0][0] == BONE_NAMES.index("thigh")
    assert entries[0][3] == 1.0
    assert len(entries) == 1


def test_below_the_knee_follows_only_the_shin():
    shin = BONE_NAMES.index("shin")
    entries = [v for v in _vertices(_mesh(cols=2, rows=3)) if v[0][0] == shin]
    assert entries, "no vertex is weighted to the shin"
    for vertex in entries:
        assert len(vertex) == 1
        assert vertex[0][3] == 1.0


def test_band_carries_both_bones_across_the_knee():
    blended = [v for v in _vertices(_mesh()) if len(v) == 2]
    assert blended, "the blend band vanished"
    for entries in blended:
        assert 0.0 < entries[0][3] < 1.0
        assert 0.0 < entries[1][3] < 1.0


# ------------------------------------------------------------ rest pose


def test_rest_pose_reproduces_the_source_pixels():
    """At rest the mesh must sit exactly on the artwork, or the leg shifts."""
    cols, rows = 5, 11
    mesh = _mesh(cols=cols, rows=rows)
    left, top, right, bottom = BOX
    order, _, _, _ = grid_topology(cols, rows)
    for (i, j), entries in zip(order, _vertices(mesh)):
        expected_x = left + (right - left) * i / (cols - 1)
        expected_y = CANVAS_H - (top + (bottom - top) * j / (rows - 1))
        x, y = _world(entries)
        assert x == pytest.approx(expected_x, abs=1e-3)
        assert y == pytest.approx(expected_y, abs=1e-3)


def test_local_point_round_trips_through_a_rotated_bone():
    frame = (100.0, 300.0, -90.0)
    lx, ly = local_point(frame, 120.0, 280.0)
    # Forward transform back into world space.
    radians = math.radians(frame[2])
    cos, sin = math.cos(radians), math.sin(radians)
    assert lx * cos - ly * sin + frame[0] == pytest.approx(120.0)
    assert lx * sin + ly * cos + frame[1] == pytest.approx(280.0)


# --------------------------------------------------------------- bending


def test_bending_the_shin_moves_the_lower_half_only():
    """This is the whole point: the knee bends while the thigh stays put."""
    cols, rows = 5, 11
    mesh = _mesh(cols=cols, rows=rows)
    order, _, _, _ = grid_topology(cols, rows)
    moved = []
    for (i, j), entries in zip(order, _vertices(mesh)):
        rest = _world(entries)
        bent = _world(entries, {"shin": 40.0})
        moved.append(((i, j), math.hypot(bent[0] - rest[0], bent[1] - rest[1])))

    by_row: dict[int, list[float]] = {}
    for (i, j), distance in moved:
        by_row.setdefault(j, []).append(distance)

    assert max(by_row[0]) < 1e-6, "the thigh half must not move"
    assert min(by_row[rows - 1]) > 1.0, "the shin half must follow the shin bone"
    # …and the change is gradual, which is what makes the knee look bent rather
    # than broken in two.
    knee_row = min(by_row, key=lambda j: abs(j - (rows - 1) / 2))
    assert 0.0 < max(by_row[knee_row]) < max(by_row[rows - 1])
