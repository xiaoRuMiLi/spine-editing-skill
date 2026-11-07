"""Spine rig document: load, edit, and save ``.json`` skeleton data.

This is a thin, lossless wrapper over the JSON structure. It deliberately keeps
the original dict around so unknown fields written by the Spine editor survive a
load/save cycle -- the reskin pipeline must not silently drop data it does not
model.

Kept free of image libraries: callers that need pixels use ``assets``.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass
class AttachmentRef:
    """Where an attachment lives: skin -> slot -> attachment name."""

    slot: str
    attachment: str
    skin: str = "default"


class Rig:
    """A parsed Spine JSON document."""

    def __init__(self, data: dict[str, Any], source_path: str | None = None) -> None:
        if "bones" not in data:
            raise ValueError("not a Spine rig: missing 'bones'")
        self.data = data
        self.source_path = source_path

    # ---- construction -------------------------------------------------

    @classmethod
    def load(cls, path: str) -> "Rig":
        with open(path, encoding="utf-8") as handle:
            return cls(json.load(handle), source_path=path)

    def copy(self) -> "Rig":
        return Rig(copy.deepcopy(self.data), source_path=self.source_path)

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(self.data, handle, indent=2, ensure_ascii=False)

    # ---- metadata -----------------------------------------------------

    @property
    def meta(self) -> dict[str, Any]:
        return self.data.setdefault("skeleton", {})

    @property
    def name(self) -> str:
        return self.meta.get("name") or "skeleton"

    @property
    def version(self) -> str:
        return self.meta.get("spine", "")

    @property
    def size(self) -> tuple[float, float]:
        return float(self.meta.get("width", 0)), float(self.meta.get("height", 0))

    # ---- bones --------------------------------------------------------

    @property
    def bones(self) -> list[dict[str, Any]]:
        return self.data.setdefault("bones", [])

    def bone(self, name: str) -> dict[str, Any] | None:
        for entry in self.bones:
            if entry.get("name") == name:
                return entry
        return None

    def bone_names(self) -> list[str]:
        return [b.get("name", "") for b in self.bones]

    def children_of(self, name: str) -> list[str]:
        return [b["name"] for b in self.bones if b.get("parent") == name]

    def descendants(self, name: str) -> list[str]:
        """Every bone below ``name``, breadth first."""
        out: list[str] = []
        frontier = [name]
        while frontier:
            current = frontier.pop(0)
            for child in self.children_of(current):
                out.append(child)
                frontier.append(child)
        return out

    # ---- slots --------------------------------------------------------

    @property
    def slots(self) -> list[dict[str, Any]]:
        return self.data.setdefault("slots", [])

    def slot(self, name: str) -> dict[str, Any] | None:
        for entry in self.slots:
            if entry.get("name") == name:
                return entry
        return None

    def slots_on_bone(self, bone: str) -> list[str]:
        return [s["name"] for s in self.slots if s.get("bone") == bone]

    # ---- skins and attachments ---------------------------------------

    @property
    def skins(self) -> list[dict[str, Any]]:
        return self.data.setdefault("skins", [])

    def skin(self, name: str = "default") -> dict[str, Any] | None:
        for entry in self.skins:
            if entry.get("name") == name:
                return entry
        return None

    def attachment_table(self, skin: str = "default") -> dict[str, dict[str, Any]]:
        """Return ``{slot: {attachment_name: attachment}}`` for a skin."""
        entry = self.skin(skin)
        if entry is None:
            return {}
        return entry.setdefault("attachments", {})

    def attachment(self, slot: str, name: str | None = None, skin: str = "default") -> dict[str, Any] | None:
        table = self.attachment_table(skin)
        slot_map = table.get(slot)
        if not slot_map:
            return None
        if name is None:
            # Caller did not name one; take the only entry if unambiguous.
            if len(slot_map) == 1:
                return next(iter(slot_map.values()))
            return None
        return slot_map.get(name)

    def iter_attachments(self, skin: str = "default") -> Iterator[AttachmentRef]:
        table = self.attachment_table(skin)
        for slot_name, slot_map in table.items():
            for att_name in slot_map:
                yield AttachmentRef(slot=slot_name, attachment=att_name, skin=skin)

    def set_attachment(self, slot: str, name: str, value: dict[str, Any], skin: str = "default") -> None:
        table = self.attachment_table(skin)
        table.setdefault(slot, {})[name] = value

    # ---- constraints --------------------------------------------------

    @property
    def constraints(self) -> list[dict[str, Any]]:
        return self.data.setdefault("constraints", [])

    def constraints_on_bone(self, bone: str) -> list[dict[str, Any]]:
        out = []
        for entry in self.constraints:
            touched = entry.get("bone") or entry.get("bones") or []
            if isinstance(touched, str):
                touched = [touched]
            if bone in touched:
                out.append(entry)
        return out

    # ---- summary ------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Compact description used by the API and the UI."""
        attachments = list(self.iter_attachments())
        kinds: dict[str, int] = {}
        for ref in attachments:
            att = self.attachment(ref.slot, ref.attachment, ref.skin) or {}
            kind = att.get("type", "region")
            kinds[kind] = kinds.get(kind, 0) + 1
        return {
            "name": self.name,
            "version": self.version,
            "width": self.size[0],
            "height": self.size[1],
            "bones": len(self.bones),
            "slots": len(self.slots),
            "skins": [s.get("name") for s in self.skins],
            "attachments": len(attachments),
            "attachment_kinds": kinds,
            "animations": list((self.data.get("animations") or {}).keys()),
            "constraints": len(self.constraints),
        }


def load(path: str) -> Rig:
    return Rig.load(path)
