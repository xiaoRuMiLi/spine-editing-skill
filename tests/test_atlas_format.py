"""Atlas text format: parse, serialise, and prove the round trip is lossless.

These tests use the real owl atlas, because the format details that bite (tab
indentation, ``bounds`` instead of ``xy``/``size``/``orig``, the page ``scale``
field) only appear in genuine editor exports.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spine_forge.assets import atlas as atlas_io

OWL_ATLAS = Path("examples/owl/export/owl.atlas")

SAMPLE = """\
sheet.png
\tsize: 512, 256
\tformat: RGBA8888
\tfilter: Linear, Linear
\trepeat: none
head
\tbounds: 10, 20, 100, 80
foot
\tbounds: 200, 40, 60, 50
\trotate: 90
"""


def test_parses_page_header():
    atlas = atlas_io.parse(SAMPLE)
    assert len(atlas.pages) == 1
    page = atlas.pages[0]
    assert page.image == "sheet.png"
    assert page.size == (512, 256)
    assert page.format == "RGBA8888"


def test_parses_regions_and_bounds():
    atlas = atlas_io.parse(SAMPLE)
    page = atlas.pages[0]
    assert [r.name for r in page.regions] == ["head", "foot"]

    head = page.find("head")
    assert head is not None
    assert head.bounds == (10, 20, 100, 80)
    assert head.position == (10, 20)
    assert head.size == (100, 80)


def test_parses_rotate_flag():
    atlas = atlas_io.parse(SAMPLE)
    foot = atlas.pages[0].find("foot")
    assert foot is not None
    assert foot.rotate == 90
    assert atlas.pages[0].find("head").rotate == 0


def test_page_scale_defaults_to_one():
    atlas = atlas_io.parse(SAMPLE)
    assert atlas.pages[0].scale == 1.0


def test_find_region_searches_all_pages():
    atlas = atlas_io.parse(SAMPLE)
    hit = atlas.find_region("foot")
    assert hit is not None
    page, region = hit
    assert page.image == "sheet.png"
    assert region.name == "foot"
    assert atlas.find_region("nope") is None


def test_roundtrip_is_lossless():
    """Serialise then reparse; nothing may drift.

    This is the guard that keeps unknown keys and `rotate` from being dropped
    when the reskin pipeline rewrites an atlas.
    """
    original = atlas_io.parse(SAMPLE)
    again = atlas_io.parse(atlas_io.dumps(original))

    assert len(again.pages) == len(original.pages)
    for before, after in zip(original.pages, again.pages):
        assert before.image == after.image
        assert before.size == after.size
        assert before.scale == after.scale
        assert len(before.regions) == len(after.regions)
        for rb, ra in zip(before.regions, after.regions):
            assert rb == ra


def test_unknown_keys_survive_roundtrip():
    """Editor-authored keys we do not model must not be silently dropped."""
    text = SAMPLE.replace(
        "\trepeat: none\n",
        "\trepeat: none\n\tpma: true\n\tcustom: keep-me\n",
    )
    atlas = atlas_io.parse(text)
    page = atlas.pages[0]
    assert page.extra["custom"] == "keep-me"
    assert "custom: keep-me" in atlas_io.dumps(atlas)


@pytest.mark.skipif(not OWL_ATLAS.is_file(), reason="owl example not present")
def test_real_atlas_roundtrip():
    """The shipped fixture: 1 page, 27 regions, packed at half resolution."""
    atlas = atlas_io.load(str(OWL_ATLAS))

    assert len(atlas.pages) == 1
    page = atlas.pages[0]
    assert page.image == "owl.png"
    assert page.size == (1024, 1024)
    assert page.scale == 0.5, "semi-resolution packing is a default trap; assert it explicitly"
    assert len(page.regions) == 27

    again = atlas_io.parse(atlas_io.dumps(atlas))
    assert len(again.pages[0].regions) == 27
    assert all(
        a == b
        for a, b in zip(atlas.pages[0].regions, again.pages[0].regions)
    )


@pytest.mark.skipif(not OWL_ATLAS.is_file(), reason="owl example not present")
def test_real_atlas_known_region():
    atlas = atlas_io.load(str(OWL_ATLAS))
    head = atlas.pages[0].find("head-base")
    assert head is not None
    # 299x237 packed at scale 0.5 -> 598x474 in rig units.
    width, height = head.size
    assert width == 299
    assert height == 237
