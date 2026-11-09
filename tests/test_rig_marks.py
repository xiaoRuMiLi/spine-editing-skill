"""Rig module: reading ring marks and turning joints into Spine bones.

The behaviours pinned here are the ones that were wrong at least once while
building the girl's skeleton: filled dark shapes being mistaken for marks, one
ring split by a hair strand being read as two joints, and the y-axis flip between
image space and Spine space.
"""

from __future__ import annotations

import json
import os

import pytest
from PIL import Image, ImageDraw

from spine_forge.rig import Joint, Skeleton, merge_close_marks, read_marks, render_panel
from spine_forge.rig.markers import Mark, detect_marks, nearest_mark
from spine_forge.rig.skeleton import load_spec, save_spec
from spine_forge.rig.constraints import add_ik_targets, bend_sign, default_constraints, validate


def ringed(tmp_path, rings, filled=(), name="marked.png"):
    """Draw hollow rings (marks) and optional filled dots (not marks)."""
    image = Image.new("RGB", (320, 260), (250, 250, 246))
    draw = ImageDraw.Draw(image)
    for x, y, radius in rings:
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], outline=(0, 0, 0), width=4)
    for x, y, radius in filled:
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(0, 0, 0))
    path = os.path.join(tmp_path, name)
    image.save(path)
    return path


# ------------------------------------------------------------------ markers


def test_hollow_rings_are_detected(tmp_path):
    path = ringed(tmp_path, [(60, 60, 11), (160, 80, 10), (250, 200, 12)])
    marks = read_marks(path)
    assert len(marks) == 3
    found = sorted((round(m.x / 10) * 10, round(m.y / 10) * 10) for m in marks)
    assert found == [(60, 60), (160, 80), (250, 200)]


def test_filled_dark_shapes_are_not_marks(tmp_path):
    """A pupil and an eyebrow were read as joints in the first attempt."""
    path = ringed(tmp_path, [(60, 60, 11)], filled=[(160, 120, 9), (200, 200, 14)])
    marks = read_marks(path)
    assert len(marks) == 1
    assert abs(marks[0].x - 60) < 3 and abs(marks[0].y - 60) < 3


def test_two_holes_of_one_ring_are_merged(tmp_path):
    """A hair strand cutting a ring leaves two holes a few pixels apart."""
    left = Mark(x=100.0, y=100.0, area=60)
    right = Mark(x=108.0, y=102.0, area=40)
    merged = merge_close_marks([left, right])
    assert len(merged) == 1
    assert 100 <= merged[0].x <= 108


def test_nearest_mark_reports_distance(tmp_path):
    marks = [Mark(x=10, y=10), Mark(x=100, y=100)]
    mark, distance = nearest_mark(marks, 95, 96)
    assert mark is not None and abs(mark.x - 100) < 1e-6
    assert 6 < distance < 8


def test_mark_count_on_a_blank_page_is_zero(tmp_path):
    path = ringed(tmp_path, [])
    assert detect_marks(path) == []


# ----------------------------------------------------------------- skeleton


def sample_skeleton() -> Skeleton:
    skeleton = Skeleton(name="test")
    skeleton.add(Joint("root", None, (100, 200), (100, 200)))
    skeleton.add(Joint("spine", "root", (100, 200), (100, 120)))
    skeleton.add(Joint("head", "spine", (100, 120), (100, 40)))
    skeleton.add(Joint("arm", "spine", (140, 140), (200, 180)))
    return skeleton


def test_unknown_parent_is_rejected():
    skeleton = Skeleton()
    with pytest.raises(ValueError):
        skeleton.add(Joint("arm", "missing", (0, 0), (10, 10)))


def test_duplicate_joint_is_rejected():
    skeleton = Skeleton()
    skeleton.add(Joint("root", None, (0, 0), (0, 0)))
    with pytest.raises(ValueError):
        skeleton.add(Joint("root", None, (1, 1), (1, 1)))


