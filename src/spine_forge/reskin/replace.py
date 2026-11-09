"""Apply a reskin: compose the new atlas page and patch the rig document.

This is the single entry point the server calls. It performs the three concerns
in order and returns a report, without writing anything except the files it is
explicitly asked to write.

Design notes:

* A new region is appended to the page rather than overwriting the old one. The
  old pixels stay where they are, so every attachment not part of this reskin
  keeps rendering exactly as before. Only the replaced attachment's ``path`` is
  repointed at the new region.
* Page height is grown to the next power of two. Spine's texture filtering is
  defined on power-of-two pages, and a non-power-of-two page is the kind of
  problem that shows up as soft edges only on some GPUs.
* The rig is patched in memory and returned; persistence is the caller's choice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from ..assets import atlas as atlas_io
from ..assets import images as atlas_images
from ..core.rig import Rig
from ..skins import faceplate
from ..skins.faceplate import BlankReport
from .align import AlignResult, compute_scale
from .propagate import PropagationReport, propagate_scale


@dataclass
class ReskinResult:
    rig: Rig
    atlas: atlas_io.Atlas
    page_image: Image.Image
    align: AlignResult
    propagation: PropagationReport
    region_name: str
    features: BlankReport | None = None
    notes: list[str] = field(default_factory=list)

    def report(self) -> dict[str, Any]:
        return {
            "region": self.region_name,
            "scale": round(self.align.scale, 6),
            "source_box": list(self.align.source_box),
            "target_box": list(self.align.target_box),
            "propagation": self.propagation.as_dict(),
            "features": self.features.as_dict() if self.features else None,
            "notes": self.notes,
        }


def _attachment_kind(attachment: dict[str, Any]) -> str:
    return attachment.get("type", "region")


def apply_reskin(
    rig: Rig,
    atlas: atlas_io.Atlas,
    page_image: Image.Image,
    *,
    slot: str,
    new_image: Image.Image,
    scale_mode: str = "height",
    manual_scale: float | None = None,
    skin: str = "default",
    propagate: bool = True,
    new_texture_name: str | None = None,
    blank_features: bool = False,
    feature_padding: float = 8.0,
    feature_feather: int = 8,
) -> ReskinResult:
    """Replace one slot's artwork and keep dependent geometry consistent.

    ``slot`` names the slot to change. The attachment currently on that slot
    supplies the geometry being replaced.
    """
    slot_entry = rig.slot(slot)
    if slot_entry is None:
        raise ValueError(f"unknown slot: {slot!r}")
    bone = slot_entry.get("bone")
    if not bone:
        raise ValueError(f"slot {slot!r} has no bone")

    attachment_name = slot_entry.get("attachment")
    attachment = None
    if attachment_name:
        attachment = rig.attachment(slot, attachment_name, skin)

    # An empty slot (``attachment: null``) is a deliberately hidden layer -- the
    # eye-closed toggles in this rig are exactly that. Fabricating artwork for it
    # would leave the slot and the skin disagreeing about whether it has an
    # attachment, which the runtime reads as an undefined pose and fails on.
    if attachment_name is None or attachment is None:
        raise ValueError(
            f"slot {slot!r} is currently empty (attachment is null); there is "
            "nothing to replace. Enable the attachment in Spine first, or reskin "
            "a slot that is already visible."
        )

    notes: list[str] = []
    kind = _attachment_kind(attachment)
    if kind == "mesh":
        notes.append(
            "target is a mesh attachment; vertex topology is preserved and only "
            "the sampled region changes, so unusual silhouettes may distort"
        )

    # --- where the old art lives on the page (used to measure it) ----------
    old_region_name = None
    if attachment is not None:
        old_region_name = attachment.get("path") or attachment_name
    found = atlas.find_region(old_region_name) if old_region_name else None
    if found is None:
        # Fall back to a region matching the attachment name.
        found = atlas.find_region(attachment_name or slot)

    if found is not None:
        page, old_region = found
        old_art = atlas_images.cut_region(page_image, old_region)
    else:
        page = atlas.pages[0]
        # No existing region: measure against the attachment's declared size so
        # an empty slot can still be filled.
        width = (attachment or {}).get("width", new_image.width)
        height = (attachment or {}).get("height", new_image.height)
        old_art = Image.new("RGBA", (max(1, int(width)), max(1, int(height))), (255, 255, 255, 255))
        notes.append("no existing atlas region; scale measured against the attachment size")

    # --- scale decision ---------------------------------------------------
    # An atlas packed at a reduced scale stores pixels that stand for larger rig
    # units, so the cropped source must be read in rig units or every ratio comes
    # out inflated by 1/page.scale.
    page_scale = page.scale if found is not None else 1.0
    align = compute_scale(
        old_art,
        new_image,
        mode=scale_mode,
        manual=manual_scale,
        source_scale=page_scale,
    )

    # --- compose the new atlas page --------------------------------------
    region_name = new_texture_name or f"{slot}_reskin"
    # Ensure the sprite fits width-wise and vertically before growing.
    needed = atlas_images.next_free_y(page) + align.target_box[3] - align.target_box[1] + 4
    if page_image.height < needed:
        page_image = atlas_images.grow_page(
            page_image, page, needed - page_image.height, page.size
        )

    sprite = new_image.convert("RGBA")
    if sprite.width > page_image.width:
        # Wider art than the page: grow width to the next power of two too.
        width = 1
        while width < sprite.width:
            width *= 2
        grown = Image.new("RGBA", (width, page_image.height), (0, 0, 0, 0))
        grown.paste(page_image, (0, 0))
        page_image = grown
        page.size = (width, page_image.height)

    # --- align the new art with the old -----------------------------------
    # The attachment samples "width x height" from the region's top-left corner,
    # so the opaque subject must sit at the same offset inside its box as the art
    # it replaces. Two independent shifts cause the drift seen in comparison
    # renders:
    #   1. the incoming image's own transparent margin (its opaque box does not
    #      start at 0,0),
    #   2. the region padding, which pushes the pasted pixels down a few rows.
    # Trim to the opaque box first, then paste with enough lead-in that the
    # subject lands back on its original offset.
    sb_left, sb_top, sb_right, sb_bottom = align.source_box
    tb_left, tb_top, tb_right, tb_bottom = align.target_box

    trimmed = sprite.crop((tb_left, tb_top, tb_right, tb_bottom))

    # --- erase rig-owned features the model painted anyway ----------------
    # The eye/beak layers live on their own slots, so anything the generator drew
    # in those areas would be doubled at render time. The zones come from the rig
    # and are mapped into the *sprite* frame here -- the same frame the pixels are
    # about to be pasted from -- which is why this runs after alignment and not on
    # a standalone preview. See PROJECT_LOG.md, section 十.
    features: BlankReport | None = None
    if blank_features:
        plate_left, plate_top, plate_w, plate_h = faceplate.plate_geometry(rig, slot, skin)
        if plate_w > 0 and plate_h > 0 and trimmed.width > 0 and trimmed.height > 0:
            zones = faceplate.feature_zones(
                rig,
                slot,
                image_size=(max(1, round(plate_w)), max(1, round(plate_h))),
                skin=skin,
                padding=feature_padding,
            )
            # Plate pixels -> this sprite's pixels. The generator copies the
            # reference layout, so plate coordinates transfer by box ratio.
            mapped = faceplate.map_zones(
                zones,
                source_size=(max(1, round(plate_w)), max(1, round(plate_h))),
                source_box=(0.0, 0.0, plate_w, plate_h),
                target_box=(0.0, 0.0, float(trimmed.width), float(trimmed.height)),
            )
            trimmed, features = faceplate.blank_features(
                trimmed, mapped, mode="fill", feather=feature_feather
            )
            if features.filled:
                notes.append(
                    f"blanked {features.filled} rig-owned feature zone(s) from the "
                    "generated plate so they are not drawn twice"
                )
            if features.skipped:
                notes.append("feature zones outside the plate skipped: " + ", ".join(features.skipped))
        else:
            notes.append("feature masking skipped: plate has no usable geometry")

    # Where the subject should start inside the sampled box, measured against the
    # old art. Negative means the old subject started before its own box, which
    # cannot be reproduced; clamp to zero.
    want_x = max(0, sb_left)
    want_y = max(0, sb_top)

    # Slack needed before the subject so the offset can be honoured.
    lead_x = want_x
    lead_y = want_y

    box_w = lead_x + trimmed.width
    box_h = lead_y + trimmed.height

    # The sprite handed to the packer is the padded box, with the subject placed
    # at the target offset. This keeps resize-independent and padding-agnostic:
    # whatever y ``append_to_page`` picks, the subject keeps its offset inside
    # the region.
    padded = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    padded.paste(trimmed, (lead_x, lead_y))

    if box_w > page_image.width:
        width = 1
        while width < box_w:
            width *= 2
        grown = Image.new("RGBA", (width, page_image.height), (0, 0, 0, 0))
        grown.paste(page_image, (0, 0))
        page_image = grown
        page.size = (width, page_image.height)

    new_region = atlas_images.append_to_page(
        page_image, page, region_name, padded, x=0
    )

    # --- patch the rig ----------------------------------------------------
    patched = rig.copy()
    assert attachment_name is not None

    attachment = patched.attachment(slot, attachment_name, skin)
    assert attachment is not None
    attachment["path"] = region_name
    # The attachment samples the whole region, so its size is the padded box, not
    # the trimmed subject. Reporting the subject size here would shift the art by
    # the lead-in amount.
    old_width = attachment.get("width", 0)
    cast = int if isinstance(old_width, int) and not isinstance(old_width, bool) else float
    attachment["width"] = cast(box_w)
    attachment["height"] = cast(box_h)
    # Re-centre on the bone using the new dimensions, preserving the old pivot.
    if "x" in attachment or "y" in attachment:
        old_w = old_art.width
        old_h = old_art.height
        attachment["x"] = round(float(attachment.get("x", 0)) - (old_w - box_w) / 2, 4)
        attachment["y"] = round(float(attachment.get("y", 0)) - (old_h - box_h) / 2, 4)

    propagation = PropagationReport(scale=align.scale)
    if propagate and align.scale != 1.0:
        propagation = propagate_scale(
            patched, slot=slot, bone=bone, factor=align.scale, skin=skin
        )
        # Re-assert the replaced attachment's own dimensions after propagation.
        attachment["width"] = cast(sprite.width)
        attachment["height"] = cast(sprite.height)

    return ReskinResult(
        rig=patched,
        atlas=atlas,
        page_image=page_image,
        align=align,
        propagation=propagation,
        region_name=region_name,
        features=features,
        notes=notes,
    )
