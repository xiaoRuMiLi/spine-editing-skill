"""Rig builder tests: parts.json -> editable bone hierarchy."""

from __future__ import annotations

from spine_forge.stages.rig import build_rig


def _parts_doc() -> dict:
    """Two stacked parts, upper centred at x=50 y=25, lower at x=50 y=75."""
    return {
        "source": {"path": "/tmp/src.png", "splitter": "fake"},
        "parts": [
            {
                "name": "part_01",
                "image": "parts/part_01.png",
                "width": 40,
                "height": 40,
                "box": [30, 5, 70, 45],
                "center": [50.0, 25.0],
            },
            {
                "name": "part_02",
                "image": "parts/part_02.png",
                "width": 40,
                "height": 40,
                "box": [30, 55, 70, 95],
                "center": [50.0, 75.0],
            },
        ],
    }


def test_root_first_then_parts():
    rig = build_rig(_parts_doc())
    assert rig["bones"][0]["name"] == "root"
    assert [b["name"] for b in rig["bones"][1:]] == ["part_01", "part_02"]


def test_each_part_hangs_off_the_previous():
    rig = build_rig(_parts_doc())
    bones = {b["name"]: b for b in rig["bones"]}
    assert bones["part_01"]["parent"] == "root"
    assert bones["part_02"]["parent"] == "part_01"


def test_coordinates_flip_y_and_chain_relatively():
    rig = build_rig(_parts_doc())
    bones = {b["name"]: b for b in rig["bones"]}
    # Canvas is 70 wide (max right) x 95 tall. First part sits at x=50 => 15
    # right of centre, and y=95-25=70 above the bottom edge.
    assert bones["part_01"]["x"] == 15.0
    assert bones["part_01"]["y"] == 70.0
    # The second part is 50 px BELOW the first on the image, which is -50 in
    # Spine's upward-growing axis.
    assert bones["part_02"]["x"] == 0.0
    assert bones["part_02"]["y"] == -50.0


def test_slots_and_attachments_mirror_bones():
    rig = build_rig(_parts_doc())
    assert [s["name"] for s in rig["slots"]] == ["part_01", "part_02"]
    assert rig["attachments"]["part_01"]["width"] == 40
    # Attachments centre the image on its bone so rotation looks right.
    assert rig["attachments"]["part_01"]["x"] == -20.0
    assert rig["attachments"]["part_01"]["y"] == -20.0


def test_skeleton_size_derived_from_bounds():
    rig = build_rig(_parts_doc())
    assert rig["skeleton"]["width"] == 70
    assert rig["skeleton"]["height"] == 95


def test_source_parts_recorded_for_build():
    rig = build_rig(_parts_doc())
    assert rig["source_parts"] == ["parts/part_01.png", "parts/part_02.png"]
