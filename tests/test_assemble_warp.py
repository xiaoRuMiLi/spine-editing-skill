"""assemble --warp legs, on the real example: one image per leg, bent by weights.

The regression here is a weight LEAK: the first version weighted a vertex by its
projection onto the SHIN's axis, so the top-left corner of the leg's bounding box
(80 px away from the knee, but beside the shin line) was handed to ``shin_*``.
Dragging the knee then dragged the top of the thigh along and the leg looked torn
apart. Walking the whole bone chain and taking the nearest point fixes it, and
"nothing in the top row is weighted to the shin" is the assertion that catches it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spine_forge.rig.mesh import grid_topology
from spine_forge.stages import assemble

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "girl"


def _build(tmp_path: Path, warp: str = "legs"):
    out = tmp_path / "out"
    result = assemble.run(
        str(EXAMPLE / "parts.json"),
        str(EXAMPLE / "rig" / "bones.json"),
        str(out),
        name="girl",
        mode="images",
        warp=warp,
    )
    document = json.loads((out / "girl.json").read_text(encoding="utf-8"))
    return result, document, out


def _decode(mesh: dict) -> list[list[tuple[int, float, float, float]]]:
    """Weighted vertices: [{bone_index, x, y, weight}, ...] per vertex."""
    flat = mesh["vertices"]
    out = []
    i = 0
    while i < len(flat):
        count = int(flat[i])
        i += 1
        entries = []
        for _ in range(count):
            entries.append((int(flat[i]), flat[i + 1], flat[i + 2], flat[i + 3]))
            i += 4
        out.append(entries)
    return out


def _grid(document: dict, slot: str, result: dict) -> tuple[int, int]:
    """Vertex order for a slot's mesh (cols, rows are reported by the stage)."""
    cols, rows = result["meshes"][slot]["grid"]
    assert len(grid_topology(cols, rows)[0]) == len(_decode(document["skins"][0]["attachments"][slot][slot]))
    return cols, rows


def test_each_leg_is_one_mesh_instead_of_two_halves(tmp_path):
    result, document, out = _build(tmp_path)
    attachments = document["skins"][0]["attachments"]

    assert "leg-right" in attachments and "leg-left" in attachments
    assert "leg-right-up" not in attachments and "leg-left-down" not in attachments
    for slot in ("leg-right", "leg-left"):
        mesh = attachments[slot][slot]
        assert mesh["type"] == "mesh"
        assert mesh["hull"] > 0
        assert len(mesh["triangles"]) % 3 == 0
        assert (out / "images" / f"{slot}.png").exists()

    assert result["slots"] == 11
    assert set(result["meshes"]) == {"leg-right", "leg-left"}


def test_nothing_above_the_knee_is_weighted_to_the_shin(tmp_path):
    """The pale-crescent bug: the top row of the leg box must stay on the thigh."""
    result, document, _ = _build(tmp_path)
    names = [bone["name"] for bone in document["bones"]]
    attachments = document["skins"][0]["attachments"]

    for slot in ("leg-right", "leg-left"):
        mesh = attachments[slot][slot]
        lower = names.index("shin_r" if slot == "leg-right" else "shin_l")
        cols, rows = _grid(document, slot, result)
        order, _, _, _ = grid_topology(cols, rows)

        for (i, j), entries in zip(order, _decode(mesh)):
            assert sum(entry[3] for entry in entries) == pytest.approx(1.0, abs=1e-3)
            if j == 0:
                assert len(entries) == 1, f"{slot} top row ({i},0) is blended: {entries}"
                assert entries[0][0] != lower, f"{slot} top row ({i},0) follows the shin"


def test_the_knee_still_has_a_blend_band(tmp_path):
    """A rigid split would pass the test above but would not bend smoothly."""
    result, document, _ = _build(tmp_path)
    attachments = document["skins"][0]["attachments"]
    for slot in ("leg-right", "leg-left"):
        blended = [v for v in _decode(attachments[slot][slot]) if len(v) == 2]
        assert blended, f"{slot} has no two-bone vertices"
        for entries in blended:
            assert 0.0 < entries[0][3] < 1.0
        assert len(blended) >= 2
