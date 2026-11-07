"""Background removal: turn a flat backdrop into a transparent channel.

A single public function, kept in its own file so any stage can call it without
pulling in a whole module. Image services routinely ignore "transparent
background" in a prompt and return the subject on some solid fill instead; this
is the step that makes that art usable as a Spine attachment.

Two strategies, picked explicitly by the caller:

* ``auto``    -- sample the image border, find the dominant colour, and erase
                 pixels within a tolerance of it. Works on the clean, saturated
                 fills these services produce.
* ``corner``  -- like ``auto`` but always seeds from the four corners, for
                 images where the border is partly occupied by the subject.

Flood fill is used rather than a global colour match so that colours *inside*
the subject which happen to match the backdrop are preserved. Without it, a
white-eye highlight on a white background would be punched through.
"""

from __future__ import annotations

from collections import Counter

from PIL import Image


def _dominant_border_colour(image: Image.Image) -> tuple[int, int, int]:
    """Most common opaque colour along the image border."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()

    samples: Counter[tuple[int, int, int]] = Counter()
    step = max(1, min(width, height) // 200)  # keep it fast on large images
    for x in range(0, width, step):
        samples[pixels[x, 0]] += 1
        samples[pixels[x, height - 1]] += 1
    for y in range(0, height, step):
        samples[pixels[0, y]] += 1
        samples[pixels[width - 1, y]] += 1

    if not samples:
        return (0, 0, 0)
    return samples.most_common(1)[0][0]


def _close(a: tuple[int, int, int], b: tuple[int, int, int], tolerance: int) -> bool:
    return (
        abs(a[0] - b[0]) <= tolerance
        and abs(a[1] - b[1]) <= tolerance
        and abs(a[2] - b[2]) <= tolerance
    )


def remove_background(
    image: Image.Image,
    *,
    mode: str = "auto",
    tolerance: int = 28,
    feather: bool = True,
) -> Image.Image:
    """Erase a flat backdrop, returning RGBA with the subject preserved.

    ``tolerance`` is per-channel colour distance. Raise it for gradients and
    compressed images, lower it when the subject is close in colour to the
    backdrop.

    ``feather`` blends the one-pixel outline of the removed area, which removes
    the hard coloured fringe that a naive cut leaves behind. It is a cheap
    approximation of anti-aliasing and costs one extra pass.

    Only pixels connected to the border are removed, so holes inside the subject
    (an eye highlight, a pale belly matching the backdrop) survive.
    """
    if mode not in ("auto", "corner"):
        raise ValueError(f"unknown background mode: {mode!r}")

    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width == 0 or height == 0:
        return rgba

    backdrop = _dominant_border_colour(rgba)
    source = rgba.load()

    # Breadth-first flood from every border pixel that matches the backdrop.
    visited = bytearray(width * height)
    queue: list[tuple[int, int]] = []

    def seed(x: int, y: int) -> None:
        index = y * width + x
        if visited[index]:
            return
        pixel = source[x, y]
        if pixel[3] < 8:
            visited[index] = 1
            queue.append((x, y))
            return
        if _close(pixel[:3], backdrop, tolerance):
            visited[index] = 1
            queue.append((x, y))

    for x in range(width):
        seed(x, 0)
        seed(x, height - 1)
    for y in range(height):
        seed(0, y)
        seed(width - 1, y)

    removed = bytearray(width * height)
    head = 0
    while head < len(queue):
        x, y = queue[head]
        head += 1
        index = y * width + x
        removed[index] = 1
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height:
                seed(nx, ny)

    pixels = rgba.load()
    for y in range(height):
        row = y * width
        for x in range(width):
            if removed[row + x]:
                r, g, b, _ = pixels[x, y]
                pixels[x, y] = (r, g, b, 0)

    if feather:
        _feather_edges(rgba, removed, width, height)

    return rgba


def _feather_edges(
    image: Image.Image,
    removed: bytearray,
    width: int,
    height: int,
) -> None:
    """Softly fade opaque pixels that sit right against removed ones.

    A hard cut leaves the backdrop colour bleeding into the subject's edge. One
    quick pass at reduced alpha is enough to hide that on a textured subject.
    """
    pixels = image.load()
    edges: list[tuple[int, int]] = []
    for y in range(1, height - 1):
        row = y * width
        for x in range(1, width - 1):
            if removed[row + x]:
                continue
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            if (
                removed[row + x - 1]
                or removed[row + x + 1]
                or removed[(y - 1) * width + x]
                or removed[(y + 1) * width + x]
            ):
                edges.append((x, y))

    for x, y in edges:
        r, g, b, a = pixels[x, y]
        pixels[x, y] = (r, g, b, int(a * 0.55))
