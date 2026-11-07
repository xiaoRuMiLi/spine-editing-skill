"""apply_reskin: the end-to-end composition step.

Covers the two data-integrity rules that cost real debugging time:

* An empty slot (``attachment: null``) must be refused, not silently given new
  artwork. Fabricating an attachment leaves the slot and the skin disagreeing
  about whether the slot has art, and the runtime reports an undefined pose.
* ``width``/``height`` must keep the numeric style the source document used.
  Spine round-trips whichever type it was given; mixing int and float inside one
  document is what upsets the parser.
"""

from __future__ import annotations

import pytest
from PIL import Image

from spine_forge.assets import atlas as atlas_io
from spine_forge.assets import images as atlas_images
from spine_forge.core.rig import Rig
from spine_forge.reskin.replace import apply_reskin


def base_rig(width_type=float) -> Rig:
    data = {
        "skeleton": {"name": "test", "spine": "4.3", "width": 200, "height": 200},
        "bones": [
            {"name": "root"},
            {"name": "head", "parent": "root", "x": 50.0, "y": 10.0, "length": 40.0},
            {"name": "control", "parent": "head", "y": 100.0},
        ],
        "slots": [
            {"name": "head-base", "bone": "head", "attachment": "head-base"},
            {"name": "eye", "bone": "control", "attachment": "eye"},
            {"name": "hidden", "bone": "control", "attachment": None},
        ],
        "skins": [
            {
                "name": "default",
                "attachments": {
                    "head-base": {
                        "head-base": {
                            "type": "mesh",
                            "width": width_type(100),
                            "height": width_type(100),
                            "uvs": [0, 0],
                            "vertices": [0, 50.0, 50.0],
                        }
                    },
                    "eye": {"eye": {"x": -20.0, "y": 30.0, "width": 40, "height": 40}},
                    "hidden": {"hidden": {"x": 0.0, "y": 0.0, "width": 10, "height": 10}},
                },
            }
        ],
    }
    return Rig(data)


def base_atlas_and_page():
    text = """\
sheet.png
\tsize: 256, 256
\tformat: RGBA8888
\tfilter: Linear, Linear
\trepeat: none
head-base
\tbounds: 0, 0, 100, 100
eye
\tbounds: 100, 0, 40, 40
hidden
\tbounds: 150, 0, 10, 10
"""
    atlas = atlas_io.parse(text)
    page = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    # Paint opaque blocks so opaque-box measurement has something to find.
    for x in range(0, 100):
        for y in range(0, 100):
            page.putpixel((x, y), (200, 120, 80, 255))
    for x in range(100, 140):
        for y in range(0, 40):
            page.putpixel((x, y), (30, 30, 200, 255))
    return atlas, page


def sprite(size: int = 100) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for x in range(size):
        for y in range(size):
            image.putpixel((x, y), (90, 180, 90, 255))
    return image


# --------------------------------------------------------------- happy path


def test_returns_a_new_rig_and_leaves_input_untouched():
    rig = base_rig()
    before = rig.copy().data
    atlas, page = base_atlas_and_page()

    result = apply_reskin(rig, atlas, page, slot="head-base", new_image=sprite())

    assert rig.data == before, "apply_reskin must not mutate the caller's rig"
    assert result.rig is not rig


def test_new_region_appended_without_touching_old_bounds():
    atlas, page = base_atlas_and_page()
    original = [r.bounds for r in atlas.pages[0].regions]

    result = apply_reskin(base_rig(), atlas, page, slot="head-base", new_image=sprite())

    current = [r.bounds for r in result.atlas.pages[0].regions][: len(original)]
    assert current == original, "existing regions must keep their bounds"
    assert result.region_name in [r.name for r in result.atlas.pages[0].regions]


def test_attachment_points_at_the_new_region():
    atlas, page = base_atlas_and_page()
    result = apply_reskin(base_rig(), atlas, page, slot="head-base", new_image=sprite())
    att = result.rig.attachment("head-base", "head-base")
    assert att["path"] == result.region_name


def test_reports_scale_and_boxes():
    atlas, page = base_atlas_and_page()
    result = apply_reskin(
        base_rig(), atlas, page, slot="head-base", new_image=sprite(50)
    )
    report = result.report()
    assert report["scale"] == pytest.approx(0.5, rel=0.05)
    assert "source_box" in report
    assert "target_box" in report


# ----------------------------------------------------------- empty slot guard


def test_empty_slot_is_rejected():
    """An unset slot must not be silently given artwork.

    This is the crash guard: slot says it has no attachment while the skin now
    has one, and the runtime reads that as an undefined pose.
    """
    atlas, page = base_atlas_and_page()
    with pytest.raises(ValueError, match="currently empty"):
        apply_reskin(base_rig(), atlas, page, slot="hidden", new_image=sprite())


def test_empty_slot_left_out_of_the_skin_on_success():
    atlas, page = base_atlas_and_page()
    result = apply_reskin(base_rig(), atlas, page, slot="head-base", new_image=sprite())

    slot = result.rig.slot("hidden")
    assert slot is not None
    assert slot["attachment"] is None


def test_unknown_slot_is_rejected():
    atlas, page = base_atlas_and_page()
    with pytest.raises(ValueError, match="unknown slot"):
        apply_reskin(base_rig(), atlas, page, slot="nope", new_image=sprite())


# ------------------------------------------------------------ numeric typing


@pytest.mark.parametrize("width_type", [int, float])
def test_width_height_keep_source_numeric_type(width_type):
    atlas, page = base_atlas_and_page()
    result = apply_reskin(
        base_rig(width_type), atlas, page, slot="head-base", new_image=sprite()
    )
    att = result.rig.attachment("head-base", "head-base")
    assert isinstance(att["width"], width_type)
    assert isinstance(att["height"], width_type)


def test_width_height_are_never_floats_when_source_is_int():
    """Regression: a propagated float width (e.g. 82.7595) breaks parsing."""
    atlas, page = base_atlas_and_page()
    result = apply_reskin(
        base_rig(int), atlas, page, slot="head-base", new_image=sprite()
    )
    att = result.rig.attachment("head-base", "head-base")
    assert float(att["width"]).is_integer()
    assert float(att["height"]).is_integer()


# ------------------------------------------------------------------ page size


def test_page_grows_when_new_art_does_not_fit():
    atlas, page = base_atlas_and_page()
    # Existing content occupies y 0..100; shrink the page so a full-size sprite
    # no longer fits below it, then assert the page grew to hold it.
    atlas.pages[0].size = (256, 128)
    page = page.crop((0, 0, 256, 128))

    result = apply_reskin(base_rig(), atlas, page, slot="head-base", new_image=sprite(80))
    assert result.page_image.height >= 128
    # Every region, old and new, must still lie inside the page.
    for region in result.atlas.pages[0].regions:
        _, y, _, h = region.bounds
        assert y + h <= result.page_image.height


def test_region_bounds_match_sprite_size():
    atlas, page = base_atlas_and_page()
    result = apply_reskin(
        base_rig(), atlas, page, slot="head-base", new_image=sprite(80)
    )
    region = result.atlas.find_region(result.region_name)
    assert region is not None
    _, reg = region
    assert reg.size == (80, 80)
