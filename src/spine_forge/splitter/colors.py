"""Colour-family splitter: one flat illustration in, labelled parts out.

The source picture separates its parts by COLOUR, not by transparency: a shirt and
its sleeve are one blob because both are brown, while an arm and a leg are two
blobs even though both are red. So the split runs in three stages:

1. **Fills** -- k-means over Lab chroma groups the picture into its actual fills.
   Lightness is weighted down and the naming decision is taken on a cluster mean,
   not on single pixels, because pencil shading walks one fill's hue across tens
   of degrees.
2. **Families** -- each fill is named by hue/saturation/value windows (hair,
   shorts, shirt, bare arm, skin, socks, shoes, accents). A cluster that matches
   none is left unclaimed and later absorbed by whichever part it touches, which
   is how grey outline pixels and shadow cores end up where they belong.
3. **Parts** -- connected components inside a family, with two cleanups: fragments
   split by a thin occluder (a sandal strap across a sock) are re-joined by box
   proximity, and small orphans are absorbed by the neighbour they sit on.

Naming is positional, never a fixed part list: the art decides how many limbs it
has. Everything is numpy + Pillow. Connected components use row runs plus a
union-find rather than a per-pixel flood fill; a 900x1200 picture has ~200k
foreground pixels, and BFS over that in Python takes tens of seconds.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from .base import Part

# Background: near-white, near-grey. Catches the paper as well as the watermarks.
BG_VALUE = 0.90
BG_SATURATION = 0.12

# Components below this share of the image are speckle, not parts.
MIN_AREA_RATIO = 0.0002

# Same-family fragments whose boxes are this close are one part, cut apart by a
# thin occluder (sandal strap over sock, outline over sleeve).
MERGE_GAP = 12

# An orphan part this enclosed by a much larger part is a shading sliver of it.
ABSORB_AREA_RATIO = 0.05
ENCLOSED_RATIO = 0.75

# A sliver this small and this elongated is a pencil stroke (a hem shadow), not a
# body part; it is absorbed by whatever it runs along.
STROKE_AREA = 1200

# Palette distance (chroma + 0.45*lightness, Lab units) beyond which a pixel is
# not any fill of this drawing. Keeps watermarks and scan shadows out of parts.
MAX_FILL_DISTANCE = 20.0

# Lab chroma distance below which two fills read as the same colour: used when
# deciding whether a small enclosed island is a shading sliver of its host.
MERGE_CHROMA = 14.0

# How far a family may grow into unclaimed pixels (outlines, shadow cores).
GROW_ROUNDS = 6


@dataclass
class Family:
    """One named colour region: hue window plus saturation/value bounds."""

    name: str
    hue_lo: float
    hue_hi: float
    min_sat: float = 0.0
    max_sat: float = 1.0
    min_val: float = 0.0
    max_val: float = 1.0

    def matches(self, hue, sat, val) -> np.ndarray:
        if self.hue_lo <= self.hue_hi:
            hue_ok = (hue >= self.hue_lo) & (hue <= self.hue_hi)
        else:  # wraps through red
            hue_ok = (hue >= self.hue_lo) | (hue <= self.hue_hi)
        return (
            hue_ok
            & (sat >= self.min_sat)
            & (sat <= self.max_sat)
            & (val >= self.min_val)
            & (val <= self.max_val)
        )


# Order matters: first match wins. ``orange`` precedes ``shirt`` because a bare
# arm and a brown sleeve share a hue and differ only in saturation/brightness.
FAMILIES: tuple[Family, ...] = (
    Family("orange", 12.0, 50.0, min_sat=0.66, min_val=0.78),
    Family("shirt", 12.0, 50.0, min_sat=0.28),
    Family("hair", 100.0, 158.0, min_sat=0.30),
    Family("shorts", 55.0, 100.0, min_sat=0.20, min_val=0.62),
    Family("teal", 160.0, 205.0, min_sat=0.25),
    Family("blue", 205.0, 245.0, min_sat=0.25),
    Family("purple", 265.0, 330.0, min_sat=0.25),
    Family("skin", 330.0, 15.0, min_sat=0.30),
)

FAMILY_BY_NAME = {family.name: family for family in FAMILIES}


@dataclass
class _Part:
    family: str
    name: str
    mask: np.ndarray
    box: tuple[int, int, int, int]
    area: int
    cx: float
    cy: float

    def gap_to(self, other: "_Part") -> float:
        left, top, right, bottom = self.box
        oleft, otop, oright, obottom = other.box
        dx = max(0, oleft - right, left - oright)
        dy = max(0, otop - bottom, top - obottom)
        return float(max(dx, dy))


# --------------------------------------------------------------- colour space


def _hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    delta = mx - mn
    sat = np.where(mx > 0, delta / np.maximum(mx, 1e-6), 0.0)

    hue = np.zeros_like(mx)
    safe = delta > 1e-6
    r_is = safe & (mx == r)
    g_is = safe & (mx == g)
    b_is = safe & (mx == b)
    hue[r_is] = ((g - b)[r_is] / delta[r_is]) % 6
    hue[g_is] = ((b - r)[g_is] / delta[g_is]) + 2
    hue[b_is] = ((r - g)[b_is] / delta[b_is]) + 4
    return hue * 60.0, sat, mx


def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB [0,1] -> CIE Lab (D65). Small enough to keep instead of a dependency."""
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    matrix = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ]
    )
    xyz = linear @ matrix.T
    scaled = xyz / np.array([0.95047, 1.0, 1.08883])
    f = np.where(scaled > 0.008856, np.cbrt(scaled), 7.787 * scaled + 16 / 116)
    return np.stack(
        [
            116 * f[:, :, 1] - 16,
            500 * (f[:, :, 0] - f[:, :, 1]),
            200 * (f[:, :, 1] - f[:, :, 2]),
        ],
        axis=2,
    )


