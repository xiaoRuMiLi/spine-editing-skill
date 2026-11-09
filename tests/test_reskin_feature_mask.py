"""Feature masking wired into ``apply_reskin`` (PROJECT_LOG section 十, step 1b).

The mask has to run on the sprite pixels, after alignment, because that is the
frame the generator's own features were painted in. These tests pin down:

* the zones land where the rig says the eyes are, not somewhere else;
* the mask scales with the sprite (a 2x plate must not keep 1x zones);
* other pixels stay byte-identical, so masking cannot damage the plate;
* the report tells the caller what happened.
"""

from __future__ import annotations

import json
import os

import pytest
from PIL import Image

from spine_forge.assets import atlas as atlas_io
from spine_forge.core.rig import Rig
from spine_forge.reskin.replace import apply_reskin
from spine_forge.skins import faceplate

PLATE = 100
EYE_Y = 30.0  # eye sits above the bone origin, i.e. upper part of the plate
EYE_SIZE = 20


def rig_with_eye() -> Rig:
    data = {
        "skeleton": {"name": "test", "spine": "4.3", "width": 200, "height": 200},
        "bones": [{"name": "root"}, {"name": "head", "parent": "root", "x": 0.0, "y": 0.0}],
        "slots": [
            {"name": "head-base", "bone": "head", "attachment": "head-base"},
            {"name": "L_eye-iris", "bone": "head", "attachment": "L_eye-iris"},
        ],
        "skins": [
            {
                "name": "default",
                "attachments": {
                    "head-base": {
                        "head-base": {
                            "type": "region",
                            "x": 0.0,
                            "y": 0.0,
                            "width": float(PLATE),
                            "height": float(PLATE),
                        }
                    },
                    "L_eye-iris": {
                        "L_eye-iris": {
                            "x": 0.0,
                            "y": EYE_Y,
                            "width": EYE_SIZE,
                            "height": EYE_SIZE,
                        }
                    },
                },
            }
        ],
    }
    return Rig(data)


def atlas_and_page() -> tuple[atlas_io.Atlas, Image.Image]:
    text = """\
sheet.png
\tsize: 256, 256
\tformat: RGBA8888
\tfilter: Linear, Linear
\trepeat: none
head-base
\tbounds: 0, 0, 100, 100
"""
    atlas = atlas_io.parse(text)
    page = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    for x in range(PLATE):
        for y in range(PLATE):
            page.putpixel((x, y), (200, 120, 80, 255))
    return atlas, page


BASE = (16, 32, 48, 255)
BLOB = (220, 20, 20, 255)


def eye_centre_in_sprite(sprite_size: int) -> tuple[int, int]:
    """Where the rig's eye zone centre should land on a sprite of this size."""
    # Zone centre in plate frame: (PLATE/2, PLATE/2 - EYE_Y) because y flips.
    cx = PLATE / 2
    cy = PLATE / 2 - EYE_Y
    k = sprite_size / PLATE
    return (int(round(cx * k)), int(round(cy * k)))


def flat_sprite(size: int = PLATE, colour=BASE) -> Image.Image:
    return Image.new("RGBA", (size, size), colour)


def sprite_with_eye(size: int = PLATE, radius: int | None = None) -> Image.Image:
    """Flat plate plus a red blob where the generator painted an eye.

    A flat plate cannot show masking working, because the fill colour is sampled
    from the plate itself and comes out identical. The blob is the *generated*
    feature the mask must remove.
    """
    from PIL import ImageDraw

    image = flat_sprite(size)
    cx, cy = eye_centre_in_sprite(size)
    r = radius if radius is not None else int(round(EYE_SIZE / 2 * size / PLATE))
    ImageDraw.Draw(image).ellipse((cx - r, cy - r, cx + r, cy + r), fill=BLOB)
    return image


def run(sprite: Image.Image, **kwargs):
    rig = rig_with_eye()
    atlas, page = atlas_and_page()
    return apply_reskin(
        rig,
        atlas,
        page,
        slot="head-base",
        new_image=sprite,
        propagate=False,
        **kwargs,
    )


def region_pixels(result, region_name: str) -> Image.Image:
    region = result.atlas.find_region(region_name)[1]
    x, y, w, h = region.bounds
    return result.page_image.crop((x, y, x + w, y + h))


# ------------------------------------------------------------- the wiring


