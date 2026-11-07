"""Stage: split one source image into body-part PNGs plus parts.json.

Input : one image with a transparent background
Output: <out>/parts/*.png  and  <out>/parts.json
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..splitter import ConnectedComponentSplitter


def run(source_path: str, out_dir: str, splitter=None) -> dict[str, Any]:
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"source image not found: {source_path}")

    splitter = splitter or ConnectedComponentSplitter()
    parts_dir = os.path.join(out_dir, "parts")
    parts = splitter.split(source_path, parts_dir)

    payload: dict[str, Any] = {
        "source": {
            "path": os.path.abspath(source_path),
            "splitter": type(splitter).__name__,
        },
        "parts": [
            {
                "name": p.name,
                "image": os.path.relpath(p.image_path, out_dir).replace("\\", "/"),
                "width": p.width,
                "height": p.height,
                "box": list(p.box),
                "center": [round(p.center_x, 2), round(p.center_y, 2)],
            }
            for p in parts
        ],
    }

    manifest_path = os.path.join(out_dir, "parts.json")
    os.makedirs(out_dir, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    return {"parts": len(parts), "manifest": manifest_path, "parts_dir": parts_dir}
