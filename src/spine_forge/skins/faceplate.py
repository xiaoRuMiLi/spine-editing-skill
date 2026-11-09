"""Remove rig-owned features from generated head plates.

The rig hangs eyes, pupils and beaks on their own slots, attached to their own
bones. A generated face plate that draws them too produces doubled features:
the template's eye lands on top of the generated one and the mismatch reads as a
ghost.

Prompting cannot fix this reliably -- tested on qwen-image: the negative list
named ``eyes, eyeballs, pupils, iris, eyelashes, beak, nostrils`` and the model
painted them anyway. So the suppression happens here, geometrically, driven by
the rig itself: every attachment whose name looks like a feature is projected
into the plate's own pixel frame, and that area is painted back to the plate's
surrounding colour.

Pure geometry, no detection model, no extra dependency: positions come from the
skeleton, which already knows exactly where every feature sits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from PIL import Image, ImageDraw, ImageFilter

from ..core.rig import Rig

FEATURE_KEYWORDS: tuple[str, ...] = (
    "eye",
    "pupil",
    "iris",
    "eyelid",
    "lid",
    "beak",
    "nostril",
    "mouth",
)
"""Substrings that mark an attachment as rig-owned face furniture."""

Matrix = tuple[float, float, float, float, float, float]
"""Affine (a, b, c, d, tx, ty): x' = a*x + c*y + tx, y' = b*x + d*y + ty."""


@dataclass(frozen=True)
class FeatureZone:
    """An ellipse to erase, in pixel coordinates of a specific plate image."""

    name: str
    cx: float
    cy: float
    rx: float
    ry: float

    def contains(self, x: float, y: float) -> bool:
        if self.rx <= 0 or self.ry <= 0:
            return False
        dx = (x - self.cx) / self.rx
        dy = (y - self.cy) / self.ry
        return dx * dx + dy * dy <= 1.0


@dataclass
class BlankReport:
    zones: list[FeatureZone] = field(default_factory=list)
    filled: int = 0
    skipped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "zones": [z.name for z in self.zones],
            "filled": self.filled,
            "skipped": self.skipped,
            "mode": "fill",
        }


# --------------------------------------------------------------- transforms


def _mat_mul(m: Matrix, n: Matrix) -> Matrix:
    a, b, c, d, tx, ty = m
    a2, b2, c2, d2, tx2, ty2 = n
    return (
        a * a2 + c * b2,
        b * a2 + d * b2,
        a * c2 + c * d2,
        b * c2 + d * d2,
        a * tx2 + c * ty2 + tx,
        b * tx2 + d * ty2 + ty,
    )


def _mat_apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, tx, ty = m
    return (a * x + c * y + tx, b * x + d * y + ty)


def _local_matrix(bone: dict[str, Any]) -> Matrix:
    """Spine bone transform: translate, then rotate, then scale."""
    import math

    rot = math.radians(float(bone.get("rotation", 0.0)))
    sx = float(bone.get("scaleX", 1.0))
    sy = float(bone.get("scaleY", 1.0))
    cos, sin = math.cos(rot), math.sin(rot)
    return (cos * sx, sin * sx, -sin * sy, cos * sy, float(bone.get("x", 0.0)), float(bone.get("y", 0.0)))


def bone_matrix(rig: Rig, bone_name: str, root: str) -> Matrix:
    """Transform from ``root``'s frame into ``bone_name``'s frame.

    Raises ``ValueError`` when ``bone_name`` is not a descendant of ``root``: a
    feature that is not carried by the plate's bone chain cannot be expressed in
    the plate's frame, and silently returning identity is how decorations end up
    erased in the wrong place.
    """
    if bone_name == root:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    chain: list[dict[str, Any]] = []
    current = bone_name
    while current and current != root:
        bone = rig.bone(current)
        if bone is None:
            raise ValueError(f"unknown bone in chain: {current!r}")
        chain.append(bone)
        current = bone.get("parent")
    if current != root:
        raise ValueError(f"bone {bone_name!r} is not a descendant of {root!r}")

    matrix: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for bone in reversed(chain):  # parent-first
        matrix = _mat_mul(matrix, _local_matrix(bone))
    return matrix


# ---------------------------------------------------------- local geometry


def attachment_box(attachment: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Centre and size of a *region* attachment in its bone's local frame.

    Returns ``None`` for meshes: their ``vertices`` are a variable-stride stream
    (and weighted vertices live in several bones' frames at once), so their
    geometry is computed by :func:`mesh_points` instead. Guessing x/y pairs out
    of that stream produced eye zones 300px wide on a 597px plate during
    development -- exactly the kind of quiet wrong answer this module must not
    produce.
    """
    if attachment.get("type") == "mesh" or attachment.get("vertices"):
        return None
    width = float(attachment.get("width", 0.0))
    height = float(attachment.get("height", 0.0))
    return (float(attachment.get("x", 0.0)), float(attachment.get("y", 0.0)), width, height)


