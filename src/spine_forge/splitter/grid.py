"""Connected-component splitter (v1, no AI, no API key).

What it can do: separate parts that are already physically detached from each
other in the source image -- typically PNGs exported from a layered PSD, where
every limb sits in its own cluster of opaque pixels.

What it cannot do: understand anatomy. An upper arm and forearm drawn as one
continuous shape become ONE part here, because from the pixel level they are one
connected blob. Semantic splitting is a later splitter implementation.
"""

from __future__ import annotations

import os
from collections import deque

import numpy as np
from PIL import Image

from .base import Part

# Anything at or below this alpha counts as background.
ALPHA_THRESHOLD = 8

# Components smaller than this fraction of the image are noise (JPEG speckle,
# stray anti-aliased pixels) and get dropped.
MIN_AREA_RATIO = 0.0005


def _label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected flood fill labelling. Returns (labels, count).

    Implemented here rather than pulled from scipy so the whole splitter stays
    on numpy + Pillow, keeping the dependency surface small.
    """
    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.int32)
    current = 0
    neighbors = ((1, 0), (-1, 0), (0, 1), (0, -1))

    for start_y in range(height):
        row = mask[start_y]
        for start_x in range(width):
            if not row[start_x] or labels[start_y, start_x]:
                continue
            current += 1
            queue = deque([(start_y, start_x)])
            labels[start_y, start_x] = current
            while queue:
                y, x = queue.popleft()
                for dy, dx in neighbors:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < height and 0 <= nx < width:
                        if mask[ny, nx] and not labels[ny, nx]:
                            labels[ny, nx] = current
                            queue.append((ny, nx))
    return labels, current


def _describe(index: int, box: tuple[int, int, int, int]) -> str:
    """Name a part from its position. Pure placeholder until a semantic splitter
    exists; the names are stable so rigging can key off them."""
    left, top, right, bottom = box
    center_x = (left + right) / 2
    return f"part_{index:02d}"


class ConnectedComponentSplitter:
    """Default splitter: opaque pixel clusters become parts."""

    def split(self, source_path: str, out_dir: str) -> list[Part]:
        source = Image.open(source_path).convert("RGBA")
        arr = np.array(source)
        alpha = arr[:, :, 3]

        mask = alpha > ALPHA_THRESHOLD
        if not mask.any():
            raise ValueError(
                f"{source_path!r} has no opaque pixels; a splitter needs an "
                "image with a transparent background"
            )

        labels, count = _label_components(mask)
        if count == 0:
            raise ValueError("no components found")

        height, width = mask.shape
        min_area = max(1, int(width * height * MIN_AREA_RATIO))

        os.makedirs(out_dir, exist_ok=True)
        parts: list[Part] = []
        kept = 0

        for label in range(1, count + 1):
            ys, xs = np.where(labels == label)
            area = len(xs)
            if area < min_area:
                continue

            left, right = int(xs.min()), int(xs.max()) + 1
            top, bottom = int(ys.min()), int(ys.max()) + 1

            # Keep only this component's pixels; everything else goes
            # transparent so the PNG stays aligned to its own bounding box.
            layer = np.zeros_like(arr)
            component_mask = labels == label
            layer[component_mask] = arr[component_mask]

            cropped = layer[top:bottom, left:right]
            kept += 1
            name = _describe(kept, (left, top, right, bottom))
            path = os.path.join(out_dir, f"{name}.png")
            Image.fromarray(cropped, mode="RGBA").save(path)

            parts.append(
                Part(
                    name=name,
                    image_path=path,
                    width=right - left,
                    height=bottom - top,
                    box=(left, top, right, bottom),
                    center_x=(left + right) / 2,
                    center_y=(top + bottom) / 2,
                )
            )

        if not parts:
            raise ValueError(
                "every component was smaller than the noise threshold; "
                "the image may be mostly background"
            )

        # Reading order, top to bottom then left to right, keeps output stable
        # across runs -- which matters because these names feed rig.json.
        parts.sort(key=lambda p: (p.box[1], p.box[0]))
        return parts
