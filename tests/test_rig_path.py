"""Path attachments: the wire format is undocumented, so pin every quirk down.

These numbers were measured against spine-player 4.3. Every wrong guess there
throws "Invalid array length" or silently puts the bones somewhere else, so each
quirk gets a test here rather than a comment in the code.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from spine_forge.core.verify import check_document
from spine_forge.rig.path import (
    build_path_attachment,
    build_path_constraint,
    cubic_length,
)
from spine_forge.stages import assemble

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "girl"
CHAIN = [(100.0, 300.0), (100.0, 180.0), (60.0, 60.0)]  # spine space, y up


def _path(**overrides):
    kwargs = dict(chain=CHAIN, frame=(0.0, 0.0, 0.0))
    kwargs.update(overrides)
    return build_path_attachment(**kwargs)


def _points(attachment):
    flat = attachment["vertices"]
    return [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]


def test_vertex_count_is_nine_and_divisible_by_three():
    """The loader does newArray(vertexCount/3); 7 or 8 throws Invalid array length."""
    attachment = _path()
    assert attachment["type"] == "path"
    assert attachment["vertexCount"] == 9
    assert len(attachment["vertices"]) == 18
    assert len(attachment["lengths"]) == 3


def test_point_zero_is_a_phantom_and_the_curve_starts_at_point_one():
    points = _points(_path())
    assert points[0] == points[1], "point 0 is never read; keep it on the start point"
    assert points[8] == points[7], "point 8 only exists to keep the count a multiple of 3"


def test_the_chain_is_points_one_four_seven():
    points = _points(_path())
    assert points[1] == pytest.approx(CHAIN[0])
    assert points[4] == pytest.approx(CHAIN[1])
    assert points[7] == pytest.approx(CHAIN[2])


def test_lengths_are_cumulative_and_cover_the_path():
    attachment = _path()
    first, total, spare = attachment["lengths"]
    assert 0 < first < total
    assert spare == total  # third slot is only there to fill newArray(3)
    straight = math.dist(CHAIN[0], CHAIN[1]) + math.dist(CHAIN[1], CHAIN[2])
    assert total == pytest.approx(straight, rel=1e-3)


def test_cubic_length_of_a_straight_line_is_the_distance():
    assert cubic_length((0, 0), (1, 0), (2, 0), (3, 0)) == pytest.approx(3.0, rel=1e-4)


def test_vertices_are_written_in_the_slot_bone_frame():
    """A rotated slot bone must not move the curve on screen."""
    attachment = _path(frame=(100.0, 300.0, 90.0))
    points = _points(attachment)
    # Rotating the frame by -90 and then applying it again lands back on the world point.
    x, y = points[4]
    radians = math.radians(90.0)
    cos, sin = math.cos(radians), math.sin(radians)
    world_x = x * cos - y * sin + 100.0
    world_y = x * sin + y * cos + 300.0
    assert (round(world_x, 3), round(world_y, 3)) == pytest.approx(CHAIN[1], abs=1e-3)


def test_constraint_spaces_the_chain_along_the_curve():
    constraint = build_path_constraint(name="leg-path-r", slot="curve", bones=["leg_r", "shin_r"])
    assert constraint["type"] == "path"
    assert constraint["slot"] == "curve"
    assert constraint["bones"] == ["leg_r", "shin_r"]
    # Length spacing with 0 gap puts each bone where the previous one ended, which
    # is what keeps the joints ON the curve.
    assert constraint["spacingMode"] == "Length"
    assert constraint["spacing"] == 0.0
    assert constraint["rotateMode"] == "Chain"
    assert constraint["mixRotate"] == 1.0


# --------------------------------------------------------------- integration


def _build(tmp_path: Path, leg_control: str, arm_control: str = "ik") -> dict:
    out = tmp_path / f"{leg_control}-{arm_control}"
    result = assemble.run(
        str(EXAMPLE / "parts.json"),
        str(EXAMPLE / "rig" / "bones.json"),
        str(out),
        name="girl",
        mode="images",
        warp="legs",
        leg_control=leg_control,
        arm_control=arm_control,
    )
    assert result["checked"] is True
    return json.loads((out / "girl.json").read_text(encoding="utf-8"))


def test_path_mode_replaces_the_leg_ik_instead_of_fighting_it(tmp_path):
    document = _build(tmp_path, "path")
    kinds = [(c["type"], c.get("name")) for c in document["constraints"]]

    assert ("path", "leg-path-r") in kinds
    assert ("path", "leg-path-l") in kinds
    # One boss per bone: the foot IK must be gone, the hand IK must stay.
    driven = {bone for c in document["constraints"] if c["type"] == "path" for bone in c["bones"]}
    assert driven == {"leg_r", "shin_r", "leg_l", "shin_l"}
    for constraint in document["constraints"]:
        if constraint["type"] == "ik":
            assert not (set(constraint["bones"]) & driven)

    slots = {slot["name"]: slot for slot in document["slots"]}
    assert slots["leg-curve-r"]["bone"] == "root"
    attachment = document["skins"][0]["attachments"]["leg-curve-r"]["leg-curve-r"]
    assert attachment["type"] == "path"


def test_ik_mode_has_no_paths_at_all(tmp_path):
    document = _build(tmp_path, "ik")
    assert not [c for c in document["constraints"] if c["type"] == "path"]
    assert all("-curve-" not in slot["name"] for slot in document["slots"])


def test_arm_path_replaces_the_hand_ik_too(tmp_path):
    """Arms are two bones as well: same path recipe, different chain."""
    document = _build(tmp_path, "ik", "path")
    driven = {bone for c in document["constraints"] if c["type"] == "path" for bone in c["bones"]}
    assert driven == {"arm_r", "fore_r", "arm_l", "fore_l"}
    for constraint in document["constraints"]:
        if constraint["type"] == "ik":
            assert not (set(constraint["bones"]) & driven)
    names = {c.get("name") for c in document["constraints"]}
    assert {"arm-path-r", "arm-path-l"} <= names
    slots = {slot["name"] for slot in document["slots"]}
    assert {"arm-curve-r", "arm-curve-l"} <= slots


def test_both_limbs_can_be_path_driven_at_once(tmp_path):
    document = _build(tmp_path, "path", "path")
    driven = {bone for c in document["constraints"] if c["type"] == "path" for bone in c["bones"]}
    assert driven == {"leg_r", "shin_r", "leg_l", "shin_l", "arm_r", "fore_r", "arm_l", "fore_l"}
    # No IK may be left on any of those bones.
    assert not [c for c in document["constraints"] if c["type"] == "ik"]


def test_self_check_rejects_a_vertex_count_that_is_not_a_multiple_of_three(tmp_path):
    document = _build(tmp_path, "path")
    attachment = document["skins"][0]["attachments"]["leg-curve-r"]["leg-curve-r"]
    attachment["vertexCount"] = 7
    problems = check_document(document)
    assert any("not divisible by 3" in problem for problem in problems)