def _decode_vertices(vertices: list[float]) -> list[list[float]]:
    """Split Spine's flat vertex array into per-vertex runs.

    Format per vertex: ``[boneCount] [boneIndex x y weight] * boneCount``, with
    ``boneCount == 0`` meaning a plain ``[x y]`` pair in the attachment's own
    bone frame. Mirrors ``reskin.propagate`` so both read the same layout.
    """
    runs: list[list[float]] = []
    index = 0
    total = len(vertices)
    while index < total:
        count = int(vertices[index])
        if count == 0:
            runs.append(vertices[index:index + 3])
            index += 3
            continue
        run_len = 1 + count * 4
        runs.append(vertices[index:index + run_len])
        index += run_len
    return runs


def mesh_points(
    rig: Rig,
    attachment: dict[str, Any],
    slot_bone: str,
    plate_bone: str,
) -> list[tuple[float, float]]:
    """Mesh vertices expressed in the plate bone's frame.

    Weighted vertices are blended across the bones they name; unweighted ones sit
    in the slot bone's frame. Returns ``[]`` when the stream cannot be decoded,
    so a malformed attachment degrades to "no zone" instead of a wild ellipse.
    """
    vertices = attachment.get("vertices") or []
    if not vertices:
        return []

    bones = rig.bones
    try:
        own_matrix = bone_matrix(rig, slot_bone, plate_bone)
    except ValueError:
        return []

    matrices: dict[int, Matrix] = {}

    def matrix_for(index: int) -> Matrix:
        if index not in matrices:
            if not 0 <= index < len(bones):
                raise ValueError(f"bone index {index} out of range")
            matrices[index] = bone_matrix(rig, bones[index]["name"], plate_bone)
        return matrices[index]

    points: list[tuple[float, float]] = []
    try:
        for run in _decode_vertices(list(vertices)):
            if int(run[0]) == 0:
                points.append(_mat_apply(own_matrix, float(run[1]), float(run[2])))
                continue
            px = py = 0.0
            count = int(run[0])
            for step in range(count):
                base = 1 + step * 4
                bone_index = int(run[base])
                x = float(run[base + 1])
                y = float(run[base + 2])
                weight = float(run[base + 3])
                wx, wy = _mat_apply(matrix_for(bone_index), x, y)
                px += wx * weight
                py += wy * weight
            points.append((px, py))
    except (ValueError, IndexError):
        return []
    return points


def _bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (
        (min(xs) + max(xs)) / 2,
        (min(ys) + max(ys)) / 2,
        max(max(xs) - min(xs), 1e-6),
        max(max(ys) - min(ys), 1e-6),
    )


def is_feature(name: str, keywords: Iterable[str] = FEATURE_KEYWORDS) -> bool:
    lowered = name.lower()
    return any(keyword in lowered for keyword in keywords)


def _skin_map(rig: Rig, skin: str) -> dict[str, dict[str, dict[str, Any]]]:
    skins = rig.data.get("skins")
    if isinstance(skins, list):
        for entry in skins:
            if entry.get("name") == skin:
                return entry.get("attachments") or {}
        if skins:
            return skins[0].get("attachments") or {}
        return {}
    if isinstance(skins, dict):
        return skins.get(skin) or skins.get("default") or {}
    return {}


