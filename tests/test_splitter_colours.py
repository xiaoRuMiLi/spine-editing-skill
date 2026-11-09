"""Colour splitter: the rules that took real debugging to get right.

Every assertion here stands for a bug that actually happened on the girl picture:
the light-green shorts being swallowed by the green hair family, a sandal strap
cutting one sock into three files, the "AI生成" watermark becoming a body part.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from spine_forge.splitter.colors import split_by_colour

W, H = 240, 340

HAIR = (60, 170, 80)
SHIRT = (150, 110, 70)
SKIN = (220, 70, 80)
SHORTS = (150, 190, 120)
TEAL = (60, 180, 175)
BLUE = (70, 120, 190)
PAPER = (250, 250, 246)


def canvas() -> Image.Image:
    image = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle((65, 20, 175, 90), fill=HAIR)        # hair, top
    draw.rectangle((55, 95, 185, 200), fill=SHIRT)      # shirt, torso
    draw.rectangle((18, 125, 50, 200), fill=SKIN)       # arm, left
    draw.rectangle((65, 210, 175, 245), fill=SHORTS)    # shorts
    draw.rectangle((60, 250, 100, 302), fill=SKIN)      # leg, left
    draw.rectangle((140, 250, 180, 302), fill=SKIN)     # leg, right
    draw.rectangle((60, 302, 100, 322), fill=BLUE)      # sock, left
    draw.rectangle((140, 302, 180, 322), fill=BLUE)     # sock, right
    draw.rectangle((60, 322, 100, 336), fill=TEAL)      # shoe, left
    draw.rectangle((140, 322, 180, 336), fill=TEAL)     # shoe, right
    return image


def run(tmp_path, image: Image.Image):
    source = os.path.join(tmp_path, "source.png")
    image.save(source)
    out = os.path.join(tmp_path, "parts")
    return source, split_by_colour(source, out), out


def test_parts_keep_full_canvas_and_stay_disjoint(tmp_path):
    _, parts, _ = run(tmp_path, canvas())
    assert len(parts) >= 6

    masks = []
    for part in parts:
        layer = Image.open(part.image_path)
        assert layer.size == (W, H), "parts must stay aligned to the source canvas"
        masks.append(np.asarray(layer)[:, :, 3] > 0)

    stacked = np.sum(np.stack(masks), axis=0)
    assert stacked.max() <= 1, "one pixel may belong to at most one part"


def test_names_are_unique(tmp_path):
    _, parts, _ = run(tmp_path, canvas())
    names = [part.name for part in parts]
    assert len(names) == len(set(names))


def test_hair_and_shorts_do_not_swap_families(tmp_path):
    """Green hair vs light-green shorts: different lightness, same hue family."""
    _, parts, _ = run(tmp_path, canvas())
    by_name = {part.name: part for part in parts}
    assert "hair" in by_name, [p.name for p in parts]
    assert "shorts" in by_name, [p.name for p in parts]
    assert by_name["hair"].box[1] < 100 < by_name["shorts"].box[1]


def test_sock_and_shoe_merge_into_one_foot(tmp_path):
    image = canvas()
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 310, 100, 314), fill=TEAL)  # strap over the left sock
    draw.rectangle((140, 310, 180, 314), fill=TEAL)  # strap over the right sock
    _, parts, _ = run(tmp_path, image)
    feet = [p for p in parts if p.name.startswith("foot")]
    assert len(feet) == 2, [p.name for p in parts]
    for foot in feet:
        assert foot.box[3] - foot.box[1] >= 25, "a foot must cover sock and shoe"
    assert not [p for p in parts if p.name.startswith(("sock", "shoe"))], (
        "sock and shoe must not survive as separate parts"
    )


def test_greyscale_watermark_far_from_the_figure_is_not_a_part(tmp_path):
    image = canvas()
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, 48, 16), outline=(180, 180, 180), width=1)
    draw.text((8, 5), "AI", fill=(190, 190, 190))
    _, parts, _ = run(tmp_path, image)
    corner = [p for p in parts if p.box[2] < 55 and p.box[3] < 25]
    assert not corner, f"the corner watermark must be dropped, got {[p.name for p in corner]}"


def test_background_is_never_part_of_a_part(tmp_path):
    _, parts, _ = run(tmp_path, canvas())
    for part in parts:
        alpha = np.asarray(Image.open(part.image_path))[:, :, 3]
        assert alpha[0, 0] == 0
        assert alpha[-1, -1] == 0


# ------------------------------------------------------------- pipeline glue


def test_colour_splitter_plugs_into_the_stage(tmp_path):
    """The stage must produce parts.json + both previews for the colour splitter."""
    from spine_forge.stages import split as split_stage

    source = os.path.join(tmp_path, "source.png")
    canvas().save(source)
    out = os.path.join(tmp_path, "out")

    result = split_stage.run(source, out, kind="colour")
    assert result["parts"] >= 6
    assert os.path.isfile(os.path.join(out, "parts.json"))
    assert os.path.isfile(os.path.join(out, "preview", "parts_sheet.png"))
    assert os.path.isfile(os.path.join(out, "preview", "reassembly.png"))
    assert 0.5 <= result["coverage"] <= 1.0

    with open(os.path.join(out, "parts.json"), encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["source"]["splitter"] == "ColourSplitter"
    assert payload["check"]["coverage"] > 0.5
    assert all("box" in part and "center" in part for part in payload["parts"])


def test_unknown_splitter_is_rejected(tmp_path):
    from spine_forge.stages import split as split_stage

    source = os.path.join(tmp_path, "source.png")
    canvas().save(source)
    with pytest.raises(ValueError):
        split_stage.run(source, os.path.join(tmp_path, "out"), kind="magic")

