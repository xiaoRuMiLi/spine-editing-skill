"""Assemble separated part PNGs into one canvas using their real positions.

Needed for testing `split`: the pipeline's entry point takes a SINGLE image, but
production art arrives as a pile of loose part files. This script places parts
at approximate body positions so the result is a realistic stand-in for an
exported character sheet.

Part offsets are read from a layout table below. They are approximate: good
enough to prove the plumbing, not a substitute for real artwork.

Usage:
    python assemble.py --parts ./spineboy_real --out character.png
"""

from __future__ import annotations

import argparse
import os

from PIL import Image

# name -> (left, top) placement on the canvas, in image coordinates.
# Stacked to resemble a standing humanoid: head on top, torso below, arms out
# to the sides, legs at the bottom.
LAYOUT: dict[str, tuple[int, int]] = {
    "head": (170, 20),
    "neck": (287, 300),
    "torso": (250, 330),
    "front-upper-arm": (330, 350),
    "front-bracer": (335, 440),
    "rear-upper-arm": (215, 350),
    "front-thigh": (285, 500),
    "front-shin": (270, 600),
    "front-foot": (245, 775),
    "rear-thigh": (240, 505),
    "rear-shin": (225, 595),
    "rear-foot": (195, 765),
}

CANVAS = (700, 900)


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble parts into one image")
    parser.add_argument("--parts", required=True, help="directory of part PNGs")
    parser.add_argument("--out", required=True, help="output image path")
    parser.add_argument("--canvas", default="700x900", help="WxH, default 700x900")
    args = parser.parse_args()

    width, height = (int(v) for v in args.canvas.lower().split("x"))
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    placed = 0
    missing: list[str] = []
    for name, (left, top) in LAYOUT.items():
        path = os.path.join(args.parts, name + ".png")
        if not os.path.isfile(path):
            missing.append(name)
            continue
        with Image.open(path) as part:
            canvas.alpha_composite(part.convert("RGBA"), (left, top))
        placed += 1

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    canvas.save(args.out)
    print(f"placed {placed} parts on {width}x{height} -> {args.out}")
    if missing:
        print(f"missing: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