def plate_attachment(rig: Rig, slot: str, skin: str = "default") -> dict[str, Any]:
    slot_entry = rig.slot(slot)
    if slot_entry is None:
        raise ValueError(f"unknown slot: {slot!r}")
    name = slot_entry.get("attachment")
    if not name:
        raise ValueError(f"slot {slot!r} has no attachment")
    attachment = rig.attachment(slot, name, skin)
    if attachment is None:
        raise ValueError(f"slot {slot!r} has no attachment {name!r} in skin {skin!r}")
    return attachment


def _feature_box(
    rig: Rig,
    attachment: dict[str, Any],
    slot_bone: str,
    plate_bone: str,
) -> tuple[float, float, float, float] | None:
    """Centre and size of a feature attachment in the plate bone's frame."""
    box = attachment_box(attachment)
    if box is not None:
        cx, cy, width, height = box
        try:
            matrix = bone_matrix(rig, slot_bone, plate_bone)
        except ValueError:
            # Hangs off a bone outside the plate's chain: it cannot be expressed
            # in this frame, so it is skipped rather than guessed at.
            return None
        x, y = _mat_apply(matrix, cx, cy)
        return (x, y, width, height)
    return _bbox(mesh_points(rig, attachment, slot_bone, plate_bone))


def plate_geometry(
    rig: Rig, plate_slot: str, skin: str = "default"
) -> tuple[float, float, float, float]:
    """The plate attachment's box in rig units: ``(left, top, width, height)``.

    ``left``/``top`` are in image orientation (y grows down), so a zone expressed
    in this frame can be scaled to pixels by dividing by ``width``/``height``.
    Raises ``ValueError`` when the attachment carries no usable geometry.
    """
    plate = plate_attachment(rig, plate_slot, skin)
    bone = rig.slot(plate_slot)["bone"]
    box = attachment_box(plate) or _bbox(mesh_points(rig, plate, bone, bone))
    if box is None:
        raise ValueError(f"plate attachment on slot {plate_slot!r} has no geometry")
    cx, cy, width, height = box
    return (cx - width / 2, cy + height / 2, width, height)


def feature_zones(
    rig: Rig,
    plate_slot: str,
    *,
    image_size: tuple[int, int] | None = None,
    skin: str = "default",
    keywords: Iterable[str] = FEATURE_KEYWORDS,
    padding: float = 0.0,
    scale: float = 1.0,
) -> list[FeatureZone]:
    """Every rig-owned feature projected into the plate's own pixel frame.

    ``image_size`` is the pixel size of the plate image the zones will be used
    on. Passing ``None`` returns bone-local units instead, which is useful for
    testing the maths without an image.

    ``scale`` divides the result when the plate image is a downscaled copy of the
    atlas page (``page.scale``); the caller passes the page scale it used.
    """
    left, top, plate_w, plate_h = plate_geometry(rig, plate_slot, skin)
    plate_bone = rig.slot(plate_slot)["bone"]

    px_per_unit_x = image_size[0] / plate_w if image_size and plate_w else 1.0
    px_per_unit_y = image_size[1] / plate_h if image_size and plate_h else 1.0

    zones: list[FeatureZone] = []
    for slot_entry in rig.slots:
        name = slot_entry.get("attachment")
        if not name or not is_feature(name, keywords):
            continue
        attachment = rig.attachment(slot_entry["name"], name, skin)
        if attachment is None:
            continue
        bone_name = slot_entry.get("bone")
        if not bone_name:
            continue
        zone = _feature_box(rig, attachment, bone_name, plate_bone)
        if zone is None:
            continue
        bx, by, fw, fh = zone
        if image_size:
            cx = (bx - left) / (scale or 1.0) * px_per_unit_x
            cy = (top - by) / (scale or 1.0) * px_per_unit_y
            rx = (fw / 2 / (scale or 1.0)) * px_per_unit_x + padding
            ry = (fh / 2 / (scale or 1.0)) * px_per_unit_y + padding
        else:
            cx, cy, rx, ry = bx, by, fw / 2 + padding, fh / 2 + padding
        zones.append(FeatureZone(name=name, cx=cx, cy=cy, rx=rx, ry=ry))
    return zones


