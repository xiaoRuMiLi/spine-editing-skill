"""Stage: render a self-contained HTML preview of the rig.

Fast feedback loop: after editing rig.json and rebuilding, open this page to see
whether parts landed where you meant and whether the bone tree looks sane.

Deliberately dependency free at runtime -- the atlas page is inlined as a data
URI and drawn with plain canvas, so there is no CDN, no Spine runtime, and
nothing to install.
"""

from __future__ import annotations

import base64
import io
import json
import os
from typing import Any

from PIL import Image

TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<title>{name} preview</title>
<style>
  body {{ margin: 0; background: #1e1e22; color: #d8d8e0; font: 13px/1.5 system-ui, sans-serif; }}
  .wrap {{ display: flex; height: 100vh; }}
  canvas {{ background: #2a2a30; flex: none; }}
  aside {{ padding: 14px 18px; width: 280px; overflow: auto; }}
  h3 {{ margin: 0 0 8px; font-size: 15px; }}
  code {{ color: #7fd7c8; }}
  .hint {{ color: #8a8a96; }}
</style>
<div class="wrap">
  <canvas id="c" width="{width}" height="{height}"></canvas>
  <aside>
    <h3>{name}</h3>
    <p>bones <code>{bone_count}</code> &middot; slots <code>{slot_count}</code></p>
    <label><input type="checkbox" id="showBones" checked> 显示骨骼</label>
    <p class="hint">这是开发期预览，只验证部件落位与骨骼层级。<br>
    最终效果请在 Spine 编辑器里打开 skeleton.json。</p>
  </aside>
</div>
<script>
const rig = {payload};
const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const atlas = new Image();

function drawParts() {{
  for (const item of rig.items) {{
    ctx.drawImage(atlas, item.sx, item.sy, item.w, item.h,
                  item.dx, item.dy, item.w, item.h);
  }}
}}

function drawBones() {{
  ctx.strokeStyle = '#6cf9d0';
  ctx.fillStyle = '#6cf9d0';
  for (const b of rig.bones) {{
    for (const child of b.children) {{
      ctx.beginPath();
      ctx.moveTo(b.x, b.y);
      ctx.lineTo(child.x, child.y);
      ctx.stroke();
    }}
    ctx.beginPath();
    ctx.arc(b.x, b.y, 3, 0, Math.PI * 2);
    ctx.fill();
  }}
}}

function draw() {{
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawParts();
  if (document.getElementById('showBones').checked) drawBones();
}}

atlas.onload = draw;
atlas.src = rig.atlas;
document.getElementById('showBones').addEventListener('change', draw);
</script>
"""


def _data_uri(path: str) -> str:
    with Image.open(path) as img:
        buf = io.BytesIO()
        img.convert("RGBA").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _atlas_layout(images_dir: str, names: list[str]) -> tuple[list[tuple[str, int, int, int]], int, int]:
    """Reproduce the packer's vertical stack so source rects match the page.

    Returns ([(name, y, width, height), ...], page_width, page_height).
    """
    PADDING = 2
    entries: list[tuple[str, int, int, int]] = []
    cursor = PADDING
    page_width = 0
    for name in names:
        path = os.path.join(images_dir, name + ".png")
        if not os.path.isfile(path):
            continue
        with Image.open(path) as img:
            w, h = img.size
        entries.append((name, cursor, w, h))
        page_width = max(page_width, w)
        cursor += h + PADDING
    return entries, page_width, cursor


def run(rig_path: str, out_html: str) -> dict[str, Any]:
    """Build the HTML from a rig document plus the atlas page next to it."""
    with open(rig_path, encoding="utf-8") as handle:
        rig = json.load(handle)

    rig_dir = os.path.dirname(os.path.abspath(rig_path))
    name = rig.get("skeleton", {}).get("name", "character")
    width = int(rig.get("skeleton", {}).get("width", 400))
    height = int(rig.get("skeleton", {}).get("height", 600))

    # Two document shapes arrive here: the editable rig.json draft, where
    # attachments sit at the top level as name -> {width, height, x, y}, and the
    # built Spine skeleton.json, where they nest under skins[0].attachments as
    # slot -> attachment -> {width, height, x, y}. Flatten the built shape so
    # the rest of this function has one layout to reason about.
    attachments = dict(rig.get("attachments") or {})
    for skin in rig.get("skins") or []:
        for slot_map in (skin.get("attachments") or {}).values():
            for att_name, att in slot_map.items():
                attachments.setdefault(att_name, att)

    # The atlas page is produced by `build` next to skeleton.json, named after
    # the SKELETON (which carries a user-supplied --name), while the rig document
    # itself only knows the rig. So resolve the page by globbing the output
    # directory rather than assuming it matches the rig's own name.
    page_candidates = sorted(
        os.path.join(rig_dir, entry)
        for entry in os.listdir(rig_dir)
        if entry.lower().endswith(".png")
    )
    if not page_candidates:
        raise FileNotFoundError(
            f"atlas page not found beside {rig_path!r}; run `build` first"
        )
    # Prefer an exact name match when there is one, else take the first page.
    exact = [p for p in page_candidates if os.path.basename(p)[:-4] == name]
    page_path = exact[0] if exact else page_candidates[0]

    # Absolute bone positions in canvas space, plus per-slot draw rectangles.
    # Spine's y axis grows upward while canvas y grows downward, so flip.
    positions: dict[str, tuple[float, float]] = {}
    bones_out: list[dict[str, Any]] = []
    bone_by_name: dict[str, dict[str, Any]] = {}

    for bone in rig.get("bones", []):
        bname = bone["name"]
        parent = bone.get("parent")
        if parent and parent in positions:
            px, py = positions[parent]
            x = px + float(bone.get("x", 0.0))
            y = py - float(bone.get("y", 0.0))
        else:
            x = width / 2 + float(bone.get("x", 0.0))
            y = height - float(bone.get("y", 0.0))
        positions[bname] = (x, y)
        entry = {"name": bname, "x": round(x, 2), "y": round(y, 2), "children": []}
        bones_out.append(entry)
        bone_by_name[bname] = entry

    for bone in rig.get("bones", []):
        parent = bone.get("parent")
        if parent and parent in bone_by_name:
            bone_by_name[parent]["children"].append(bone_by_name[bone["name"]])

    # Atlas layout mirrors the packer: a vertical stack, in attachment order.
    images_dir = os.path.join(rig_dir, "images")
    if not os.path.isdir(images_dir):
        images_dir = rig_dir

    slot_atts = [
        (slot.get("attachment") or slot["name"], slot["bone"])
        for slot in rig.get("slots", [])
    ]
    layout, _page_w, _page_h = _atlas_layout(images_dir, [a for a, _ in slot_atts])
    placed = {name: (y, w, h) for name, y, w, h in layout}

    items: list[dict[str, Any]] = []
    for att_name, bone_name in slot_atts:
        att = attachments.get(att_name)
        if att is None or att_name not in placed:
            continue
        sy, w, h = placed[att_name]
        bx, by = positions.get(bone_name, (width / 2, height / 2))
        # Attachment x/y is an offset from the bone origin; the image's top-left
        # lands at (bone + offset) with the image hanging BELOW that point once
        # the upward y axis is flipped to canvas coordinates.
        items.append(
            {
                "sx": 0,
                "sy": sy,
                "w": w,
                "h": h,
                "dx": round(bx + float(att.get("x", 0.0)), 2),
                "dy": round(by - float(att.get("y", 0.0)) - h, 2),
            }
        )

    payload = json.dumps(
        {
            "atlas": _data_uri(page_path),
            "items": items,
            "bones": bones_out,
        },
        ensure_ascii=False,
    )

    html = TEMPLATE.format(
        name=name,
        width=width,
        height=height,
        bone_count=len(rig.get("bones", [])),
        slot_count=len(rig.get("slots", [])),
        payload=payload,
    )

    os.makedirs(os.path.dirname(os.path.abspath(out_html)) or ".", exist_ok=True)
    with open(out_html, "w", encoding="utf-8") as handle:
        handle.write(html)

    return {"html": out_html, "items": len(items), "bones": len(bones_out)}
