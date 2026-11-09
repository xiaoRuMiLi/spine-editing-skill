"""Face-plate feature blanking: positions come from the rig, not from detection.

The behaviour being pinned: a generated head plate must not keep its own eyes or
beak, because the rig draws those itself. Prompting failed at this (negative list
named them, the model painted them anyway), so the test suite pins the geometric
route instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from spine_forge.core.rig import Rig
from spine_forge.skins import faceplate

OWL_RIG = Path(__file__).resolve().parents[1] / "examples" / "owl" / "export" / "owl-pro.json"


def rig_data() -> dict:
    """Head bone at (50, 10); eyes hang off a control bone offset (0, 20)."""
    return {
        "skeleton": {"name": "t"},
        "bones": [
            {"name": "root"},
            {"name": "head", "parent": "root", "x": 50.0, "y": 10.0},
            {"name": "control", "parent": "head", "y": 20.0},
        ],
        "slots": [
            {"name": "head-base", "bone": "head", "attachment": "head-base"},
            {"name": "L_eye-iris", "bone": "control", "attachment": "L_eye-iris"},
            {"name": "beak", "bone": "head", "attachment": "beak"},
            {"name": "body", "bone": "head", "attachment": "body"},
        ],
        "skins": [
            {
                "name": "default",
                "attachments": {
                    "head-base": {"head-base": {"x": 0.0, "y": 0.0, "width": 200, "height": 100}},
                    "L_eye-iris": {"L_eye-iris": {"x": -40.0, "y": 0.0, "width": 40, "height": 40}},
                    "beak": {"beak": {"x": 0.0, "y": -40.0, "width": 20, "height": 20}},
                    "body": {"body": {"x": 0.0, "y": 0.0, "width": 200, "height": 100}},
                },
            }
        ],
    }


def plate(size=(200, 100)) -> Image.Image:
    """Opaque plate with a distinct patch where the eye is, so erasing is visible."""
    width, height = size
    image = Image.new("RGBA", size, (180, 150, 120, 255))
    # Eye zone lands at pixel (60, 30) for the synthetic rig above.
    for x in range(40, min(80, width)):
        for y in range(10, min(50, height)):
            image.putpixel((x, y), (20, 40, 200, 255))
    return image


# --------------------------------------------------------------- primitives


def test_is_feature_matches_names_case_insensitively():
    assert faceplate.is_feature("L_eye-iris")
    assert faceplate.is_feature("BEAK")
    assert faceplate.is_feature("R_eye-pupil")
    assert not faceplate.is_feature("body")
    assert not faceplate.is_feature("leaf-3")


def test_is_feature_accepts_custom_keywords():
    assert not faceplate.is_feature("wing", keywords=("eye",))
    assert faceplate.is_feature("wing", keywords=("wing",))


def test_region_attachment_box_is_centre_and_size():
    assert faceplate.attachment_box({"x": 5, "y": 6, "width": 30, "height": 40}) == (5.0, 6.0, 30.0, 40.0)


def test_mesh_attachment_has_no_region_box():
    """Regression: reading a vertex stream as x/y pairs produced 300px eye zones."""
    mesh = {"type": "mesh", "vertices": [2.0, 9.0, 212.0, 3.35, 0.5, 10.0], "width": 999, "height": 999}
    assert faceplate.attachment_box(mesh) is None


def test_mesh_points_decode_unweighted_and_weighted_runs():
    rig = Rig(rig_data())
    # unweighted: [0, x, y]; weighted: [1, boneIndex, x, y, weight]
    mesh = {"type": "mesh", "vertices": [0, 0.0, 0.0, 1, 2, 5.0, 7.0, 1.0]}
    points = faceplate.mesh_points(rig, mesh, "head", "head")
    assert points[0] == (0.0, 0.0)          # unweighted, plate bone == slot bone
    assert points[1] == (5.0, 27.0)         # weighted to control (y += 20) then head (y += 10)


def test_mesh_points_returns_empty_on_bad_stream():
    rig = Rig(rig_data())
    assert faceplate.mesh_points(rig, {"type": "mesh", "vertices": [1, 99, 0, 0, 1]}, "head", "head") == []


def test_bone_matrix_accumulates_parent_translation():
    rig = Rig(rig_data())
    matrix = faceplate.bone_matrix(rig, "control", "head")
    assert faceplate._mat_apply(matrix, 0.0, 0.0) == (0.0, 20.0)


def test_bone_matrix_identity_for_same_bone():
    rig = Rig(rig_data())
    assert faceplate.bone_matrix(rig, "head", "head") == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def test_bone_matrix_rejects_foreign_bone():
    rig = Rig(rig_data())
    with pytest.raises(ValueError, match="not a descendant"):
        faceplate.bone_matrix(rig, "root", "head")


# ------------------------------------------------------------------ zones


def test_zones_use_bone_local_units_without_image_size():
    rig = Rig(rig_data())
    zones = {z.name: z for z in faceplate.feature_zones(rig, "head-base")}
    assert set(zones) == {"L_eye-iris", "beak"}
    assert zones["L_eye-iris"].cx == pytest.approx(-40.0)
    assert zones["L_eye-iris"].cy == pytest.approx(20.0)  # control offset applied


def test_zones_map_into_plate_pixels():
    """Plate is 200x100 units at (0,0): 1 unit == 1 px, y flipped about +50."""
    rig = Rig(rig_data())
    zones = {z.name: z for z in faceplate.feature_zones(rig, "head-base", image_size=(200, 100))}
    eye = zones["L_eye-iris"]
    assert eye.cx == pytest.approx(60.0)
    assert eye.cy == pytest.approx(30.0)
    assert eye.rx == pytest.approx(20.0)


def test_padding_expands_zone():
    rig = Rig(rig_data())
    plain = {z.name: z for z in faceplate.feature_zones(rig, "head-base", image_size=(200, 100))}
    padded = {
        z.name: z
        for z in faceplate.feature_zones(rig, "head-base", image_size=(200, 100), padding=6.0)
    }
    assert padded["L_eye-iris"].rx == pytest.approx(plain["L_eye-iris"].rx + 6.0)


def test_plate_slot_without_attachment_is_rejected():
    rig = Rig(rig_data())
    rig.data["slots"].append({"name": "empty", "bone": "head", "attachment": None})
    with pytest.raises(ValueError, match="no attachment"):
        faceplate.feature_zones(rig, "empty")


def test_map_zones_follows_resize():
    zone = faceplate.FeatureZone(name="eye", cx=100.0, cy=50.0, rx=10.0, ry=10.0)
    mapped = faceplate.map_zones([zone], (400, 200), (0.0, 0.0, 200.0, 100.0))[0]
    assert (mapped.cx, mapped.cy, mapped.rx, mapped.ry) == (50.0, 25.0, 5.0, 5.0)


# ----------------------------------------------------------------- pixels


def test_fill_mode_erases_the_feature_and_keeps_the_rest():
    rig = Rig(rig_data())
    image = plate()
    zones = faceplate.feature_zones(rig, "head-base", image_size=image.size)
    result, report = faceplate.blank_features(image, zones)

    assert report.filled == len(zones)
    # Inside the eye zone: no more blue.
    r, g, b, a = result.getpixel((60, 30))
    assert b < 150 and a == 255
    # Far outside every zone: byte-identical.
    assert result.getpixel((10, 10)) == image.getpixel((10, 10))
    assert result.getpixel((190, 90)) == image.getpixel((190, 90))


def test_clear_mode_makes_the_zone_transparent():
    rig = Rig(rig_data())
    image = plate()
    zones = faceplate.feature_zones(rig, "head-base", image_size=image.size)
    result, _ = faceplate.blank_features(image, zones, mode="clear", feather=0)
    assert result.getpixel((60, 30))[3] == 0


def test_second_pass_does_not_bring_the_feature_back():
    """Re-blanking is not byte-idempotent (feathering re-blurs the edge), but the
    feature colour must never reappear."""
    rig = Rig(rig_data())
    zones = faceplate.feature_zones(rig, "head-base", image_size=(200, 100))
    once, _ = faceplate.blank_features(plate(), zones)
    twice, _ = faceplate.blank_features(once, zones)
    r, g, b, a = twice.getpixel((60, 30))
    assert b < 150 and a == 255


def test_zone_outside_the_image_is_skipped_not_drawn():
    image = plate((50, 50))
    zone = faceplate.FeatureZone(name="eye", cx=500.0, cy=500.0, rx=10.0, ry=10.0)
    result, report = faceplate.blank_features(image, [zone])
    assert report.skipped == ["eye"] and report.filled == 0
    assert list(result.getdata()) == list(image.getdata())


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="unknown blanking mode"):
        faceplate.blank_features(plate(), [], mode="blur")


# ------------------------------------------------------- real owl regression


@pytest.mark.skipif(not OWL_RIG.is_file(), reason="owl example not present")
def test_owl_rig_yields_eye_and_beak_zones():
    rig = Rig(json.loads(OWL_RIG.read_text(encoding="utf-8")))
    zones = faceplate.feature_zones(rig, "head-base", image_size=(597, 474))
    names = {z.name for z in zones}
    assert {"L_eye-iris", "R_eye-iris", "beak"} <= names

    # The eyes sit either side of the plate centre and are far smaller than it:
    # a mis-decoded vertex stream produced 300px-wide ellipses here.
    left = next(z for z in zones if z.name == "L_eye-iris")
    right = next(z for z in zones if z.name == "R_eye-iris")
    assert abs(left.cx - right.cx) > 60
    assert left.rx < 597 / 3 and right.rx < 597 / 3
    for zone in zones:
        assert 0 <= zone.cx <= 597 and 0 <= zone.cy <= 474
