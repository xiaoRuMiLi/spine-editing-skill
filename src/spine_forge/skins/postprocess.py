"""Prepare generated artwork so the reskin stage receives sane input.

Image services rarely honour a requested canvas size and almost never return a
transparent background. Handing that raw output to ``apply_reskin`` triggers the
wrong thing: the alignment step measures opaque height, sees art several times
larger than the part it replaces, and scales the entire bone tree to match --
which inflates every child attachment along with it.

Normalising first keeps ``align`` in its intended role of fine adjustment
instead of brute force correction.

Kept separate from ``matting`` (background only) and from ``reskin.align``
(measurement only) so each stays testable on its own.
"""

from __future__ import annotations

from PIL import Image

from ..assets.matting import remove_background


def opaque_size(image: Image.Image, threshold: int = 8) -> tuple[int, int]:
    """Width and height of the non-transparent content, ignoring margins."""
    rgba = image.convert("RGBA")
    box = rgba.getchannel("A").point(lambda v: 255 if v > threshold else 0).getbbox()
    if box is None:
        return (0, 0)
    return (box[2] - box[0], box[3] - box[1])


def normalize_to_reference(
    image: Image.Image,
    reference: Image.Image,
    *,
    mode: str = "height",
    reference_scale: float = 1.0,
) -> Image.Image:
    """Resize generated art so its subject matches the reference subject's size.

    ``reference_scale`` is the atlas page scale the reference came from; without
    it a half-resolution atlas makes every comparison twice as large as it
    should be.

    ``mode`` mirrors :func:`reskin.align.compute_scale`: ``height``, ``width``,
    ``area`` or ``fit``.

    Returns the input untouched when either side is empty, rather than raising:
    a blank generation is a content problem for the caller to report, not a
    reason to crash mid-pipeline.
    """
    source_w, source_h = opaque_size(image)
    ref_w, ref_h = opaque_size(reference)
    if source_w == 0 or source_h == 0 or ref_w == 0 or ref_h == 0:
        return image

    ref_w = ref_w / (reference_scale or 1.0)
    ref_h = ref_h / (reference_scale or 1.0)

    if mode == "height":
        factor = ref_h / source_h
    elif mode == "width":
        factor = ref_w / source_w
    elif mode == "area":
        factor = ((ref_w * ref_h) / (source_w * source_h)) ** 0.5
    elif mode == "fit":
        factor = max(ref_h / source_h, ref_w / source_w)
    else:
        raise ValueError(f"unknown normalize mode: {mode!r}")

    if abs(factor - 1.0) < 0.01:
        return image

    width = max(1, round(image.width * factor))
    height = max(1, round(image.height * factor))
    return image.resize((width, height), Image.LANCZOS)


def prepare(
    image: Image.Image,
    reference: Image.Image | None = None,
    *,
    matte: bool = True,
    tolerance: int = 28,
    mode: str = "height",
    reference_scale: float = 1.0,
) -> Image.Image:
    """Make generated art ready for the reskin stage in one call.

    Order matters: remove the background before measuring, because the backdrop
    is opaque and would otherwise be counted as part of the subject's size.
    """
    prepared = remove_background(image, tolerance=tolerance) if matte else image.convert("RGBA")
    if reference is not None:
        prepared = normalize_to_reference(
            prepared,
            reference,
            mode=mode,
            reference_scale=reference_scale,
        )
    return prepared
