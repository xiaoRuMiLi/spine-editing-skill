"""Reporting side of a split: contact sheet, reassembly check, statistics.

Kept out of ``colors.py`` on purpose. That module decides *what is a part*; this
one only draws what it produced, so a bug in the preview code can never change
the split. Both are used by ``stages.split`` and by the CLI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from .base import Part

CHECKER_LIGHT = (255, 255, 255, 255)
CHECKER_DARK = (210, 214, 222, 255)
TILE = 240
TILE_HEIGHT = 300
LABEL_HEIGHT = 22
COLUMNS = 5


@dataclass
class ReassemblyReport:
    coverage: float
    """Share of the figure's foreground pixels covered by at least one part."""

    mean_diff: float
    """Mean absolute RGB difference inside the figure, 0..765."""

    def as_dict(self) -> dict[str, float]:
        return {"coverage": round(self.coverage, 4), "mean_diff": round(self.mean_diff, 2)}


def _foreground_mask(source: Image.Image) -> np.ndarray:
    """Same background rule the splitter uses, so the number means the same thing."""
    rgb = np.asarray(source.convert("RGB")).astype(np.float32) / 255.0
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    saturation = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    return ~((mx > 0.90) & (saturation < 0.12))


def write_contact_sheet(parts: list[Part], out_path: str) -> str:
    """Lay every part out on a checkerboard, cropped to its box, with a label."""
    rows = max(1, (len(parts) + COLUMNS - 1) // COLUMNS)
    sheet = Image.new(
        "RGBA", (COLUMNS * TILE, rows * (TILE_HEIGHT + LABEL_HEIGHT)), (30, 32, 40, 255)
    )
    draw = ImageDraw.Draw(sheet)

    checker = Image.new("RGBA", (TILE, TILE_HEIGHT), CHECKER_LIGHT)
    checker_draw = ImageDraw.Draw(checker)
    for y in range(0, TILE_HEIGHT, 16):
        for x in range(0, TILE, 16):
            if (x // 16 + y // 16) % 2:
                checker_draw.rectangle((x, y, x + 15, y + 15), fill=CHECKER_DARK)

    for index, part in enumerate(parts):
        left, top, right, bottom = part.box
        layer = Image.open(part.image_path).convert("RGBA").crop((left, top, right, bottom))
        scale = min((TILE - 16) / max(layer.width, 1), (TILE_HEIGHT - 16) / max(layer.height, 1), 1.0)
        target = (max(1, int(layer.width * scale)), max(1, int(layer.height * scale)))
        cell = checker.copy()
        cell.alpha_composite(
            layer.resize(target, Image.LANCZOS),
            ((TILE - target[0]) // 2, (TILE_HEIGHT - target[1]) // 2),
        )
        cell_x = (index % COLUMNS) * TILE
        cell_y = (index // COLUMNS) * (TILE_HEIGHT + LABEL_HEIGHT)
        sheet.alpha_composite(cell, (cell_x, cell_y))
        draw.text(
            (cell_x + 8, cell_y + TILE_HEIGHT + 4),
            f"{part.name}   {layer.width}x{layer.height}",
            fill=(235, 238, 245, 255),
        )
        draw.rectangle(
            (cell_x, cell_y, cell_x + TILE - 1, cell_y + TILE_HEIGHT - 1),
            outline=(70, 76, 92, 255),
        )

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    sheet.save(out_path)
    return out_path


def write_reassembly(source_path: str, parts: list[Part], out_path: str) -> ReassemblyReport:
    """Stack the parts back into one picture and measure how much survived.

    The measurement is the honest part: coverage counts foreground pixels no part
    claimed, so a pruned contour shows up as a number instead of a surprise later.
    """
    source = Image.open(source_path).convert("RGBA")
    rebuilt = Image.new("RGBA", source.size, (255, 255, 255, 255))
    covered = np.zeros((source.height, source.width), dtype=bool)
    for part in parts:
        layer = Image.open(part.image_path).convert("RGBA")
        rebuilt.alpha_composite(layer)
        covered |= np.asarray(layer)[:, :, 3] > 0

    side = Image.new("RGBA", (source.width * 2 + 20, source.height), (255, 255, 255, 255))
    side.alpha_composite(source, (0, 0))
    side.alpha_composite(rebuilt, (source.width + 20, 0))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    side.save(out_path)

    foreground = _foreground_mask(source)
    total = int(foreground.sum()) or 1
    diff = np.abs(
        np.asarray(source.convert("RGB")).astype(np.int16)
        - np.asarray(rebuilt.convert("RGB")).astype(np.int16)
    ).sum(axis=2)
    return ReassemblyReport(
        coverage=float(covered[foreground].sum()) / total,
        mean_diff=float(diff[foreground].mean()),
    )
