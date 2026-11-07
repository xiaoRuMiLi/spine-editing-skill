"""Model tests: hierarchy validation rules."""

from __future__ import annotations

from spine_forge.core import Bone, RegionAttachment, Skeleton, Slot


def test_validate_clean_rig_has_no_problems():
    rig = Skeleton()
    rig.add_bone(Bone("root"))
    rig.add_bone(Bone("child", parent="root"))
    rig.add_slot(Slot("child", bone="child", attachment="child"))
    rig.add_attachment(RegionAttachment("child", 10, 10))
    assert rig.validate() == []


def test_validate_reports_missing_attachment():
    rig = Skeleton()
    rig.add_bone(Bone("root"))
    # Bypass add_slot so the attachment is missing on purpose.
    rig.slots.append(Slot("s", bone="root", attachment="ghost"))
    problems = rig.validate()
    assert any("ghost" in p for p in problems)


def test_slot_defaults_attachment_name_to_slot_name():
    slot = Slot("arm", bone="arm")
    assert slot.attachment == "arm"


def test_bone_names_set():
    rig = Skeleton()
    rig.add_bone(Bone("a"))
    rig.add_bone(Bone("b", parent="a"))
    assert rig.bone_names() == {"a", "b"}