def _kmeans(points: np.ndarray, k: int, seed: int = 7, iterations: int = 40):
    """Plain k-means, deterministic seed so runs are reproducible."""
    rng = np.random.default_rng(seed)
    centers = points[rng.choice(len(points), size=min(k, len(points)), replace=False)].copy()
    labels = np.zeros(len(points), dtype=np.int32)
    for _ in range(iterations):
        distances = ((points[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        labels = distances.argmin(axis=1)
        for index in range(len(centers)):
            members = points[labels == index]
            if len(members):
                centers[index] = members.mean(axis=0)
    return centers, labels


# ------------------------------------------------------------- family naming


def _family_of(hue: float, sat: float, val: float) -> int:
    """Index of the first family whose window accepts this colour, else -1."""
    for index, family in enumerate(FAMILIES):
        if family.matches(np.array([hue]), np.array([sat]), np.array([val]))[0]:
            return index
    return -1


def _fill_families(rgb: np.ndarray, foreground: np.ndarray, hue, sat, val) -> np.ndarray:
    """Assign every foreground pixel a family index, or -1 when no fill owns it.

    Fills are found as *peaks in the colour histogram*, not by k-means. Flat
    illustration has large areas of one exact colour, so peaks are the real
    palette; k-means instead splits a big flat area into several clusters and
    merges two small distinct ones -- on a test sheet it glued the green hair to
    the light-green shorts and lost the teal shoes entirely.

    1. count colours in 16-level RGB buckets over the foreground,
    2. keep buckets that cover a real area, and merge buckets that are the same
       colour (shading moves a fill a little, not a lot),
    3. assign each pixel to the nearest kept colour in chroma-weighted Lab,
    4. name each kept colour by its own mean hue/saturation/value.
    """
    pixels = rgb[foreground]
    if len(pixels) < 64:
        raise ValueError("not enough foreground pixels to cluster")

    buckets = (pixels * 255).astype(np.int16) // 16
    keys = (buckets[:, 0] * 16 + buckets[:, 1]) * 16 + buckets[:, 2]
    counts = np.bincount(keys, minlength=16 * 16 * 16)

    min_count = max(40, int(0.0008 * len(pixels)))
    peaks = np.flatnonzero(counts >= min_count)
    if len(peaks) == 0:
        peaks = np.array([int(np.argmax(counts))])

    centres_rgb: list[np.ndarray] = []
    centres_weight: list[int] = []
    for key in peaks:
        member = keys == key
        centres_rgb.append(pixels[member].mean(axis=0))
        centres_weight.append(int(counts[key]))

    # Merge buckets that describe the same fill: compare chroma, allow lightness
    # to move (shading), because that is exactly how one fill splits into peaks.
    merged_rgb: list[np.ndarray] = []
    merged_weight: list[int] = []
    for rgb_centre, weight in zip(centres_rgb, centres_weight):
        lab = _rgb_to_lab(rgb_centre.reshape(1, 1, 3))[0, 0]
        placed = False
        for index, existing in enumerate(merged_rgb):
            existing_lab = _rgb_to_lab(existing.reshape(1, 1, 3))[0, 0]
            chroma_gap = float(np.linalg.norm(lab[1:] - existing_lab[1:]))
            light_gap = abs(float(lab[0] - existing_lab[0]))
            if chroma_gap <= 8.0 and light_gap <= 22.0:
                total = merged_weight[index] + weight
                merged_rgb[index] = (existing * merged_weight[index] + rgb_centre * weight) / total
                merged_weight[index] = total
                placed = True
                break
        if not placed:
            merged_rgb.append(rgb_centre)
            merged_weight.append(weight)

    palettes = np.stack(merged_rgb)
    palette_lab = _rgb_to_lab(palettes.reshape(1, -1, 3)).reshape(-1, 3)
    palette_hue, palette_sat, palette_val = _hsv(palettes.reshape(1, -1, 3))

    palette_family = np.array(
        [
            _family_of(float(palette_hue[0, index]), float(palette_sat[0, index]), float(palette_val[0, index]))
            for index in range(len(palettes))
        ],
        dtype=np.int16,
    )

    # Nearest palette entry per pixel, chroma first and lightness second.
    pixel_lab = _rgb_to_lab(rgb)
    best_distance = np.full(foreground.shape, np.inf, dtype=np.float32)
    best_index = np.zeros(foreground.shape, dtype=np.int16)
    for index in range(len(palettes)):
        delta = pixel_lab - palette_lab[index]
        distance = delta[:, :, 1] ** 2 + delta[:, :, 2] ** 2 + (delta[:, :, 0] * 0.45) ** 2
        closer = distance < best_distance
        best_distance[closer] = distance[closer]
        best_index[closer] = index

    assigned = np.full(foreground.shape, -1, dtype=np.int8)
    for index in range(len(palettes)):
        family = int(palette_family[index])
        if family < 0:
            continue
        assigned[(best_index == index) & foreground & (assigned < 0)] = family

    # A pixel nobody is close to is not part of the drawing's palette: a grey
    # watermark, a scanned shadow. Leaving it unclaimed lets the later passes
    # either attach it to a touching part or drop it as greyscale noise.
    assigned[best_distance > MAX_FILL_DISTANCE ** 2] = -1
    return assigned


# ------------------------------------------------------- morphology + labels


def _dilate(mask: np.ndarray) -> np.ndarray:
    """3x3 binary dilation via shifted ORs (no scipy)."""
    out = mask.copy()
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    tmp = out.copy()
    out[1:, :] |= tmp[:-1, :]
    out[:-1, :] |= tmp[1:, :]
    out[:, 1:] |= tmp[:, :-1]
    out[:, :-1] |= tmp[:, 1:]
    return out


def _box_sum(mask: np.ndarray, radius: int) -> np.ndarray:
    """Sum of ``mask`` over a (2r+1) square window, via an integral image."""
    padded = np.pad(mask.astype(np.int32), radius + 1, mode="constant")
    integral = padded.cumsum(0).cumsum(1)
    size = 2 * radius + 1
    height, width = mask.shape
    return (
        integral[size:size + height, size:size + width]
        - integral[0:height, size:size + width]
        - integral[size:size + height, 0:width]
        + integral[0:height, 0:width]
    )


def _erode(mask: np.ndarray) -> np.ndarray:
    """3x3 binary erosion: a pixel survives only if all 8 neighbours do."""
    return ~_dilate(~mask)


def _dilate4(mask: np.ndarray) -> np.ndarray:
    """4-connected dilation: up/down/left/right only."""
    out = mask.copy()
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def _erode4(mask: np.ndarray) -> np.ndarray:
    """4-connected erosion: a pixel survives only if its four cross-neighbours do.

    A 45 degree hair two pixels wide survives a square erosion by staying inside
    the 3x3 block, which is why the contour squiggle on the shirt outlived the
    normal opening. With cross connectivity it has nowhere to hide.
    """
    return ~_dilate4(~mask)


def _open(mask: np.ndarray, rounds: int) -> np.ndarray:
    out = mask
    for _ in range(rounds):
        out = _erode(out)
    for _ in range(rounds):
        out = _dilate(out)
    return out


def _reconstruct(seed: np.ndarray, mask: np.ndarray, limit: int = 200) -> np.ndarray:
    """Grow ``seed`` back inside ``mask`` until it stops growing.

    Opening alone shrinks the whole shape by the erosion radius; reconstruction
    restores the thick body exactly while leaving whatever the opening deleted
    (thin strands) deleted. That is what removes a 2px contour hair from the
    shirt without nibbling 2px off the shirt itself.
    """
    current = seed
    for _ in range(limit):
        grown = _dilate(current) & mask
        if np.array_equal(grown, current):
            break
        current = grown
    return current


def _label_runs(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Label 8-connected components using horizontal runs + union-find."""
    height, width = mask.shape
    parent: list[int] = []

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    padded = np.zeros((height, width + 2), dtype=np.int8)
    padded[:, 1:-1] = mask.astype(np.int8)
    diff = np.diff(padded, axis=1)

    start_map: dict[int, list[int]] = {}
    end_map: dict[int, list[int]] = {}
    for y, x in np.argwhere(diff == 1):
        start_map.setdefault(int(y), []).append(int(x))
    for y, x in np.argwhere(diff == -1):
        end_map.setdefault(int(y), []).append(int(x))

    run_rows: list[list[tuple[int, int, int]]] = []
    index = 0
    for y in range(height):
        row: list[tuple[int, int, int]] = []
        for x0, x1 in zip(start_map.get(y, []), end_map.get(y, [])):
            parent.append(index)
            row.append((x0, x1, index))
            index += 1
        run_rows.append(row)

    for y in range(1, height):
        previous, current = run_rows[y - 1], run_rows[y]
        i = j = 0
        while i < len(previous) and j < len(current):
            p0, p1, pid = previous[i]
            c0, c1, cid = current[j]
            if p0 <= c1 and c0 <= p1:  # inclusive -> 8-connected
                union(pid, cid)
            if p1 < c1:
                i += 1
            else:
                j += 1

    labels = np.zeros((height, width), dtype=np.int32)
    roots: dict[int, int] = {}
    for y, row in enumerate(run_rows):
        for x0, x1, rid in row:
            root = find(rid)
            label = roots.get(root)
            if label is None:
                label = len(roots) + 1
                roots[root] = label
            labels[y, x0:x1] = label
    return labels, len(roots)


def _components(mask: np.ndarray, min_area: int):
    labels, count = _label_runs(mask)
    blobs: list[dict] = []
    for label in range(1, count + 1):
        component = labels == label
        area = int(component.sum())
        if area < min_area:
            continue
        ys, xs = np.nonzero(component)
        blobs.append(
            {
                "label": label,
                "area": area,
                "box": (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1),
                "cx": float(xs.mean()),
                "cy": float(ys.mean()),
            }
        )
    return blobs, labels


# ------------------------------------------------------------------- naming


def _side(cx: float, axis: float) -> str:
    """Which side of the CHARACTER a part sits on, not of the picture.

    The art faces the viewer, so the viewer's left is the character's right.
    ``axis`` is the figure's own centre line, NOT the canvas centre: this girl
    stands left of centre with one arm reaching right, so a canvas-centre split
    put both her legs on the same side.
    """
    return "left" if cx > axis else "right"


def _name_skin(parts: list[_Part], height: int, axis: float) -> None:
    """Anatomical names for the crimson blobs, from where they sit."""
    heads = [p for p in parts if p.cy < 0.30 * height]
    arms = [p for p in parts if 0.30 * height <= p.cy < 0.62 * height]
    legs = [p for p in parts if p.cy >= 0.62 * height]

    heads.sort(key=lambda p: -p.area)
    for position, part in enumerate(heads):
        part.name = "head" if position == 0 else f"head-{position + 1}"

    arms.sort(key=lambda p: -p.area)
    for part in arms:
        part.name = f"arm-{_side(part.cx, axis)}"

    legs.sort(key=lambda p: p.cx)
    for part in legs:
        part.name = f"leg-{_side(part.cx, axis)}"


def _name_by_x(parts: list[_Part], stem: str) -> None:
    parts.sort(key=lambda p: p.cx)
    for position, part in enumerate(parts):
        part.name = f"{stem}-{'left' if position == 0 else 'right'}"


# --------------------------------------------------------------------- main


def _thin(part: "_Part", max_thickness: float = 6.0) -> bool:
    """True when the shape is a stroke: area small relative to its own box and
    its width in pixels (2*area/perimeter proxy) is a few pixels at most."""
    left, top, right, bottom = part.box
    box_area = max(1, (right - left) * (bottom - top))
    if part.area / box_area > 0.40:
        return False
    return part.area / max(right - left, bottom - top) <= max_thickness * 2


def split_by_colour(
    source_path: str,
    out_dir: str,
    min_area_ratio: float = MIN_AREA_RATIO,
) -> list[Part]:
    """Extract every colour-separated part and save each as ``<name>.png``.

    Parts are written at FULL canvas size with transparency, not tightly cropped:
    downstream bone placement needs absolute coordinates, and cropping here would
    throw that away.
    """
    image = Image.open(source_path).convert("RGBA")
    rgb = np.asarray(image.convert("RGB")).astype(np.float32) / 255.0
    height, width, _ = rgb.shape
    min_area = int(min_area_ratio * width * height)

    hue, sat, val = _hsv(rgb)
    background = (val > BG_VALUE) & (sat < BG_SATURATION)
    foreground = ~background

    assigned = _fill_families(rgb, foreground, hue, sat, val)

    # Colour islands too small for the histogram (eyes, lips, a lone buckle) are
    # recovered from their own mean colour. Without this the eye paint fell below
    # the peak threshold and was swallowed by the surrounding skin.
    residual = foreground & (assigned < 0)
    if residual.any():
        blobs, labels = _components(residual, max(200, min_area))
        for blob in blobs:
            mask = labels == blob["label"]
            if float(sat[mask].mean()) < 0.15 or float(val[mask].mean()) < 0.25:
                continue  # grey line or a black shadow, not a fill
            angles = np.deg2rad(hue[mask])
            circular = (np.rad2deg(np.arctan2(np.sin(angles).mean(), np.cos(angles).mean())) + 360) % 360
            family = _family_of(
                circular, float(sat[mask].mean()), float(val[mask].mean())
            )
            if family >= 0:
                assigned[mask] = family

    # Grey foreground no fill owns (outlines, shadow cores) joins the family that
    # dominates its neighbourhood. A plain "first family to grow" loop is order
    # biased: the shirt grew into every dark contour it could reach and dragged
    # ghost lines of both arms into its own part. Majority-in-a-window has no
    # such bias and follows the actual nearest region.
    # Anti-aliased edges blend one fill into another and land in whichever palette
    # entry the blend resembles -- the arm's edge came out as brown, i.e. shirt.
    # A majority vote over the neighbourhood puts those pixels back with the fill
    # they actually border.
    counts = np.stack([_box_sum(assigned == index, 1) for index in range(len(FAMILIES))])
    majority = counts.argmax(axis=0).astype(np.int8)
    vote = counts.max(axis=0)
    settled = (assigned >= 0) & (vote >= 3)
    assigned[settled] = majority[settled]

    for _ in range(GROW_ROUNDS):
        counts = np.stack(
            [_box_sum(assigned == index, 2) for index in range(len(FAMILIES))]
        )
        best = counts.argmax(axis=0)
        strongest = counts.max(axis=0)
        claim = (assigned < 0) & foreground & (strongest > 0)
        assigned[claim] = best[claim].astype(np.int8)

    residual = foreground & (assigned < 0)

    grouped: dict[str, list[_Part]] = {family.name: [] for family in FAMILIES}

    for index, family in enumerate(FAMILIES):
        mask = assigned == index
        if mask.sum() < min_area:
            continue
        blobs, labels = _components(mask, min_area)
        if not blobs:
            continue

        # Join fragments split by a thin occluder: union boxes that nearly touch.
        parent = list(range(len(blobs)))

        def find(a: int) -> int:
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for a in range(len(blobs)):
            for b in range(a + 1, len(blobs)):
                left, top, right, bottom = blobs[a]["box"]
                oleft, otop, oright, obottom = blobs[b]["box"]
                gap = max(
                    0,
                    oleft - right,
                    left - oright,
                    otop - bottom,
                    top - obottom,
                )
                if gap <= MERGE_GAP:
                    ra, rb = find(a), find(b)
                    if ra != rb:
                        parent[max(ra, rb)] = min(ra, rb)

        clusters: dict[int, list[dict]] = {}
        for position, blob in enumerate(blobs):
            clusters.setdefault(find(position), []).append(blob)

        for members in clusters.values():
            member_mask = np.isin(labels, [m["label"] for m in members])
            ys, xs = np.nonzero(member_mask)
            grouped[family.name].append(
                _Part(
                    family=family.name,
                    name="",
                    mask=member_mask,
                    box=(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1),
                    area=int(member_mask.sum()),
                    cx=float(xs.mean()),
                    cy=float(ys.mean()),
                )
            )

    # --- naming, family by family ------------------------------------------
    # The character's own centre line, weighted by area so a small reaching
    # hand cannot drag it sideways.
    all_parts = [part for bucket in grouped.values() for part in bucket]
    total_area = sum(part.area for part in all_parts) or 1
    axis = sum(part.cx * part.area for part in all_parts) / total_area

    if grouped["skin"]:
        _name_skin(grouped["skin"], height, axis)
    for family_name, stem in (("hair", "hair"), ("shorts", "shorts"), ("shirt", "shirt")):
        parts = sorted(grouped[family_name], key=lambda p: -p.area)
        for position, part in enumerate(parts):
            part.name = stem if position == 0 else f"{stem}-{position + 1}"
    for part in grouped["orange"]:
        part.name = f"arm-{_side(part.cx, axis)}"
    _name_group(grouped["teal"], "shoe", axis)
    _name_group(grouped["blue"], "sock", axis)
    _name_group(grouped["purple"], "accent", axis, force_side=False)

    parts: list[_Part] = [part for bucket in grouped.values() for part in bucket]

    if os.environ.get("SPINE_SPLIT_DEBUG"):
        for family_name, bucket in grouped.items():
            if bucket:
                print(f"  [family] {family_name:8} -> {[(p.area, p.name) for p in bucket]}")

    # --- absorb shading slivers -------------------------------------------
    # A hair-coloured sliver sitting inside the shorts is the shorts' own shadow.
    # The test is ENCLOSURE, not size alone: a sleeve that merely touches the
    # shirt must survive, which is what a plain area/gap rule destroyed when it
    # swallowed both arms into the torso.
    parts.sort(key=lambda p: -p.area)
    boundaries: dict[int, float] = {}
    dropped: list[str] = []

    def mean_chroma(part: _Part) -> np.ndarray:
        indices = fg_index[part.mask]
        indices = indices[indices >= 0]
        if not len(indices):
            return np.zeros(2)
        return lab_rgb[indices][:, 1:].mean(axis=0)

    lab_rgb = _rgb_to_lab(rgb).reshape(-1, 3)[foreground.ravel()]
    # Remap part masks into the foreground-pixel list for colour statistics.
    fg_index = np.full(foreground.shape, -1, dtype=np.int64)
    fg_index[foreground] = np.arange(int(foreground.sum()))

    def chroma_of(part: _Part) -> np.ndarray:
        indices = fg_index[part.mask]
        indices = indices[indices >= 0]
        if not len(indices):
            return np.zeros(2)
        return lab_rgb[indices][:, 1:].mean(axis=0)

    survivors: list[_Part] = []
    for part in parts:
        # A pencil stroke that ended up on its own is residue from the contour
        # lines, not a body part.
        if part.area < 400 and _thin(part):
            dropped.append(f"{part.family}:{part.area}px")
            continue
        host = None
        boundary = _dilate(part.mask) & ~part.mask
        boundary_count = int(boundary.sum())
        if boundary_count:
            for candidate in sorted(survivors, key=lambda c: c.area):
                covered = int((boundary & candidate.mask).sum()) / boundary_count
                ratio = part.area / max(candidate.area, 1)
                distance = float(np.linalg.norm(chroma_of(part) - chroma_of(candidate)))
                same_colour = distance <= MERGE_CHROMA
                stroke = part.area < STROKE_AREA and ratio < 0.2 and _thin(part)
                # Three ways an island is not its own part:
                #  * same colour and mostly enclosed -- a shading sliver of it,
                #  * same colour, touching, small -- a stroke along its edge,
                #  * tiny and fully swallowed -- an outline pocket.
                if not (
                    (same_colour and covered >= ENCLOSED_RATIO and ratio < 0.5)
                    or (same_colour and part.gap_to(candidate) <= 2 and ratio < 0.3)
                    or (ratio < ABSORB_AREA_RATIO and covered >= 0.95)
                    or (stroke and part.gap_to(candidate) <= 2)
                ):
                    continue
                host = candidate
                break

        if host is None:
            survivors.append(part)
            continue
        host.mask |= part.mask
        host.area = int(host.mask.sum())
        ys, xs = np.nonzero(host.mask)
        host.box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        host.cx = float(xs.mean())
        host.cy = float(ys.mean())

    os.makedirs(out_dir, exist_ok=True)
    used: set[str] = set()
    saved: list[Part] = []

    # --- merge socks with shoes, per foot -----------------------------------
    # A sock and the sandal over it are one visual unit and move together; as two
    # parts they would need two bones with the same motion.
            # Naming happens before the feet merge so the pieces can be found by
            # name; the merge itself is just below.
    for side in ("left", "right"):
        pieces = [p for p in survivors if p.name in (f"sock-{side}", f"shoe-{side}")]
        if len(pieces) < 2:
            continue
        merged = np.zeros(foreground.shape, dtype=bool)
        for piece in pieces:
            merged |= piece.mask
            survivors.remove(piece)
        ys, xs = np.nonzero(merged)
        survivors.append(
            _Part(
                family="foot",
                name=f"foot-{side}",
                mask=merged,
                box=(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1),
                area=int(merged.sum()),
                cx=float(xs.mean()),
                cy=float(ys.mean()),
            )
        )

    # --- prune stray strands ------------------------------------------------
    # Thin contour lines that the majority pass handed to the nearest fill end up
    # as hairs attached to a part: the shirt was carrying a ghost outline of an
    # arm. Those pixels are dropped, not collected: a global "outline" layer of
    # leftovers is not line art, and every real engine keeps each part's contour
    # inside its own texture so it moves with the limb.
    dropped_ink = 0.0
    stroke_count = 0
    if survivors:
        union_mask = np.zeros(foreground.shape, dtype=bool)
        for part in survivors:
            union_mask |= part.mask

        for part in survivors:
            core = _open(part.mask, 3)
            if not core.any():
                core = part.mask
            near_core = core
            for _ in range(3):
                near_core = _dilate(near_core)

            others = union_mask & ~part.mask
            for _ in range(4):
                others = _dilate(others)

            # Contour bleed, two ways:
            #  * ink of this part's colour lying outside its body and hugging a
            #    DIFFERENT part (the shirt carrying the arm's outline);
            #  * ink noticeably darker than the body, away from the body's core.
            #    Contour lines are always drawn darker than the fill they border,
            #    which is what separates them from the fill's own shading: shading
            #    sits inside the core and is protected.
            body_mask = core if core.any() else part.mask
            body_lab = _rgb_to_lab(rgb[body_mask].mean(axis=0).reshape(1, 1, 3))[0, 0]
            lightness = _rgb_to_lab(rgb)[:, :, 0]
            darker = lightness < body_lab[0] - 15.0
            bleed = part.mask & ~near_core & (others | darker)
            shape = part.mask & ~bleed

            # Keep the largest island, plus islands that actually touch it (a sock
            # behind a strap). Anything floating on its own is debris: the shirt
            # was left with a detached squiggle of the hand contour.
            labels, count = _label_runs(shape)
            if count > 1:
                areas = np.bincount(labels.ravel(), minlength=count + 1)
                main = int(np.argmax(areas[1:])) + 1
                main_mask = labels == main
                ys, xs = np.nonzero(main_mask)
                main_box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
                keep = main_mask.copy()
                for label in range(1, count + 1):
                    if label == main:
                        continue
                    piece = labels == label
                    ys, xs = np.nonzero(piece)
                    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
                    gap = max(
                        0,
                        main_box[0] - box[2],
                        box[0] - main_box[2],
                        main_box[1] - box[3],
                        box[1] - main_box[3],
                    )
                    if gap <= 3 or areas[label] >= max(120, 0.05 * part.area):
                        # Colour consistency: a fragment whose ink is a different
                        # colour from the body is a contour hair, not part of it.
                        pixels = rgb[piece]
                        if len(pixels):
                            frag = _rgb_to_lab(pixels.mean(axis=0).reshape(1, 1, 3))[0, 0]
                            body = _rgb_to_lab(rgb[main_mask].mean(axis=0).reshape(1, 1, 3))[0, 0]
                            if areas[label] < 0.02 * part.area and float(
                                np.linalg.norm(frag[1:] - body[1:])
                            ) > 15.0:
                                continue
                        keep |= piece
                shape = keep

            # Pruned pixels are dropped outright.
            dropped_ink += float((part.mask & ~shape).sum())
            if (part.mask & ~shape).any():
                stroke_count += 1
            part.mask = shape

        for part in survivors:
            if not part.mask.any():
                continue
            part.area = int(part.mask.sum())
            ys, xs = np.nonzero(part.mask)
            part.box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
            part.cx = float(xs.mean())
            part.cy = float(ys.mean())

    if os.environ.get("SPINE_SPLIT_DEBUG"):
        print(f"  [dropped strokes] {int(dropped_ink)} px in {stroke_count} piece(s)")

    survivors.sort(key=lambda p: -p.area)
    if os.environ.get("SPINE_SPLIT_DEBUG"):
        print(f"  [after absorb] {len(survivors)} parts: {[(p.family, p.name, p.area) for p in survivors]}")
    for part in survivors:
        name = part.name or part.family
        suffix = 2
        while name in used:
            name = f"{part.name or part.family}-{suffix}"
            suffix += 1
        used.add(name)

        rgba = np.asarray(image).copy()
        rgba[:, :, 3] = np.where(part.mask, rgba[:, :, 3], 0)
        path = os.path.join(out_dir, f"{name}.png")
        Image.fromarray(rgba, mode="RGBA").save(path)

        left, top, right, bottom = part.box
        saved.append(
            Part(
                name=name,
                image_path=path,
                width=right - left,
                height=bottom - top,
                box=part.box,
                center_x=part.cx,
                center_y=part.cy,
            )
        )
    return saved


def _name_group(parts: list[_Part], stem: str, axis: float, force_side: bool = True) -> None:
    """Name a family's blobs by the character's left/right."""
    parts.sort(key=lambda p: p.cx)
    used: set[str] = set()
    for part in parts:
        base = f"{stem}-{_side(part.cx, axis)}" if (force_side or len(parts) > 1) else stem
        name = base
        suffix = 2
        while name in used:
            name = f"{base}-{suffix}"
            suffix += 1
        used.add(name)
        part.name = name










class ColourSplitter:
    """``Splitter`` implementation over :func:`split_by_colour`.

    Exists so the flat-illustration pipeline plugs into ``stages.split`` and the
    CLI exactly like the connected-component splitter does: same ``split()``
    signature, same ``Part`` list, nothing stage-specific leaks out.
    """

    name = "colour"

    def split(self, source_path: str, out_dir: str) -> list[Part]:
        return split_by_colour(source_path, out_dir)
