"""Decide where new artwork lands: scale factor and offset.

The goal is a heads-up replacement. When a pigeon head is swapped in for an owl
head, the pigeon head is smaller on the canvas; the rig has to shrink the
attachment and everything hung off it, or the new art floats in the old footprint.

Two independent measurements feed the decision:

* ``scale``  -- how much smaller the new art is than the art it replaces, given
                by comparing opaque bounding boxes rather than raw pixel counts.
                Composition differences inside the box do not skew it.
* ``anchor`` -- where the new art's visual centre is relative to its own box, so
                a subject that sits high in its canvas still lands on the pivot.

Everything is expressed as ratios, never absolute pixels, so the result composes
with any parent transform.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


@dataclass
class AlignResult:
    scale: float
    """Multiplier to apply to geometry. 1.0 means the new art is the same size."""

    source_box: tuple[int, int, int, int]
    """Opaque bounds of the art being replaced, in its own pixels."""

    target_box: tuple[int, int, int, int]
    """Opaque bounds of the incoming art, in its own pixels."""

    source_scale: float = 1.0
    """Atlas page scale the source art was packed at (1.0 for full resolution)."""

    @property
    def source_size(self) -> tuple[int, int]:
        left, top, right, bottom = self.source_box
        return right - left, bottom - top

    @property
    def source_size_in_rig_units(self) -> tuple[float, float]:
        """Source dimensions expressed in rig units, atlas packing scale removed.

        The rig's geometry is authored at full resolution even when the atlas was
        packed at half, so comparisons must be made on this value, not on raw
        atlas pixels.
        """
        width, height = self.source_size
        divisor = self.source_scale or 1.0
        return width / divisor, height / divisor

    @property
    def target_size(self) -> tuple[int, int]:
        left, top, right, bottom = self.target_box
        return right - left, bottom - top


def _opaque_box(image: Image.Image, threshold: int = 8) -> tuple[int, int, int, int]:
    """Bounding box of pixels at or above ``threshold`` alpha.

    Spine art almost always arrives with generous transparent margins; measuring
    those margins instead of the subject is the single most common cause of a
    replacement that looks mis-scaled.
    """
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value > threshold else 0)
    box = mask.getbbox()
    if box is None:
        raise ValueError("incoming art is fully transparent")
    return box


def compute_scale(
    source_image: Image.Image,
    target_image: Image.Image,
    *,
    mode: str = "height",
    manual: float | None = None,
    source_scale: float = 1.0,
) -> AlignResult:
    """Work out the scale factor between the art being replaced and its replacement.

    ``mode``:
        ``height`` -- match the opaque height. Usual choice for heads, torsos and
                      limbs, where height carries the silhouette.
        ``width``  -- match the opaque width. For wide pieces such as wings.
        ``area``   -- match total opaque area; the most forgiving when the two
                      shapes are intrinsically different.
        ``fit``    -- match the larger of the two ratios, so nothing overflows the
                      original footprint.

    ``manual`` overrides the computed factor while still reporting both boxes, so
    the UI can show "auto suggested 0.61, you set 0.55".

    ``source_scale`` is the atlas page's ``scale`` field. An atlas packed at half
    resolution stores pixels that represent twice their size in the rig, so a
    region cropped from it is NOT directly comparable to a full-resolution image
    the user supplies. Dividing the source box by this factor puts both sides on
    the rig's own units; skipping it inflates every computed ratio by
    1/source_scale and scales the whole part -- and its children -- accordingly.
    """
    source_box = _opaque_box(source_image)
    target_box = _opaque_box(target_image)

    if source_scale <= 0:
        raise ValueError("source_scale must be positive")

    source_w = (source_box[2] - source_box[0]) / source_scale
    source_h = (source_box[3] - source_box[1]) / source_scale
    target_w = target_box[2] - target_box[0]
    target_h = target_box[3] - target_box[1]

    if source_w <= 0 or source_h <= 0:
        raise ValueError("source art has an empty opaque box")
    if target_w <= 0 or target_h <= 0:
        raise ValueError("incoming art has an empty opaque box")

    if manual is not None:
        if manual <= 0:
            raise ValueError("manual scale must be positive")
        scale = float(manual)
    elif mode == "height":
        scale = target_h / source_h
    elif mode == "width":
        scale = target_w / source_w
    elif mode == "area":
        import math

        scale = math.sqrt((target_w * target_h) / (source_w * source_h))
    elif mode == "fit":
        scale = max(target_h / source_h, target_w / source_w)
    else:
        raise ValueError(f"unknown scale mode: {mode!r}")

    return AlignResult(
        scale=scale,
        source_box=source_box,
        target_box=target_box,
        source_scale=source_scale,
    )
