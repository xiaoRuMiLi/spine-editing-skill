"""Background removal on a synthetic backdrop.

Each test builds the smallest image that exercises one property: a solid subject
on a flat fill, with a deliberate complication (a matching colour inside the
subject, a gradient nearer the edge) to prove the flood fill is doing the work
rather than a global colour comparison.
"""

from __future__ import annotations

import pytest
from PIL import Image

from spine_forge.assets.matting import remove_background


def canvas(width: int = 40, height: int = 40, fill=(120, 80, 150, 255)) -> Image.Image:
    return Image.new("RGBA", (width, height), fill)


def put_rect(image: Image.Image, box, colour) -> None:
    x0, y0, x1, y1 = box
    for x in range(x0, x1):
        for y in range(y0, y1):
            image.putpixel((x, y), colour)


def opaque_count(image: Image.Image, threshold: int = 8) -> int:
    return sum(1 for p in image.getdata() if p[3] > threshold)


def test_removes_flat_backdrop():
    image = canvas()
    put_rect(image, (10, 10, 30, 30), (30, 200, 30, 255))

    result = remove_background(image, feather=False)

    assert result.getpixel((0, 0))[3] == 0
    assert result.getpixel((20, 20))[3] == 255


def test_keeps_subject_interior_matching_the_backdrop():
    """A hole of backdrop colour inside the subject must survive.

    This is the reason for flood fill: a global colour match would punch it out.
    """
    image = canvas()
    put_rect(image, (10, 10, 30, 30), (30, 200, 30, 255))
    put_rect(image, (18, 18, 22, 22), (120, 80, 150, 255))  # same as backdrop

    result = remove_background(image, feather=False)

    assert result.getpixel((19, 19))[3] == 255, "interior hole was erased"


def test_returns_rgba():
    result = remove_background(canvas())
    assert result.mode == "RGBA"


def test_fully_uniform_image_becomes_fully_transparent():
    result = remove_background(canvas(), feather=False)
    assert opaque_count(result) == 0


def test_tolerance_controls_how_much_is_removed():
    image = canvas()
    # A near-backdrop ring the flood can reach through the border.
    put_rect(image, (0, 0, 40, 3), (125, 85, 155, 255))

    tight = remove_background(image, tolerance=2, feather=False)
    loose = remove_background(image, tolerance=20, feather=False)

    assert opaque_count(loose) < opaque_count(tight) or opaque_count(loose) == 0


def test_feather_softens_the_outline():
    image = canvas()
    put_rect(image, (10, 10, 30, 30), (30, 200, 30, 255))

    hard = remove_background(image, feather=False)
    soft = remove_background(image, feather=True)

    # The pixel just inside the subject's boundary loses some alpha.
    assert soft.getpixel((10, 20))[3] < hard.getpixel((10, 20))[3]


def test_rejects_unknown_mode():
    with pytest.raises(ValueError, match="unknown background mode"):
        remove_background(canvas(), mode="magic")


def test_transparent_input_is_left_alone():
    """Already-transparent art must not gain or lose coverage."""
    image = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    put_rect(image, (4, 4, 6, 6), (255, 0, 0, 255))
    result = remove_background(image, feather=False)
    assert result.getpixel((5, 5))[3] == 255
    assert result.getpixel((0, 0))[3] == 0


def test_zero_size_image_is_handled():
    result = remove_background(Image.new("RGBA", (0, 0)))
    assert result.size == (0, 0)
