"""Turn a joint table into a Spine-ready bone hierarchy.

A joint is a segment: it has a base (the pivot) and a tip (where the bone points).
That is how a human reads a rig off a drawing, and it is enough to derive the two
numbers Spine actually needs -- the local ``x/y`` (offset inside the parent's
rotated frame) and the local ``rotation``.

The one conversion that bites everyone: images are measured in pixels with **y
DOWN**, Spine is **y UP**. :meth:`Skeleton.spine_bones` flips y once, at the
boundary, so nothing downstream has to remember.

Two more rules learned the hard way:

* a child's base usually equals its parent's tip, but not always (a leg branches
  off the pelvis side, not off the pelvis bone's tip) -- offsets are computed, not
  assumed,
* a zero-length bone (a control bone at a shoulder) is legal and useful; it must
  keep rotation 0 and must not be given a bogus atan2 result.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field


@dataclass
class Joint:
    """One bone segment in image pixels (y down)."""

    name: str
    parent: str | None
    base: tuple[float, float]
    tip: tuple[float, float]

    @property
    def length(self) -> float:
        return math.hypot(self.tip[0] - self.base[0], self.tip[1] - self.base[1])

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "parent": self.parent,
            "base": [round(self.base[0], 2), round(self.base[1], 2)],
            "tip": [round(self.tip[0], 2), round(self.tip[1], 2)],
        }


@dataclass
class Skeleton:
    """An ordered joint list plus the derived Spine bones."""

    joints: list[Joint] = field(default_factory=list)
    name: str = "character"

    def by_name(self, name: str) -> Joint | None:
        for joint in self.joints:
            if joint.name == name:
                return joint
        return None

    def add(self, joint: Joint) -> None:
        if joint.parent is not None and self.by_name(joint.parent) is None:
            raise ValueError(f"joint {joint.name!r} refers to unknown parent {joint.parent!r}")
        if self.by_name(joint.name) is not None:
            raise ValueError(f"duplicate joint: {joint.name!r}")
        self.joints.append(joint)

    def spine_bones(self, canvas_height: float) -> list[dict]:
        """Local Spine bones (y up). Parents must be added before children."""
        world: dict[str, dict] = {}
        bones: list[dict] = []

        for joint in self.joints:
            bx, by = joint.base[0], canvas_height - joint.base[1]
            tx, ty = joint.tip[0], canvas_height - joint.tip[1]
            if (tx, ty) == (bx, by):
                angle = 0.0
            else:
                angle = math.degrees(math.atan2(ty - by, tx - bx))

            world[joint.name] = {"x": bx, "y": by, "rotation": angle}

            if joint.parent is None:
                local_x, local_y, local_rot = bx, by, angle
            else:
                parent = world[joint.parent]
                # Undo the parent's rotation, then express the offset in it.
                radians = math.radians(-parent["rotation"])
                dx, dy = bx - parent["x"], by - parent["y"]
                local_x = dx * math.cos(radians) - dy * math.sin(radians)
                local_y = dx * math.sin(radians) + dy * math.cos(radians)
                local_rot = angle - parent["rotation"]

            bones.append(
                {
                    "name": joint.name,
                    "parent": joint.parent,
                    "x": round(local_x, 2),
                    "y": round(local_y, 2),
                    "rotation": round(local_rot, 2),
                    "length": round(joint.length, 2),
                }
            )
        return bones

    def chains(self) -> dict[str, list[str]]:
        """Longest-path-from-root grouping, useful for sanity printing."""
        children: dict[str, list[str]] = {}
        for joint in self.joints:
            children.setdefault(joint.parent or "", []).append(joint.name)
        out: dict[str, list[str]] = {}

        def walk(name: str, path: list[str]) -> None:
            path = path + [name]
            kids = children.get(name, [])
            if not kids:
                out[name] = path
                return
            for kid in kids:
                walk(kid, path)

        for root in children.get("", []):
            walk(root, [])
        return out


# ------------------------------------------------------------------ spec i/o


def load_document(path: str) -> tuple[list[Joint], list[dict]]:
    """Read a joint table plus its optional constraint list.

    Accepted shape::

        {"name": ..., "joints": [...], "constraints": [...]}

    ``constraints`` may be omitted; the caller then applies its own recipe.
    """
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    entries = data["joints"] if isinstance(data, dict) else data
    constraints = data.get("constraints", []) if isinstance(data, dict) else []
    joints = [
        Joint(
            name=entry["name"],
            parent=entry.get("parent"),
            base=(float(entry["base"][0]), float(entry["base"][1])),
            tip=(float(entry["tip"][0]), float(entry["tip"][1])),
        )
        for entry in entries
    ]
    return joints, constraints


def load_spec(path: str) -> list[Joint]:
    """Read only the joints from a spec file (constraints are ignored)."""
    return load_document(path)[0]


def save_spec(skeleton: Skeleton, path: str, constraints: list[dict] | None = None) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    payload: dict = {"name": skeleton.name, "joints": [j.as_dict() for j in skeleton.joints]}
    if constraints:
        payload["constraints"] = constraints
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path
