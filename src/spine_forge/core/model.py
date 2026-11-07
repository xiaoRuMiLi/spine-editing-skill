"""Core data model: the in-memory shape of a Spine rig.

Zero dependencies. Everything here is plain dataclasses plus JSON dicts, so the
whole core layer can be tested without Pillow, numpy, or any image library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Bone:
    """A single bone in the skeleton hierarchy.

    x/y are RELATIVE TO THE PARENT, not world coordinates. length only affects
    how the bone is drawn in the editor; it does not change the transform.
    """

    name: str
    parent: str | None = None
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    length: float = 0.0


@dataclass
class Slot:
    """A draw slot. Slots are painted in array order, back to front."""

    name: str
    bone: str
    attachment: str = ""

    def __post_init__(self) -> None:
        if not self.attachment:
            self.attachment = self.name


@dataclass
class RegionAttachment:
    """A simple rectangular image attachment.

    x/y position the region relative to its slot's bone, at the bone origin.
    """

    name: str
    width: float
    height: float
    x: float = 0.0
    y: float = 0.0


@dataclass
class Skeleton:
    """A complete rig: metadata, hierarchy, slots, attachments, animations."""

    name: str = "skeleton"
    width: int = 400
    height: int = 600
    images: str = "./images/"
    bones: list[Bone] = field(default_factory=list)
    slots: list[Slot] = field(default_factory=list)
    attachments: dict[str, RegionAttachment] = field(default_factory=dict)
    animations: dict[str, Any] = field(default_factory=dict)

    def bone_names(self) -> set[str]:
        return {b.name for b in self.bones}

    def add_bone(self, bone: Bone) -> None:
        """Add a bone, refusing duplicates and dangling parents."""
        if bone.name in self.bone_names():
            raise ValueError(f"duplicate bone name: {bone.name}")
        if bone.parent is not None and bone.parent not in self.bone_names():
            raise ValueError(
                f"bone {bone.name!r} references parent {bone.parent!r} "
                "which is not defined yet; parents must come first"
            )
        self.bones.append(bone)

    def add_slot(self, slot: Slot) -> None:
        if slot.bone not in self.bone_names():
            raise ValueError(f"slot {slot.name!r} references unknown bone {slot.bone!r}")
        if any(s.name == slot.name for s in self.slots):
            raise ValueError(f"duplicate slot name: {slot.name}")
        self.slots.append(slot)

    def add_attachment(self, att: RegionAttachment) -> None:
        if att.name in self.attachments:
            raise ValueError(f"duplicate attachment name: {att.name}")
        self.attachments[att.name] = att

    def validate(self) -> list[str]:
        """Return human-readable problems; empty list means the rig is sound."""
        problems: list[str] = []

        names: list[str] = []
        for bone in self.bones:
            if bone.name in names:
                problems.append(f"duplicate bone: {bone.name}")
            names.append(bone.name)

        for index, bone in enumerate(self.bones):
            if bone.parent is not None and bone.parent not in names[:index]:
                problems.append(
                    f"bone {bone.name!r}: parent {bone.parent!r} must be defined before it"
                )

        slot_names: set[str] = set()
        for slot in self.slots:
            if slot.name in slot_names:
                problems.append(f"duplicate slot: {slot.name}")
            slot_names.add(slot.name)
            if slot.bone not in set(names):
                problems.append(f"slot {slot.name!r}: unknown bone {slot.bone!r}")
            if slot.attachment and slot.attachment not in self.attachments:
                problems.append(
                    f"slot {slot.name!r}: attachment {slot.attachment!r} has no definition"
                )

        return problems