def test_mask_is_off_unless_requested():
    sprite = flat_sprite()
    result = run(sprite)
    assert result.features is None
    pasted = region_pixels(result, result.region_name)
    assert pasted.getpixel(eye_centre_in_sprite(PLATE)) == BASE


def test_mask_erases_the_eye_area_and_leaves_the_rest_alone():
    sprite = sprite_with_eye()
    result = run(sprite, blank_features=True)
    assert result.features is not None
    assert result.features.filled >= 1

    pasted = region_pixels(result, result.region_name)
    cx, cy = eye_centre_in_sprite(PLATE)
    # The generator's eye blob is gone, replaced by the plate colour around it.
    assert pasted.getpixel((cx, cy)) != BLOB
    # Corners far from every feature are untouched, byte for byte.
    assert pasted.getpixel((2, 2)) == BASE
    assert pasted.getpixel((PLATE - 3, PLATE - 3)) == BASE


def test_mask_off_keeps_the_generated_eye():
    result = run(sprite_with_eye())
    pasted = region_pixels(result, result.region_name)
    cx, cy = eye_centre_in_sprite(PLATE)
    assert pasted.getpixel((cx, cy)) == BLOB


def test_zones_scale_with_the_sprite():
    """A plate drawn twice as large must get zones twice as far from the corner."""
    big = 2 * PLATE
    result = run(sprite_with_eye(big), blank_features=True)
    pasted = region_pixels(result, result.region_name)
    cx, cy = eye_centre_in_sprite(big)
    assert pasted.getpixel((cx, cy)) != BLOB
    # The eye sits at (100, 40) on a 2x sprite; (50, 20) is 50px away, outside
    # the scaled zone, so a blob left there would mean the zones never scaled.
    assert pasted.getpixel((50, 20)) == BASE


def test_padding_widens_the_erased_area():
    from PIL import ImageDraw

    sprite = sprite_with_eye()
    cx, cy = eye_centre_in_sprite(PLATE)
    edge = (cx + int(EYE_SIZE / 2) + 4, cy)  # 4px outside the bare eye zone
    ImageDraw.Draw(sprite).point(edge, fill=(0, 255, 0, 255))

    tight = run(sprite.copy(), blank_features=True, feature_padding=0.0, feature_feather=0)
    wide = run(sprite.copy(), blank_features=True, feature_padding=30.0, feature_feather=0)
    assert region_pixels(tight, tight.region_name).getpixel(edge) == (0, 255, 0, 255)
    assert region_pixels(wide, wide.region_name).getpixel(edge) != (0, 255, 0, 255)


def test_report_describes_the_masking():
    result = run(flat_sprite(), blank_features=True)
    payload = result.report()
    assert payload["features"] is not None
    assert "L_eye-iris" in payload["features"]["zones"]
    assert payload["features"]["filled"] >= 1
    assert payload["features"]["mode"] == "fill"
    assert any("blanked" in note for note in payload["notes"])


def test_pixels_outside_the_region_are_never_touched():
    rig = rig_with_eye()
    atlas, page = atlas_and_page()
    # A sentinel pixel on the page, outside every region.
    page.putpixel((250, 250), (1, 2, 3, 255))
    result = apply_reskin(
        rig, atlas, page, slot="head-base", new_image=sprite_with_eye(),
        propagate=False, blank_features=True,
    )
    assert result.page_image.getpixel((250, 250)) == (1, 2, 3, 255)


# ------------------------------------------------------- real owl geometry


OWL_JSON = os.path.join("examples", "owl", "export", "owl-pro.json")


@pytest.mark.skipif(not os.path.isfile(OWL_JSON), reason="owl example not present")
def test_real_owl_plate_zones_are_inside_the_plate():
    with open(OWL_JSON, encoding="utf-8") as handle:
        rig = Rig(json.load(handle))
    left, top, width, height = faceplate.plate_geometry(rig, "head-base")
    assert width > 0 and height > 0

    zones = faceplate.feature_zones(
        rig, "head-base", image_size=(int(width), int(height)), padding=8.0
    )
    names = {zone.name for zone in zones}
    assert {"L_eye-iris", "R_eye-iris", "beak"} <= names
    for zone in zones:
        assert 0 <= zone.cx <= width
        assert 0 <= zone.cy <= height
        assert zone.rx > 0 and zone.ry > 0
