"""Stage: split one source image into body-part PNGs plus parts.json.

Input : one image -- either with a transparent background (``--splitter alpha``)
        or a flat colour illustration on plain paper (``--splitter colour``)
Output: <out>/parts/*.png, <out>/parts.json, and by default the two previews
        <out>/preview/parts_sheet.png and <out>/preview/reassembly.png

The stage is deliberately thin: it picks a splitter, runs it, and writes down
what happened. Everything that decides "what is a part" lives in
``spine_forge.splitter``.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..splitter import ColourSplitter, ConnectedComponentSplitter
from ..splitter import report as report_tools

SPLITTERS = {
    "alpha": ConnectedComponentSplitter,
    "colour": ColourSplitter,
}


def run(
    source_path: str,
    out_dir: str,
    splitter=None,
    *,
    kind: str = "alpha",
    previews: bool = True,
) -> dict[str, Any]:
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"source image not found: {source_path}")

    if splitter is None:
        if kind not in SPLITTERS:
            raise ValueError(f"unknown splitter: {kind!r} (expected one of {sorted(SPLITTERS)})")
        splitter = SPLITTERS[kind]()

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

    if previews and parts:
        preview_dir = os.path.join(out_dir, "preview")
        sheet = report_tools.write_contact_sheet(
            parts, os.path.join(preview_dir, "parts_sheet.png")
        )
        rebuilt = report_tools.write_reassembly(
            source_path, parts, os.path.join(preview_dir, "reassembly.png")
        )
        payload["preview"] = {"sheet": sheet, "reassembly": os.path.join(preview_dir, "reassembly.png")}
        payload["check"] = rebuilt.as_dict()

    manifest_path = os.path.join(out_dir, "parts.json")
    os.makedirs(out_dir, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    result: dict[str, Any] = {
        "parts": len(parts),
        "manifest": manifest_path,
        "parts_dir": parts_dir,
    }
    if "check" in payload:
        result["coverage"] = payload["check"]["coverage"]
        result["mean_diff"] = payload["check"]["mean_diff"]
    return result
