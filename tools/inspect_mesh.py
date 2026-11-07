"""Inspect mesh attachment vertex layouts in the owl rig.

Prints the structural facts needed to decide which vertex arrays may be scaled:
attachment type, array lengths, and whether weights/bones are present.
"""

from __future__ import annotations

import json
import sys

RIG = "examples/owl/export/owl-pro.json"
SLOTS = ["beak", "beak-down", "L_eye-iris", "L_eye-light", "R_eye-iris", "R_eye-light", "head-base", "body"]


def main() -> int:
    with open(RIG, encoding="utf-8") as handle:
        rig = json.load(handle)

    table = rig["skins"][0]["attachments"]
    for slot in SLOTS:
        slot_map = table.get(slot)
        if not slot_map:
            print(f"{slot}: MISSING")
            continue
        att = next(iter(slot_map.values()))
        vertices = att.get("vertices") or []
        print(
            f"{slot:14} type={str(att.get('type')):6} "
            f"verts={len(vertices):4} "
            f"uvs={len(att.get('uvs') or []):4} "
            f"weights={'yes' if 'weights' in att else 'no':3} "
            f"bones={'yes' if 'bones' in att else 'no':3} "
            f"keys={sorted(att.keys())}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
