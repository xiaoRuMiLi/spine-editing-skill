"""Read joint marks a human drew on an illustration.

The convention is deliberately narrow: a mark is a small **hollow ring** (a black
ellipse outline). Rings are found by their hole, not by their ink:

1. threshold near-black pixels into an "ink" mask,
2. flood the paper background in from the border,
3. whatever stays unreached and is NOT ink is enclosed -> candidate hole,
4. a hole of plausible size whose centroid is the joint.

Why not just take dark blobs: a filled dark area (a pupil, an eyebrow) is not a
mark, and a thin dark line (a hair strand) is not a mark either. Neither encloses
anything, so neither survives step 3. This is the difference between "the tool
found 20 marks" and "the tool found 24 dark things, three of which were eyes".

Limits that are handled explicitly:

* a ring cut by a hair strand becomes two holes -> :func:`merge_close_marks`,
* a ring drawn almost shut has a slit too thin to flood -> the caller adds it by
  hand (the girl's ``(354, 646)`` mark), and ``snap`` reports how far a spec point
  sits from the nearest detected mark so that gap is visible, never silent.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DARK_THRESHOLD = 80
"""Ink is every channel below this. The marks in practice are pure black."""

MIN_HOLE_AREA = 12
MAX_HOLE_AREA = 900
MAX_HOLE_SIDE = 40
MIN_FILL_RATIO = 0.30
"""Hole area / bounding-box area. A ring's hole is fat; a hair gap is a sliver."""


@dataclass
class Mark:
    """One joint mark, in image pixels (y down)."""

    x: float
    y: float
    width: int = 0
    height: int = 0
    area: int = 0

    def as_dict(self) -> dict[str, float]:
        return {"x": round(self.x, 1), "y": round(self.y, 1)}


def _ink_mask(image: Image.Image, threshold: int = DARK_THRESHOLD) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB")).astype(np.int16)
    return (
        (rgb[:, :, 0] < threshold)
        & (rgb[:, :, 1] < threshold)
        & (rgb[:, :, 2] < threshold)
    )


def _label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected labelling via row runs + union-find."""
    height, width = mask.shape
    padded = np.zeros((height, width + 2), dtype=np.int8)
    padded[:, 1:-1] = mask.astype(np.int8)
    diff = np.diff(padded, axis=1)

    starts: dict[int, list[int]] = {}
    ends: dict[int, list[int]] = {}
    for y, x in np.argwhere(diff == 1):
        starts.setdefault(int(y), []).append(int(x))
    for y, x in np.argwhere(diff == -1):
        ends.setdefault(int(y), []).append(int(x))

    rows: list[list[tuple[int, int, int]]] = []
    parent: list[int] = []
    index = 0
    for y in range(height):
        row = []
        for x0, x1 in zip(starts.get(y, []), ends.get(y, [])):
            parent.append(index)
            row.append((x0, x1, index))
            index += 1
        rows.append(row)

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for y in range(1, height):
        previous, current = rows[y - 1], rows[y]
        i = j = 0
        while i < len(previous) and j < len(current):
            p0, p1, pid = previous[i]
            c0, c1, cid = current[j]
            if p0 <= c1 and c0 <= p1:
                ra, rb = find(pid), find(cid)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
            if p1 < c1:
                i += 1
            else:
                j += 1

    labels = np.zeros((height, width), dtype=np.int32)
    roots: dict[int, int] = {}
    for y, row in enumerate(rows):
        for x0, x1, rid in row:
            root = find(rid)
            if root not in roots:
                roots[root] = len(roots) + 1
            labels[y, x0:x1] = roots[root]
    return labels, len(roots)


def detect_marks(image_path: str, *, threshold: int = DARK_THRESHOLD) -> list[Mark]:
    """Every hollow ring in ``image_path``, ordered top-to-bottom then left-to-right."""
    image = Image.open(image_path).convert("RGB")
    ink = _ink_mask(image, threshold)

    # Flood the outside. Pillow's floodfill is C-speed, and the paper is one
    # connected region, so this is the whole background in one call.
    light = Image.fromarray(((~ink) * 255).astype(np.uint8), mode="L")
    ImageDraw.floodfill(light, (0, 0), 128)
    holes = np.asarray(light) == 255

    if not holes.any():
        return []

    labels, count = _label(holes)
    marks: list[Mark] = []
    for label in range(1, count + 1):
        component = labels == label
        area = int(component.sum())
        if area < MIN_HOLE_AREA or area > MAX_HOLE_AREA:
            continue
        ys, xs = np.nonzero(component)
        width = int(xs.max() - xs.min() + 1)
        height = int(ys.max() - ys.min() + 1)
        if width > MAX_HOLE_SIDE or height > MAX_HOLE_SIDE:
            continue
        if width < 3 or height < 3:
            continue
        if area / float(width * height) < MIN_FILL_RATIO:
            continue
        marks.append(
            Mark(x=float(xs.mean()), y=float(ys.mean()), width=width, height=height, area=area)
        )

    marks.sort(key=lambda m: (round(m.y / 25), m.x))
    return marks


def merge_close_marks(marks: list[Mark], radius: float = 14.0) -> list[Mark]:
    """Join holes that are two halves of one ring (cut by a hair strand)."""
    merged: list[Mark] = []
    for mark in marks:
        for existing in merged:
            if abs(existing.x - mark.x) <= radius and abs(existing.y - mark.y) <= radius:
                total = existing.area + mark.area or 1
                existing.x = (existing.x * existing.area + mark.x * mark.area) / total
                existing.y = (existing.y * existing.area + mark.y * mark.area) / total
                existing.area = total
                existing.width = max(existing.width, mark.width)
                existing.height = max(existing.height, mark.height)
                break
        else:
            merged.append(
                Mark(mark.x, mark.y, mark.width, mark.height, mark.area)
            )
    merged.sort(key=lambda m: (round(m.y / 25), m.x))
    return merged


def nearest_mark(marks: list[Mark], x: float, y: float) -> tuple[Mark | None, float]:
    """Closest mark to a point, plus the distance."""
    if not marks:
        return None, float("inf")
    best = min(marks, key=lambda m: (m.x - x) ** 2 + (m.y - y) ** 2)
    return best, ((best.x - x) ** 2 + (best.y - y) ** 2) ** 0.5


def annotate(image_path: str, marks: list[Mark], out_path: str, *, scale: int = 2) -> str:
    """Numbered copy of the art, so a human can confirm what was read."""
    image = Image.open(image_path).convert("RGB")
    image = image.resize((image.width * scale, image.height * scale), Image.LANCZOS)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 20)
    except Exception:  # pragma: no cover - font is cosmetic
        font = ImageFont.load_default()

    for index, mark in enumerate(marks, 1):
        x, y = mark.x * scale, mark.y * scale
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 0, 0))
        draw.text((x + 9, y - 11), str(index), fill=(200, 0, 0), font=font)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    image.save(out_path)
    return out_path


def save_marks(marks: list[Mark], path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump([m.as_dict() for m in marks], handle, indent=2)
    return path


def load_marks(path: str) -> list[Mark]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return [Mark(x=float(item["x"]), y=float(item["y"])) for item in data]


def read_marks(image_path: str, *, threshold: int = DARK_THRESHOLD) -> list[Mark]:
    """Detect and merge in one call -- what callers actually want."""
    return merge_close_marks(detect_marks(image_path, threshold=threshold))
