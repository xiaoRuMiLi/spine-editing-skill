"""Serializer tests: the Spine 4.2 wire-format rules that fail silently."""

from __future__ import annotations

import json

import pytest

from spine_forge.core import Bone, RegionAttachment, Skeleton, Slot, to_spine_json


def _rig() -> Skeleton:
    rig = Skeleton(name="t", width=400, height=600)
    rig.add_bone(Bone("root"))
    rig.add_bone(Bone("hip", parent="root", x=0, y=200, length=30))
    rig.add_slot(Slot("hip", bone="hip", attachment="hip"))
    rig.add_attachment(RegionAttachment("hip", width=60, height=80))
    return rig


def test_skeleton_block_shape():
    doc = to_spine_json(_rig())
    meta = doc["skeleton"]
    assert meta["spine"] == "4.2.0"
    assert meta["name"] == "t"
    # Origin sits at the horizontal centre, so the rig shifts left by half.
    assert meta["x"] == -200
    assert meta["width"] == 400
    assert meta["height"] == 600


def test_bone_order_and_parents_preserved():
    doc = to_spine_json(_rig())
    names = [b["name"] for b in doc["bones"]]
    assert names == ["root", "hip"]
    assert doc["bones"][1]["parent"] == "root"


def test_attachments_nest_under_slot_then_attachment():
    doc = to_spine_json(_rig())
    skin = doc["skins"][0]
    assert skin["name"] == "default"
    # Outer key is the SLOT name, inner key is the ATTACHMENT name.
    assert skin["attachments"]["hip"]["hip"]["width"] == 60


def test_duplicate_bone_rejected():
    rig = Skeleton()
    rig.add_bone(Bone("a"))
    with pytest.raises(ValueError, match="duplicate bone"):
        rig.add_bone(Bone("a"))


def test_dangling_parent_rejected():
    with pytest.raises(ValueError, match="parent"):
        Skeleton().add_bone(Bone("child", parent="ghost"))


def test_slot_with_unknown_bone_rejected():
    rig = Skeleton()
    rig.add_bone(Bone("root"))
    with pytest.raises(ValueError, match="unknown bone"):
        rig.add_slot(Slot("s", bone="nope"))


def test_rotation_uses_value_not_angle():
    rig = _rig()
    rig.animations = {
        "idle": {
            "bones": {
                "hip": {
                    "rotate": [
                        {"time": 0.0, "angle": 0},
                        {"time": 1.0, "angle": 20},
                    ]
                }
            }
        }
    }
    doc = to_spine_json(rig)
    frames = doc["animations"]["idle"]["bones"]["hip"]["rotate"]
    # A 4.x runtime ignores "angle" entirely; every value must land in "value".
    assert all("angle" not in f for f in frames)
    assert frames[1]["value"] == 20


def test_single_property_curve_is_four_numbers():
    rig = _rig()
    rig.animations = {
        "a": {
            "bones": {
                "hip": {
                    "rotate": [
                        {"time": 0.0, "angle": 0},
                        {"time": 1.0, "angle": 10, "curve": [0.25, 0, 0.75, 1]},
                    ]
                }
            }
        }
    }
    doc = to_spine_json(rig)
    frames = doc["animations"]["a"]["bones"]["hip"]["rotate"]
    curve = frames[0]["curve"]
    assert len(curve) == 4
    # Absolute, not normalized: x spans the segment 0..1 -> 0.25..0.75.
    assert curve[0] == pytest.approx(0.25)
    assert curve[2] == pytest.approx(0.75)


def test_two_property_curve_is_eight_numbers():
    rig = _rig()
    rig.animations = {
        "a": {
            "bones": {
                "hip": {
                    "translate": [
                        {"time": 0.0, "x": 0, "y": 0},
                        {"time": 2.0, "x": 100, "y": 50, "curve": [0.5, 0, 0.5, 1]},
                    ]
                }
            }
        }
    }
    doc = to_spine_json(rig)
    frames = doc["animations"]["a"]["bones"]["hip"]["translate"]
    curve = frames[0]["curve"]
    # translate animates x AND y, so the runtime indexes 8 numbers. Four makes
    # it read past the array and NaN spreads through the bone transforms.
    assert len(curve) == 8
    # x segment: 0 -> 100 over time 0 -> 2
    assert curve[0] == pytest.approx(1.0)
    assert curve[1] == pytest.approx(0.0)
    # y segment: 0 -> 50 over the same span
    assert curve[4] == pytest.approx(1.0)
    assert curve[5] == pytest.approx(0.0)


def test_curve_moves_to_segment_start():
    rig = _rig()
    rig.animations = {
        "a": {
            "bones": {
                "hip": {
                    "rotate": [
                        {"time": 0.0, "angle": 0},
                        {"time": 1.0, "angle": 10},
                        {"time": 2.0, "angle": 0, "curve": [0.25, 0, 0.75, 1]},
                    ]
                }
            }
        }
    }
    doc = to_spine_json(rig)
    frames = doc["animations"]["a"]["bones"]["hip"]["rotate"]
    # The curve authored on frame 2 governs 1 -> 2, so it lands on frame 1.
    assert "curve" in frames[1]
    assert "curve" not in frames[2]


def test_stepped_curve_passes_through():
    rig = _rig()
    rig.animations = {
        "a": {
            "bones": {
                "hip": {
                    "rotate": [
                        {"time": 0.0, "angle": 0},
                        {"time": 1.0, "angle": 10, "curve": "stepped"},
                    ]
                }
            }
        }
    }
    doc = to_spine_json(rig)
    assert doc["animations"]["a"]["bones"]["hip"]["rotate"][0]["curve"] == "stepped"


def test_invalid_curve_shape_raises():
    rig = _rig()
    rig.animations = {
        "a": {
            "bones": {
                "hip": {
                    "rotate": [
                        {"time": 0.0, "angle": 0},
                        {"time": 1.0, "angle": 10, "curve": [0.5, 0.5]},
                    ]
                }
            }
        }
    }
    with pytest.raises(ValueError, match="curve"):
        to_spine_json(rig)


def test_serialized_document_is_json_round_trippable():
    doc = to_spine_json(_rig())
    assert json.loads(json.dumps(doc)) == doc
