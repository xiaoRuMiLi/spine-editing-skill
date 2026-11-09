"""Draw a skeleton over the artwork, with a table beside it.

The deliverable a human actually reviews is this picture, not the JSON: bones
drawn 1:1 on the original art, joints marked, and every coordinate printed next to
it. Two rules keep it honest:

* the art is pasted at native scale so a joint that looks on the arm IS on the
  arm -- no rescaling that would shift every judgement by a few pixels,
* the table shows the same numbers that go into ``bones.json``, so what is
  approved on screen is what gets built.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from .skeleton import Joint

CHAIN_COLOURS = (
    (("root", "hips", "spine"), (40, 70, 210)),
    (("chest", "neck", "head"), (140, 50, 190)),
    (("hair",), (20, 150, 80)),
    (("shoulder", "arm", "fore", "hand"), (215, 45, 45)),
    (("leg", "shin", "foot"), (0, 130, 155)),
    (("ik_", "-control"), (235, 130, 20)),
)

PANEL_WIDTH = 430
ROW_HEIGHT = 22


def chain_colour(name: str) -> tuple[int, int, int]:
    for prefixes, colour in CHAIN_COLOURS:
        if any(name.startswith(prefix) for prefix in prefixes):
            return colour
    return (90, 90, 90)


def _font(size: int, bold: bool = False):
    name = "arialbd.ttf" if bold else "arial.ttf"
    try:
        return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
    except Exception:  # pragma: no cover - cosmetic only
        return ImageFont.load_default()


def _dashed(draw, start, end, colour, width: int = 1, dash: int = 6) -> None:
    import math

    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    step = dash / length
    position = 0.0
    while position < 1.0:
        a = (start[0] + dx * position, start[1] + dy * position)
        b = (start[0] + dx * min(1.0, position + step), start[1] + dy * min(1.0, position + step))
        draw.line([a, b], fill=colour, width=width)
        position += 2 * step


def _draw_bones(draw, joints: list[Joint], font, *, scale: float = 1.0) -> None:
    for joint in joints:
        colour = chain_colour(joint.name)
        base = (joint.base[0] * scale, joint.base[1] * scale)
        tip = (joint.tip[0] * scale, joint.tip[1] * scale)
        if base != tip:
            draw.line([base, tip], fill=colour, width=max(2, int(3 * scale)))
            import math

            angle = math.atan2(tip[1] - base[1], tip[0] - base[0])
            size = 8 * scale
            for delta in (math.radians(150), math.radians(-150)):
                draw.line(
                    [
                        tip,
                        (
                            tip[0] + size * math.cos(angle + delta),
                            tip[1] + size * math.sin(angle + delta),
                        ),
                    ],
                    fill=colour,
                    width=max(1, int(2 * scale)),
                )

        if joint.length == 0 and joint.name.startswith(("ik_", "head-control")):
            # A control / IK target: diamond, so it reads as "handle", not "joint".
            radius = max(5, 7 * scale)
            draw.polygon(
                [(base[0], base[1] - radius), (base[0] + radius, base[1]),
                 (base[0], base[1] + radius), (base[0] - radius, base[1])],
                outline=colour,
                fill=(255, 255, 255),
            )
        else:
            radius = max(4, 5 * scale)
            draw.ellipse(
                [base[0] - radius, base[1] - radius, base[0] + radius, base[1] + radius],
                fill=(255, 255, 255),
                outline=colour,
                width=max(1, int(2 * scale)),
            )
        draw.text(
            (base[0] + 7 * scale, base[1] - 15 * scale), joint.name, fill=colour, font=font
        )

    # IK targets get a dashed tether to the joint they drive, so the chain is
    # obvious on the panel without reading the JSON.
    driven = [j for j in joints if j.length > 0 and not j.name.startswith(("ik_", "head-control"))]
    for joint in joints:
        if not joint.name.startswith("ik_") or not driven:
            continue
        nearest = min(
            driven,
            key=lambda other: (other.base[0] - joint.base[0]) ** 2 + (other.base[1] - joint.base[1]) ** 2,
        )
        _dashed(
            draw,
            (joint.base[0] * scale, joint.base[1] * scale),
            (nearest.base[0] * scale, nearest.base[1] * scale),
            chain_colour(joint.name),
            width=max(1, int(1 * scale)),
        )


def render_panel(
    image_path: str,
    joints: list[Joint],
    out_path: str,
    *,
    title: str | None = None,
) -> str:
    """Art + bones on the left, coordinate table on the right."""
    art = Image.open(image_path).convert("RGB")
    canvas = Image.new(
        "RGB", (art.width + PANEL_WIDTH, max(art.height, 700)), (248, 249, 252)
    )
    canvas.paste(art, (0, 0))
    draw = ImageDraw.Draw(canvas)

    label_font = _font(13, bold=True)
    mono = _font(13)
    title_font = _font(18, bold=True)
    _draw_bones(draw, joints, label_font)

    x0 = art.width + 18
    draw.text((x0, 16), title or f"Skeleton draft ({len(joints)} bones)", fill=(20, 20, 24), font=title_font)
    draw.text((x0, 42), "coords = image px, y down", fill=(90, 94, 104), font=mono)

    header_y = 72
    draw.text((x0, header_y), f"{'bone':<12}{'parent':<12}{'joint x,y':>12}{'len':>7}", fill=(40, 44, 52), font=mono)
    draw.line([(x0, header_y + 20), (x0 + PANEL_WIDTH - 36, header_y + 20)], fill=(190, 194, 204), width=1)

    y = header_y + 28
    for joint in joints:
        colour = chain_colour(joint.name)
        draw.ellipse([x0, y + 5, x0 + 8, y + 13], fill=colour)
        draw.text(
            (x0 + 14, y),
            f"{joint.name:<12}{joint.parent or '-':<12}"
            f"{str((round(joint.base[0]), round(joint.base[1]))):>12}{joint.length:>7.0f}",
            fill=(30, 34, 40),
            font=mono,
        )
        y += ROW_HEIGHT

    y += 8
    for line in (
        "Blue spine | purple head | green hair",
        "Red arms | teal legs",
        "Drawn 1:1 over the source art",
    ):
        draw.text((x0, y), line, fill=(90, 94, 104), font=mono)
        y += 18

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    canvas.save(out_path)
    return out_path