# ------------------------------------------------------------- pixel work


def map_zones(
    zones: Sequence[FeatureZone],
    source_size: tuple[int, int],
    target_box: tuple[float, float, float, float],
    source_box: tuple[float, float, float, float] | None = None,
) -> list[FeatureZone]:
    """Re-express zones measured on one plate onto a differently sized plate.

    ``source_box``/``target_box`` are ``(x, y, w, h)`` opaque boxes; when the
    source box is omitted the whole source image is assumed. Zones are scaled by
    the ratio of the two boxes so they keep covering the same anatomical spot
    after the generated art was resized.
    """
    sx0, sy0, sw0, sh0 = source_box or (0.0, 0.0, float(source_size[0]), float(source_size[1]))
    tx0, ty0, tw0, th0 = target_box
    kx = tw0 / sw0 if sw0 else 1.0
    ky = th0 / sh0 if sh0 else 1.0

    mapped: list[FeatureZone] = []
    for zone in zones:
        mapped.append(
            FeatureZone(
                name=zone.name,
                cx=tx0 + (zone.cx - sx0) * kx,
                cy=ty0 + (zone.cy - sy0) * ky,
                rx=zone.rx * kx,
                ry=zone.ry * ky,
            )
        )
    return mapped


def _surround_colour(image: Image.Image, zone: FeatureZone) -> tuple[int, int, int, int]:
    """Median colour of the opaque ring just outside ``zone``.

    Median rather than mean: one dark outline pixel must not drag the fill
    colour, and the ring always contains a mix of shading values.
    """
    pixels = image.load()
    width, height = image.size
    samples: list[tuple[int, int, int, int]] = []
    steps = 72
    import math

    for radius_scale in (1.08, 1.25, 1.45):
        for index in range(steps):
            angle = 2 * math.pi * index / steps
            x = int(zone.cx + zone.rx * radius_scale * math.cos(angle))
            y = int(zone.cy + zone.ry * radius_scale * math.sin(angle))
            if 0 <= x < width and 0 <= y < height:
                r, g, b, a = pixels[x, y]
                if a > 16:
                    samples.append((r, g, b, a))
    if not samples:
        return (0, 0, 0, 0)
    channels = list(zip(*samples))
    return tuple(int(sorted(channel)[len(channel) // 2]) for channel in channels)  # type: ignore[return-value]


def blank_features(
    image: Image.Image,
    zones: Sequence[FeatureZone],
    *,
    mode: str = "fill",
    feather: int = 3,
) -> tuple[Image.Image, BlankReport]:
    """Erase ``zones`` from ``image``.

    ``mode="fill"`` paints each zone with the median colour around it, which
    keeps the plate looking like the reference plate (whose own sockets are
    blank). ``mode="clear"`` makes the zone transparent instead.
    """
    if mode not in ("fill", "clear"):
        raise ValueError(f"unknown blanking mode: {mode!r}")

    result = image.convert("RGBA").copy()
    report = BlankReport(zones=list(zones))
    width, height = result.size

    for zone in zones:
        if zone.rx <= 0 or zone.ry <= 0:
            report.skipped.append(zone.name)
            continue
        if zone.cx + zone.rx < 0 or zone.cx - zone.rx > width or zone.cy + zone.ry < 0 or zone.cy - zone.ry > height:
            report.skipped.append(zone.name)
            continue

        mask = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse(
            (zone.cx - zone.rx, zone.cy - zone.ry, zone.cx + zone.rx, zone.cy + zone.ry),
            fill=255,
        )
        if feather > 0:
            mask = mask.filter(ImageFilter.GaussianBlur(feather))

        if mode == "fill":
            patch = Image.new("RGBA", (width, height), _surround_colour(result, zone))
        else:
            patch = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        result = Image.composite(patch, result, mask)
        report.filled += 1

    return result, report
