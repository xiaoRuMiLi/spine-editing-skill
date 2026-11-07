"""Generate a synthetic test character for the pipeline.

Draws a crude but properly SEPARATED humanoid -- head, torso, two arms, two
legs -- as disconnected pixel clusters on a transparent canvas. That is exactly
the input the v1 connected-component splitter can handle, so this fixture
proves the plumbing end to end without needing real art.

Usage:
    python make_fixture.py --out ../examples/sample_character/character.png
"""

from __future__ import annotations

import argparse
import os

from PIL import Image, ImageDraw

CANVAS = (400, 600)

# (label, box, colour) in image coordinates, y growing downward.
# Gaps between shapes are intentional: touching parts would merge into one
# component and defeat the splitter.
SHAPES = [
    ("head",   (160,  40, 240, 120), (240, 200, 170, 255)),
    ("torso",  (150, 140, 250, 320), ( 70, 130, 200, 255)),
    ("arm_l",  ( 80, 150, 140, 300), ( 60, 110, 170, 255)),
    ("arm_r",  (260, 150, 320, 300), ( 60, 110, 170, 255)),
    ("leg_l",  (165, 340, 215, 540), ( 40,  70, 120, 255)),
    ("leg_r",  (215, 340, 265, 540), ( 40,  70, 120, 255)),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a separated test character PNG")
    parser.add_argument("--out", required=True, help="output PNG path")
    args = parser.parse_args()

    canvas = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    for _label, box, colour in SHAPES:
        draw.rectangle(box, fill=colour)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    canvas.save(args.out)
    print(f"wrote {args.out} ({len(SHAPES)} shapes, {CANVAS[0]}x{CANVAS[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
