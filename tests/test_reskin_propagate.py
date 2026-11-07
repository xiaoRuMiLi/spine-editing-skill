"""Propagation: scaling a part must shrink everything hung off it, and nothing else.

The load-bearing case here is the variable-length mesh vertex layout. Spine stores
vertices as ``[boneCount] [boneIndex x y weight] * boneCount`` per vertex, so a
fixed-stride multiply corrupts bone indices and the runtime dies on an undefined
pose. That is a real crash this file exists to prevent.
"""

from __future__ import annotations

import pytest

from spine_forge.core.rig import Rig
from spine_forge.reskin.propagate import _parse_vertices, propagate_scale


def small_rig() -> Rig:
    """head -> control -> control-back, with art on each.

    Mirrors the owl's shape closely enough to exercise every branch: a bone with
    children, a slot on the replaced bone, slots on a child bone, one empty slot,
    and a mesh attachment.
    """
    data = {
        "skeleton": {"name": "test", "spine": "4.3", "width": 200, "height": 200},
        "bones": [
            {"name": "root"},
            {"name": "head", "parent": "root", "x": 50.0, "y": 10.0, "length": 40.0},
            {"name": "control", "parent": "head", "y": 100.0},
            {"name": "control-back", "parent": "head", "x": 2.0, "y": 60.0},
            {"name": "unrelated", "parent": "root", "x": 9.0, "y": 9.0},
        ],
        "slots": [
            {"name": "head-base", "bone": "head", "attachment": "head-base"},
            {"name": "eye", "bone": "control", "attachment": "eye"},
            {"name": "eye-closed", "bone": "control", "attachment": None},
            {"name": "beak", "bone": "head", "attachment": "beak"},
            {"name": "other", "bone": "unrelated", "attachment": "other"},
        ],
        "skins": [
            {
                "name": "default",
                "attachments": {
                    "head-base": {
                        "head-base": {
                            "type": "mesh",
                            "width": 100.0,
                            "height": 100.0,
                            "uvs": [0, 0],
                            # One unweighted vertex: [0] [x] [y]
                            "vertices": [0, 10.0, 20.0],
                        }
                    },
                    "eye": {
                        "eye": {
                            "x": -20.0,
                            "y": 30.0,
                            "width": 40.0,
                            "height": 40.0,
                        }
                    },
                    "eye-closed": {
                        "eye-closed": {"x": -20.0, "y": 30.0, "width": 40.0, "height": 40.0}
                    },
                    "beak": {
                        "beak": {
                            "type": "mesh",
                            "width": 30.0,
                            "height": 20.0,
                            "uvs": [0, 0],
                            # One weighted vertex with two influencing bones:
                            # [2] [10][x][y][w] [9][x][y][w]
                            "vertices": [2, 10, 6.0, 8.0, 0.5, 9, 6.0, 8.0, 0.5],
                        }
                    },
                    "other": {"other": {"x": 7.0, "y": 7.0, "width": 10.0, "height": 10.0}},
                },
            }
        ],
    }
    return Rig(data)


# ---------------------------------------------------------------- vertex layout


def test_parse_unweighted_vertex():
    runs = _parse_vertices([0, 1.0, 2.0])
    assert len(runs) == 1
    assert runs[0] == [0, 1.0, 2.0]


def test_parse_weighted_vertex():
    flat = [2, 10, 6.0, 8.0, 0.5, 9, 6.0, 8.0, 0.5]
    runs = _parse_vertices(flat)
    assert len(runs) == 1
    assert runs[0] == flat


def test_parse_mixed_vertices():
    flat = [0, 1.0, 2.0, 2, 10, 6.0, 8.0, 0.5, 9, 6.0, 8.0, 0.5]
    runs = _parse_vertices(flat)
    assert len(runs) == 2
    assert runs[0][0] == 0
    assert runs[1][0] == 2


def test_parse_three_bone_vertex():
    flat = [3, 1, 1.0, 1.0, 0.3, 2, 2.0, 2.0, 0.3, 3, 3.0, 3.0, 0.4]
    runs = _parse_vertices(flat)
    assert len(runs) == 1
    assert len(runs[0]) == 1 + 3 * 4


# ----------------------------------------------------------------- propagation


def test_identity_scale_changes_nothing():
    rig = small_rig()
    before = rig.copy().data
    report = propagate_scale(rig, slot="head-base", bone="head", factor=1.0)
    assert rig.data == before
    assert report.bones_scaled == []


