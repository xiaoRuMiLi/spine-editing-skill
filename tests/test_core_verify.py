"""The self-check has to catch the mistakes that cost us screenshots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spine_forge.core.verify import check_document
from spine_forge.stages import assemble

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "girl"


def _built(tmp_path: Path) -> dict:
    out = tmp_path / "out"
    result = assemble.run(
        str(EXAMPLE / "parts.json"),
        str(EXAMPLE / "rig" / "bones.json"),
        str(out),
        name="girl",
        mode="images",
        warp="legs",
    )
    return json.loads(Path(result["skeleton"]).read_text(encoding="utf-8"))


def _mesh(document: dict, slot: str = "leg-right") -> dict:
    return document["skins"][0]["attachments"][slot][slot]


def test_a_good_document_has_no_problems(tmp_path):
    assert check_document(_built(tmp_path)) == []


def test_atlas_coordinates_in_uvs_are_rejected(tmp_path):
    """The first version wrote absolute atlas UVs; that paints one flat colour.

    Reproduces the real numbers: the leg sits at (275, 340) in a 896x1024 page.
    """
    document = _built(tmp_path)
    mesh = _mesh(document)
    uvs = mesh["uvs"]
    for i in range(0, len(uvs), 2):
        uvs[i] = (275 + uvs[i] * 97) / 896
        uvs[i + 1] = (340 + (1.0 - uvs[i + 1]) * 151) / 1024
    problems = check_document(document)
    assert any("uvs span only" in problem for problem in problems)


def test_weights_that_do_not_sum_to_one_are_rejected(tmp_path):
    """A vertex whose weights sum to 0.5 sinks halfway between two bones."""
    document = _built(tmp_path)
    mesh = _mesh(document)
    vertices = mesh["vertices"]
    # First vertex: boneCount, then (boneIndex, x, y, weight)
    vertices[0] = 2.0
    vertices[1:5] = [vertices[1], vertices[2], vertices[3], 0.5]
    vertices[5:9] = [vertices[5], vertices[6], vertices[7], 0.2]
    problems = check_document(document)
    assert any("weights sum to 0.700" in problem for problem in problems)


def test_out_of_range_bone_index_is_rejected(tmp_path):
    document = _built(tmp_path)
    mesh = _mesh(document)
    mesh["vertices"][1] = 999.0  # bone index of the first influence
    problems = check_document(document)
    assert any("references bone 999" in problem for problem in problems)


def test_triangle_index_past_the_vertices_is_rejected(tmp_path):
    document = _built(tmp_path)
    mesh = _mesh(document)
    mesh["triangles"][0] = 10_000
    problems = check_document(document)
    assert any("triangle index 10000" in problem for problem in problems)


def test_ik_target_must_exist(tmp_path):
    document = _built(tmp_path)
    for constraint in document["constraints"]:
        if constraint.get("type") == "ik":
            constraint["target"] = "missing-bone"
            break
    problems = check_document(document)
    assert any("unknown IK target" in problem for problem in problems)


def test_slot_with_unknown_bone_is_rejected(tmp_path):
    document = _built(tmp_path)
    document["slots"][0]["bone"] = "nope"
    problems = check_document(document)
    assert any("unknown bone 'nope'" in problem for problem in problems)


def test_cli_check_reports_zero_problems(tmp_path, capsys):
    from spine_forge import cli

    document = _built(tmp_path)
    path = tmp_path / "girl.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert cli.main(["check", str(path)]) == 0
    assert "problems: 0" in capsys.readouterr().out
