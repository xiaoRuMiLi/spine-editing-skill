"""Constraints: IK targets and follow bones, mirroring the official sample.

The ``mix-and-match`` export uses exactly three constraint kinds: IK on the legs,
path constraints for limbs, and transform constraints for secondary motion
(hair, skirt, hat, pupils). This module only builds the two that make sense for a
part-per-limb rig with no path attachments:

* **IK** -- a zero-length target bone at the ankle / wrist, and a two-bone chain
  reaching for it. Moving the target bends the leg or arm without touching the
  chain, which is how a walking cycle is usually driven.
* **transform (follow)** -- one control bone driving a part with a mix below 1,
  which is what gives hair its lag behind the head.

Path constraints are deliberately absent: they need a ``path`` attachment drawn
along the limb, and this pipeline has no such artwork. Adding one later is a new
attachment plus one constraint dict, not a redesign.

Coordinates here are image pixels (y down) for targets, and bone names for the
rest, so a joint table plus this recipe is enough to emit a usable document.
"""

from __future__ import annotations

from dataclasses import dataclass

from .skeleton import Joint, Skeleton

CONTROL_PARENT = "root"
"""IK targets hang off the root so they stay put in world space (same as the
sample, where ``foot-front-IK`` is parented to ``skeleton-control``)."""


@dataclass
class IkSpec:
    """One two-bone IK chain and the target it reaches for."""

    name: str
    target: str
    bones: tuple[str, ...]
    bend_positive: bool = False
    mix: float = 1.0
    softness: float = 0.0

    def as_dict(self) -> dict:
        data: dict = {
            "type": "ik",
            "name": self.name,
            "target": self.target,
            "bones": list(self.bones),
            "bendPositive": self.bend_positive,
        }
        if self.mix != 1.0:
            data["mix"] = self.mix
        if self.softness:
            data["softness"] = self.softness
        return data


@dataclass
class FollowSpec:
    """A transform constraint: ``source`` drives ``bones`` by ``mix``."""

    name: str
    source: str
    bones: tuple[str, ...]
    mix_rotate: float = 0.0
    mix_x: float = 0.0
    mix_y: float = 0.0
    use_ranges: bool = False
    """Emit the sample's ``properties`` range block. Off by default -- see as_dict."""


    def as_dict(self) -> dict:
        data: dict = {
            "type": "transform",
            "name": self.name,
            "source": self.source,
            "bones": list(self.bones),
        }
        # No ``properties`` block: with a range remap (``rotate.to.rotate.max``)
        # the runtime maps the source angle into that window, and a head at 89
        # degrees lands far outside it -- the head rotated ~60 degrees on the first
        # render. Plain mix is the honest default; add ranges later per bone.
        if self.use_ranges:
            properties: dict = {}
            if self.mix_rotate:
                properties["rotate"] = {"to": {"rotate": {"max": 100}}}
            if self.mix_x:
                properties["x"] = {"to": {"x": {"max": 100}}}
            if self.mix_y:
                properties["y"] = {"to": {"y": {"max": 100}}}
            data["properties"] = properties
        if self.mix_rotate:
            data["mixRotate"] = self.mix_rotate
        if self.mix_x:
            data["mixX"] = self.mix_x
        if self.mix_y:
            data["mixY"] = self.mix_y
        return data


def add_ik_targets(
    skeleton: Skeleton,
    targets: dict[str, tuple[float, float]],
    *,
    parent: str = CONTROL_PARENT,
) -> None:
    """Create the zero-length bones the IK chains aim at."""
    for name, (x, y) in targets.items():
        skeleton.add(Joint(name=name, parent=parent, base=(x, y), tip=(x, y)))


def bend_sign(skeleton: Skeleton, parent: str, child: str) -> bool:
    """Which way the IK chain bends, read from the pose that already exists.

    Wrong sign is not an error the runtime reports: it silently mirrors the chain.
    On the girl the left arm flipped up onto the head because ``bendPositive``
    defaulted to false while the drawn pose bends the other way. The sign is the
    cross product of the two bones' directions in Spine space (y up).
    """
    first = skeleton.by_name(parent)
    second = skeleton.by_name(child)
    if first is None or second is None:
        return False
    v1 = (first.tip[0] - first.base[0], -(first.tip[1] - first.base[1]))
    v2 = (second.tip[0] - second.base[0], -(second.tip[1] - second.base[1]))
    return (v1[0] * v2[1] - v1[1] * v2[0]) > 0


def default_constraints(skeleton: Skeleton) -> list[dict]:
    """The recipe used for the girl, in the sample's own field shapes.

    Feet and hands get IK so a walk cycle and a wave can be driven from targets;
    hair follows the head at partial mix so it lags instead of moving rigidly.
    """
    existing = {joint.name for joint in skeleton.joints}
    out: list[dict] = []

    for side in ("r", "l"):
        chain = (f"leg_{side}", f"shin_{side}")
        target = f"ik_foot_{side}"
        if target in existing and all(name in existing for name in chain):
            out.append(
                IkSpec(
                    f"foot_{side}",
                    target,
                    chain,
                    bend_positive=bend_sign(skeleton, *chain),
                ).as_dict()
            )

    for side in ("r", "l"):
        chain = (f"arm_{side}", f"fore_{side}")
        target = f"ik_hand_{side}"
        if target in existing and all(name in existing for name in chain):
            out.append(
                IkSpec(
                    f"hand_{side}",
                    target,
                    chain,
                    bend_positive=bend_sign(skeleton, *chain),
                ).as_dict()
            )

    if "head-control" in existing:
        if "head" in existing:
            out.append(
                FollowSpec(
                    "head-follow",
                    "head-control",
                    ("head",),
                    mix_rotate=1.0,
                    mix_x=1.0,
                    mix_y=1.0,
                ).as_dict()
            )
        if "hair" in existing:
            out.append(
                FollowSpec(
                    "hair-follow",
                    "head-control",
                    ("hair",),
                    mix_rotate=0.35,
                    mix_x=0.1,
                    mix_y=0.1,
                ).as_dict()
            )
    return out


def validate(constraints: list[dict], skeleton: Skeleton) -> list[str]:
    """Return human-readable problems; empty list means the set is usable."""
    known = {joint.name for joint in skeleton.joints}
    problems: list[str] = []
    for constraint in constraints:
        kind = constraint.get("type")
        name = constraint.get("name", "?")
        if kind == "ik":
            target = constraint.get("target")
            if target not in known:
                problems.append(f"{name}: unknown IK target {target!r}")
            chain = constraint.get("bones") or []
            if len(chain) < 2:
                problems.append(f"{name}: IK needs at least two bones, got {chain}")
            for bone in chain:
                if bone not in known:
                    problems.append(f"{name}: unknown bone {bone!r} in IK chain")
        elif kind == "transform":
            if constraint.get("source") not in known:
                problems.append(f"{name}: unknown source {constraint.get('source')!r}")
            for bone in constraint.get("bones") or []:
                if bone not in known:
                    problems.append(f"{name}: unknown bone {bone!r}")
        else:
            problems.append(f"{name}: unsupported constraint type {kind!r}")
    return problems