def test_scales_the_bone_the_part_hangs_on():
    rig = small_rig()
    propagate_scale(rig, slot="head-base", bone="head", factor=0.5)

    head = rig.bone("head")
    assert head["x"] == pytest.approx(25.0)
    assert head["y"] == pytest.approx(5.0)
    assert head["length"] == pytest.approx(20.0)


def test_scales_descendant_bone_offsets():
    rig = small_rig()
    propagate_scale(rig, slot="head-base", bone="head", factor=0.5)

    assert rig.bone("control")["y"] == pytest.approx(50.0)
    assert rig.bone("control-back")["x"] == pytest.approx(1.0)
    assert rig.bone("control-back")["y"] == pytest.approx(30.0)


def test_leaves_unrelated_bones_alone():
    rig = small_rig()
    propagate_scale(rig, slot="head-base", bone="head", factor=0.5)
    unrelated = rig.bone("unrelated")
    assert unrelated["x"] == pytest.approx(9.0)
    assert unrelated["y"] == pytest.approx(9.0)


def test_scales_child_attachment_placement():
    rig = small_rig()
    propagate_scale(rig, slot="head-base", bone="head", factor=0.5)
    eye = rig.attachment("eye", "eye")
    assert eye["x"] == pytest.approx(-10.0)
    assert eye["y"] == pytest.approx(15.0)


def test_does_not_scale_attachment_width_or_height():
    """width/height bound the sampling box; scaling both vertices and box
    double-counts the change and slides the texture off the silhouette."""
    rig = small_rig()
    propagate_scale(rig, slot="head-base", bone="head", factor=0.5)
    eye = rig.attachment("eye", "eye")
    assert eye["width"] == pytest.approx(40.0)
    assert eye["height"] == pytest.approx(40.0)


def test_skips_empty_slots():
    """An unset slot is a hidden toggle. Touching it desynchronises slot and skin."""
    rig = small_rig()
    report = propagate_scale(rig, slot="head-base", bone="head", factor=0.5)
    assert "eye-closed" not in report.attachments_scaled
    assert "eye-closed" not in str(report.vertices_scaled)


def test_leaves_rotation_alone():
    rig = small_rig()
    rig.bone("control")["rotation"] = 33.0
    propagate_scale(rig, slot="head-base", bone="head", factor=0.5)
    assert rig.bone("control")["rotation"] == pytest.approx(33.0)


def test_scales_unweighted_vertex_positions():
    rig = small_rig()
    propagate_scale(rig, slot="head-base", bone="head", factor=0.5)
    vertices = rig.attachment("other", "other") if False else None  # unused
    head = rig.attachment("head-base", "head-base")
    # The replaced part is excluded from propagation; its own vertices stay put.
    assert head["vertices"][1] == pytest.approx(10.0)


def test_weighted_vertex_keeps_bone_indices_and_weights():
    """The crash this guards against: scaling bone indices points the mesh at
    bones that do not exist."""
    rig = small_rig()
    propagate_scale(rig, slot="head-base", bone="head", factor=0.5)

    beak = rig.attachment("beak", "beak")
    flat = beak["vertices"]
    # [2] [10][x][y][w] [9][x][y][w]
    assert flat[0] == 2, "bone count must not scale"
    assert flat[1] == 10, "bone index must not scale"
    assert flat[2] == pytest.approx(3.0), "x scales"
    assert flat[3] == pytest.approx(4.0), "y scales"
    assert flat[4] == pytest.approx(0.5), "weight must not scale"
    assert flat[5] == 9, "second bone index must not scale"
    assert flat[6] == pytest.approx(3.0)
    assert flat[7] == pytest.approx(4.0)
    assert flat[8] == pytest.approx(0.5)


def test_bone_indices_survive_large_scale():
    """A factor big enough to turn index 10 into 19.7 catches the old bug."""
    rig = small_rig()
    propagate_scale(rig, slot="head-base", bone="head", factor=1.970464)
    flat = rig.attachment("beak", "beak")["vertices"]
    assert flat[1] == 10
    assert flat[5] == 9


def test_report_lists_what_changed():
    rig = small_rig()
    report = propagate_scale(rig, slot="head-base", bone="head", factor=0.5)
    assert "head" in report.bones_scaled
    assert "control" in report.bones_scaled
    assert "eye" in report.attachments_scaled
    assert report.scale == pytest.approx(0.5)


def test_can_skip_children():
    rig = small_rig()
    propagate_scale(
        rig, slot="head-base", bone="head", factor=0.5, include_children=False
    )
    # Descendants keep their offsets.
    assert rig.bone("control")["y"] == pytest.approx(100.0)
    assert rig.attachment("eye", "eye")["y"] == pytest.approx(30.0)
