"""Splitter tests: component separation and noise handling."""

from __future__ import annotations

import os

import pytest
from PIL import Image, ImageDraw

from spine_forge.splitter import ConnectedComponentSplitter


def _draw(tmp_path, shapes, size=(100, 100)):
    path = tmp_path / "src.png"
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for box in shapes:
        draw.rectangle(box, fill=(200, 100, 50, 255))
    canvas.save(path)
    return str(path)


def test_separate_shapes_become_separate_parts(tmp_path):
    src = _draw(tmp_path, [(5, 5, 35, 35), (60, 5, 90, 35), (30, 60, 60, 90)])
    parts = ConnectedComponentSplitter().split(src, str(tmp_path / "out"))
    assert len(parts) == 3
    # Each part keeps the bounding box of its own shape.
    boxes = sorted(p.box for p in parts)
    assert boxes == [(5, 5, 36, 36), (30, 60, 61, 91), (60, 5, 91, 36)]


def test_touching_shapes_merge_into_one_part(tmp_path):
    # This is the documented limitation: connected pixels are one component,
    # so an upper arm drawn against a forearm is a single part.
    src = _draw(tmp_path, [(10, 10, 50, 50), (50, 10, 90, 50)])
    parts = ConnectedComponentSplitter().split(src, str(tmp_path / "out"))
    assert len(parts) == 1


def test_part_pngs_written_and_sized(tmp_path):
    src = _draw(tmp_path, [(5, 5, 35, 45)])
    parts = ConnectedComponentSplitter().split(src, str(tmp_path / "out"))
    part = parts[0]
    assert os.path.isfile(part.image_path)
    with Image.open(part.image_path) as img:
        assert img.size == (part.width, part.height)


def test_transparent_image_rejected(tmp_path):
    path = tmp_path / "empty.png"
    Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(path)
    with pytest.raises(ValueError, match="no opaque pixels"):
        ConnectedComponentSplitter().split(str(path), str(tmp_path / "out"))


def test_tiny_speckles_dropped(tmp_path):
    # A 1px dot is below the noise threshold for a 100x100 canvas.
    src = _draw(tmp_path, [(10, 10, 60, 60), (95, 95, 96, 96)])
    parts = ConnectedComponentSplitter().split(src, str(tmp_path / "out"))
    assert len(parts) == 1


def test_parts_are_ordered_reading_order(tmp_path):
    src = _draw(tmp_path, [(60, 60, 90, 90), (5, 5, 35, 35)])
    parts = ConnectedComponentSplitter().split(src, str(tmp_path / "out"))
    # Top-most part first.
    assert parts[0].box[1] < parts[1].box[1]