def test_y_axis_flips_once_into_spine_space():
    """Image y grows DOWN, Spine y grows UP; a bone pointing up on screen must be
    +90 degrees in the document, not -90."""
    bones = {b["name"]: b for b in sample_skeleton().spine_bones(canvas_height=200)}
    assert bones["spine"]["rotation"] == pytest.approx(90.0, abs=0.01)
    assert bones["spine"]["y"] == pytest.approx(0.0, abs=0.01)
    assert bones["head"]["length"] == pytest.approx(80.0, abs=0.01)


def test_child_offset_is_in_the_parent_rotated_frame():
    bones = {b["name"]: b for b in sample_skeleton().spine_bones(canvas_height=200)}
    head = bones["head"]
    # Head continues along the spine, so its local offset is straight ahead.
    assert head["x"] == pytest.approx(80.0, abs=0.01)
    assert head["y"] == pytest.approx(0.0, abs=0.01)
    assert head["rotation"] == pytest.approx(0.0, abs=0.01)

    arm = bones["arm"]
    # Arm branches sideways from the spine's midpoint, so it does NOT sit at the
    # parent's tip -- the offset has to be computed, not assumed.
    assert arm["parent"] == "spine"
    assert arm["x"] > 0 and arm["y"] != 0


def test_zero_length_control_bone_stays_put():
    skeleton = Skeleton()
    skeleton.add(Joint("root", None, (50, 50), (50, 50)))
    skeleton.add(Joint("shoulder", "root", (80, 60), (80, 60)))
    bones = {b["name"]: b for b in skeleton.spine_bones(canvas_height=100)}
    assert bones["shoulder"]["length"] == 0
    assert bones["shoulder"]["rotation"] == 0


# --------------------------------------------------------------- spec + panel


def test_spec_round_trip(tmp_path):
    skeleton = sample_skeleton()
    path = save_spec(skeleton, os.path.join(tmp_path, "joints.json"))
    loaded = load_spec(path)
    assert [j.name for j in loaded] == [j.name for j in skeleton.joints]
    assert loaded[3].base == (140.0, 140.0)


def test_panel_renders_at_art_size_plus_table(tmp_path):
    path = ringed(tmp_path, [(60, 60, 11)])
    out = os.path.join(tmp_path, "panel.png")
    render_panel(path, sample_skeleton().joints, out)
    panel = Image.open(out)
    assert panel.width > 320 and panel.height >= 260


def test_stage_writes_bones_and_previews(tmp_path):
    from spine_forge.stages import skeleton as stage

    art = ringed(tmp_path, [(60, 60, 11)], name="art.png")
    marks = ringed(tmp_path, [(60, 60, 11), (120, 180, 11)], name="marks.png")
    spec = os.path.join(tmp_path, "joints.json")
    save_spec(sample_skeleton(), spec)

    out = os.path.join(tmp_path, "out")
    result = stage.run(art, out, marks_path=marks, spec_path=spec, name="hero")

    assert result["marks"] == 2
    assert result["bones"] == 4
    assert os.path.isfile(os.path.join(out, "bones.json"))
    assert os.path.isfile(os.path.join(out, "skeleton_panel.png"))
    assert os.path.isfile(os.path.join(out, "marks_numbered.png"))

    with open(os.path.join(out, "bones.json"), encoding="utf-8") as handle:
        payload = json.load(handle)
    assert [b["name"] for b in payload["spine_bones"]] == ["root", "spine", "head", "arm"]


# ------------------------------------------------------------- constraints


def rig_with_ik() -> Skeleton:
    skeleton = Skeleton(name="ik")
    skeleton.add(Joint("root", None, (100, 200), (100, 200)))
    skeleton.add(Joint("hips", "root", (100, 200), (100, 150)))
    skeleton.add(Joint("chest", "hips", (100, 150), (100, 100)))
    skeleton.add(Joint("head", "chest", (100, 100), (100, 60)))
    skeleton.add(Joint("head-control", "chest", (100, 100), (100, 100)))
    skeleton.add(Joint("hair", "head", (95, 70), (70, 90)))
    for side, x in (("r", 80), ("l", 120)):
        skeleton.add(Joint(f"leg_{side}", "hips", (x, 200), (x, 250)))
        skeleton.add(Joint(f"shin_{side}", f"leg_{side}", (x, 250), (x, 290)))
        skeleton.add(Joint(f"foot_{side}", f"shin_{side}", (x, 290), (x, 310)))
        skeleton.add(Joint(f"arm_{side}", "chest", (x, 110), (x + 10, 140)))
        skeleton.add(Joint(f"fore_{side}", f"arm_{side}", (x + 10, 140), (x + 45, 128)))
        skeleton.add(Joint(f"hand_{side}", f"fore_{side}", (x + 45, 128), (x + 60, 120)))
        skeleton.add(Joint(f"ik_foot_{side}", "root", (x, 290), (x, 290)))
        skeleton.add(Joint(f"ik_hand_{side}", "root", (x + 45, 128), (x + 45, 128)))
    return skeleton


