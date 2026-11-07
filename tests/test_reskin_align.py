"""Scale inference: atlas page scale must be compensated before comparing sizes.

Regression guard for the bug that made a replacement head render at double size:
a region cropped from a half-resolution atlas reports half the pixels it stands
for in the rig, so a raw pixel comparison inflates every ratio by 1/page_scale.
"""

from __future__ import annotations

import pytest
from PIL import Image

from spine_forge.reskin.align import compute_scale


def solid(width: int, height: int) -> Image.Image:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for x in range(width):
        for y in range(height):
            image.putpixel((x, y), (255, 0, 0, 255))
    return image


def framed(outer: int, inner: int) -> Image.Image:
    """A ``inner`` square centred in an ``outer`` transparent square."""
    image = Image.new("RGBA", (outer, outer), (0, 0, 0, 0))
    offset = (outer - inner) // 2
    for x in range(offset, offset + inner):
        for y in range(offset, offset + inner):
            image.putpixel((x, y), (0, 0, 255, 255))
    return image


def test_same_size_gives_one():
    result = compute_scale(solid(100, 100), solid(100, 100))
    assert result.scale == pytest.approx(1.0)


def test_height_mode_matches_opaque_height():
    # Source 100 tall, target 50 tall -> half.
    result = compute_scale(solid(80, 100), solid(200, 50), mode="height")
    assert result.scale == pytest.approx(0.5)


def test_width_mode_matches_opaque_width():
    result = compute_scale(solid(100, 80), solid(50, 400), mode="width")
    assert result.scale == pytest.approx(0.5)


def test_fit_mode_takes_the_larger_ratio():
    # Width ratio 2.0, height ratio 0.5 -> fit picks 2.0 so nothing overflows.
    result = compute_scale(solid(100, 100), solid(200, 50), mode="fit")
    assert result.scale == pytest.approx(2.0)


def test_transparent_margins_are_ignored():
    """A generous transparent border must not change the measured size."""
    plain = solid(100, 100)
    padded = framed(300, 100)
    result = compute_scale(plain, padded, mode="height")
    assert result.scale == pytest.approx(1.0)


def test_atlas_scale_compensation():
    """The core regression: half-resolution source must not double the result.

    Source art is 300px in the atlas but stands for 600 rig units. A 600px
    replacement is therefore the same size, not twice as large.
    """
    source = solid(300, 300)
    target = solid(600, 600)

    naive = compute_scale(source, target, mode="height", source_scale=1.0)
    assert naive.scale == pytest.approx(2.0), "uncompensated ratio is the bug"

    compensated = compute_scale(source, target, mode="height", source_scale=0.5)
    assert compensated.scale == pytest.approx(1.0)


def test_atlas_scale_recorded_on_result():
    result = compute_scale(solid(100, 100), solid(100, 100), source_scale=0.5)
    assert result.source_scale == 0.5
    assert result.source_size == (100, 100)
    # 100 atlas pixels at half resolution stand for 200 rig units.
    assert result.source_size_in_rig_units == pytest.approx((200.0, 200.0))


def test_manual_scale_overrides_computed():
    result = compute_scale(solid(100, 100), solid(100, 100), manual=0.55)
    assert result.scale == pytest.approx(0.55)
    # Boxes are still reported so the UI can show "auto suggested X, you set Y".
    assert result.source_box is not None
    assert result.target_box is not None


def test_rejects_empty_art():
    blank = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    with pytest.raises(ValueError, match="fully transparent"):
        compute_scale(blank, solid(10, 10))


def test_rejects_non_positive_source_scale():
    with pytest.raises(ValueError, match="source_scale"):
        compute_scale(solid(10, 10), solid(10, 10), source_scale=0)


def test_rejects_unknown_mode():
    with pytest.raises(ValueError, match="unknown scale mode"):
        compute_scale(solid(10, 10), solid(10, 10), mode="diagonal")
