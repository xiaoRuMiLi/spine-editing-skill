"""Work out how Spine stores unweighted mesh vertices.

Method: ``uvs`` is authoritative for vertex count because it is consumed two
values at a time. Divide ``vertices`` by that count to learn the stride actually
in use, then print the first few raw values so the layout is visible rather than
assumed.
"""

from __future__ import annotations

import json
import sys

RIG = "examples/owl/export/owl-pro.json"
SLOTS = ["beak", "beak-down", "eye-iris"]


def main() -> int:
    with open(RIG, encoding="utf-8") as handle:
        rig = json.load(handle)

    table = rig["skins"][0]["attachments"]
    print(f"{'slot':16} {'uvs':>5} {'uv_pairs':>9} {'verts':>6} {'stride':>7} {'tri':>5}")
    print("-" * 60)
    for slot in table:
        att = next(iter(table[slot].values()))
        if att.get("type") != "mesh":
            continue
        uvs = att.get("uvs") or []
        verts = att.get("vertices") or []
        tris = att.get("triangles") or []
        pairs = len(uvs) // 2
        stride = (len(verts) / pairs) if pairs else 0
        print(f"{slot:16} {len(uvs):5} {pairs:9} {len(verts):6} {stride:7.2f} {len(tris)//3:5}")

    print("\n--- first 12 raw values, per mesh with non-integer stride ---")
    for slot in table:
        att = next(iter(table[slot].values()))
        if att.get("type") != "mesh":
            continue
        uvs = att.get("uvs") or []
        verts = att.get("vertices") or []
        pairs = len(uvs) // 2
        if not pairs:
            continue
        stride = len(verts) / pairs
        if abs(stride - round(stride)) > 0.01 or round(stride) not in (2, 3, 4):
            print(f"{slot}: stride={stride:.2f}  sample={verts[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