def test_bend_sign_follows_the_drawn_pose():
    """Left arm bends the other way than the legs; a fixed False mirrored it onto
    the head in the first build."""
    skeleton = rig_with_ik()
    # leg_r: down-right then down-left -> negative cross
    assert bend_sign(skeleton, "leg_r", "shin_r") is False
    # arm_l: down-right then right-up -> positive cross
    assert bend_sign(skeleton, "arm_l", "fore_l") is True


def test_default_constraints_use_pose_bend_signs():
    constraints = {c["name"]: c for c in default_constraints(rig_with_ik())}
    assert constraints["foot_r"]["bendPositive"] is False
    assert constraints["hand_l"]["bendPositive"] is True


def test_default_constraints_shape_matches_the_sample():
    kinds = {c["name"]: c for c in default_constraints(rig_with_ik())}
    assert set(kinds) == {"foot_r", "foot_l", "hand_r", "hand_l", "head-follow", "hair-follow"}

    foot = kinds["foot_r"]
    assert foot["type"] == "ik"
    assert foot["bones"] == ["leg_r", "shin_r"]
    assert foot["target"] == "ik_foot_r"
    assert foot["bendPositive"] is False

    hair = kinds["hair-follow"]
    assert hair["type"] == "transform"
    assert hair["source"] == "head-control"
    assert hair["mixRotate"] < 1, "hair must lag, not follow rigidly"
    # No range block by default: a ``rotate.to.rotate.max`` window maps the source
    # angle into that window and threw the head ~60 degrees off on the first render.
    assert "properties" not in hair


def test_validate_catches_unknown_target_and_bone():
    skeleton = rig_with_ik()
    problems = validate(
        [
            {"type": "ik", "name": "bad", "target": "nope", "bones": ["leg_r", "ghost"]},
            {"type": "transform", "name": "t", "source": "missing", "bones": ["head"]},
        ],
        skeleton,
    )
    assert any("unknown IK target" in p for p in problems)
    assert any("ghost" in p for p in problems)
    assert any("unknown source" in p for p in problems)


def test_validate_accepts_the_default_set():
    skeleton = rig_with_ik()
    assert validate(default_constraints(skeleton), skeleton) == []


def test_add_ik_targets_creates_zero_length_bones():
    skeleton = Skeleton()
    skeleton.add(Joint("root", None, (0, 0), (0, 0)))
    add_ik_targets(skeleton, {"ik_foot_r": (10, 20)})
    target = skeleton.by_name("ik_foot_r")
    assert target is not None
    assert target.parent == "root"
    assert target.length == 0


def test_stage_emits_constraints_and_rejects_broken_ones(tmp_path):
    from spine_forge.stages import skeleton as stage

    art = ringed(tmp_path, [(60, 60, 11)], name="art.png")
    out = os.path.join(tmp_path, "out")

    good = os.path.join(tmp_path, "good.json")
    save_spec(rig_with_ik(), good, default_constraints(rig_with_ik()))
    result = stage.run(art, out, spec_path=good, snap=False)
    assert result["constraints"] == 6

    bad = os.path.join(tmp_path, "bad.json")
    skeleton = rig_with_ik()
    save_spec(
        skeleton,
        bad,
        [{"type": "ik", "name": "foot_r", "target": "nowhere", "bones": ["leg_r", "shin_r"]}],
    )
    with pytest.raises(ValueError):
        stage.run(art, os.path.join(tmp_path, "out2"), spec_path=bad, snap=False)


