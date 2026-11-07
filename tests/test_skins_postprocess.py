"""Normalisation: make generated art comparable to the part it replaces.

The regression this guards is the one that produced a 2.84x bone scale: art
arrives several times larger than expected, ``align`` measures it, and the whole
tree inflates. Normalising first keeps ``align`` in its fine-adjustment role.
"""

from __future__ import annotations

import pytest
from PIL import Image

from spine_forge.skins.postprocess import (
    normalize_to_reference,
    opaque_size,
    prepare,
)


def subject(width: int = 20, height: int = 20, outer: int = 40) -> Image.Image:
    """An opaque square centred inside a transparent canvas."""
    image = Image.new("RGBA", (outer, outer), (0, 0, 0, 0))
    offset_x = (outer - width) // 2
    offset_y = (outer - height) // 2
    for x in range(offset_x, offset_x + width):
        for y in range(offset_y, offset_y + height):
            image.putpixel((x, y), (0, 128, 0, 255))
    return image


def test_opaque_size_ignores_transparent_margins():
    assert opaque_size(subject(20, 20, 60)) == (20, 20)


def test_opaque_size_of_blank_is_zero():
    assert opaque_size(Image.new("RGBA", (10, 10), (0, 0, 0, 0))) == (0, 0)


def test_height_mode_matches_opaque_height():
    source = subject(20, 40)   # 40 tall
    reference = subject(20, 20)  # 20 tall
    result = normalize_to_reference(source, reference, mode="height")
    assert opaque_size(result)[1] == pytest.approx(20, abs=1)


def test_width_mode_matches_opaque_width():
    source = subject(40, 20)
    reference = subject(20, 20)
    result = normalize_to_reference(source, reference, mode="width")
    assert opaque_size(result)[0] == pytest.approx(20, abs=1)


def test_fit_mode_uses_the_larger_ratio():
    # Source is 40 wide / 20 tall; reference 20 x 20 -> width ratio 0.5, height 1.0.
    source = subject(40, 20)
    reference = subject(20, 20)
    result = normalize_to_reference(source, reference, mode="fit")
    assert opaque_size(result)[1] == pytest.approx(20, abs=1)


def test_reference_scale_doubles_the_target():
    """Half-resolution reference: the target is twice its pixel height."""
    source = subject(20, 40)
    reference = subject(20, 20)

    plain = normalize_to_reference(source, reference, mode="height", reference_scale=1.0)
    doubled = normalize_to_reference(source, reference, mode="height", reference_scale=0.5)

    assert opaque_size(doubled)[1] == pytest.approx(
        opaque_size(plain)[1] * 2, abs=2
    )


def test_regression_oversized_generation_is_shrunk():
    """The 2.84x case: art many times larger must come back near the target."""
    huge = subject(200, 800, 900)
    reference = subject(20, 20)

    result = normalize_to_reference(huge, reference, mode="height")

    assert opaque_size(result)[1] == pytest.approx(20, abs=2)


def test_near_identity_is_left_untouched():
    source = subject(20, 20)
    reference = subject(20, 20)
    result = normalize_to_reference(source, reference, mode="height")
    assert result.size == source.size


def test_blank_source_is_returned_unchanged():
    blank = Image.new("RGBA", (30, 30), (0, 0, 0, 0))
    result = normalize_to_reference(blank, subject(), mode="height")
    assert result.size == blank.size


def test_blank_reference_is_returned_unchanged():
    source = subject()
    blank = Image.new("RGBA", (30, 30), (0, 0, 0, 0))
    result = normalize_to_reference(source, blank, mode="height")
    assert result.size == source.size


def test_rejects_unknown_mode():
    with pytest.raises(ValueError, match="unknown normalize mode"):
        normalize_to_reference(subject(), subject(), mode="diagonal")


def test_prepare_mattes_before_measuring():
    """Measuring first would count the opaque backdrop as subject size."""
    image = Image.new("RGBA", (40, 40), (120, 80, 150, 255))
    for x in range(15, 25):
        for y in range(15, 25):
            image.putpixel((x, y), (0, 128, 0, 255))

    reference = subject(20, 20)
    result = prepare(image, reference, matte=True, mode="height")

    # Subject is 10px tall in the source, reference is 20 -> roughly doubled.
    assert opaque_size(result)[1] == pytest.approx(20, abs=2)
    assert result.getpixel((0, 0))[3] == 0


def test_prepare_without_reference_only_mattes():
    image = Image.new("RGBA", (40, 40), (120, 80, 150, 255))
    image.putpixel((20, 20), (0, 128, 0, 255))

    result = prepare(image, None, matte=True)
    assert result.size == image.size
    assert result.getpixel((0, 0))[3] == 0
