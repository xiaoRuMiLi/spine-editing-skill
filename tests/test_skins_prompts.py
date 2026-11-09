"""Prompt composition: config-driven templates, technique/geometry split.

Pins the three behaviours that the first live generation proved wrong:

* "same art style as the reference" made the model copy the reference wholesale
  (owl head plate -> owl head plate). The instruction must ask for the
  reference's *technique* and forbid its *shapes*.
* The species' silhouette needs its own clause, or the model inherits the
  reference's outline even when the subject noun changes.
* "as a {subject}" plus a subject already starting with "a" produced "as a a
  pigeon head". The article is normalised now.

The config is a file on disk that a human edits, so these tests also pin the
failure modes of that file: missing template, bad JSON, unknown key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spine_forge.skins import prompts
from spine_forge.skins.request import SkinRequest

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config" / "prompts.json"


@pytest.fixture()
def config():
    prompts.reset_cache()
    return prompts.load_config(REPO_CONFIG)


def req(**kwargs) -> SkinRequest:
    base = dict(part="head-base", subject="pigeon head")
    base.update(kwargs)
    return SkinRequest(**base)


# ------------------------------------------------------------------ config


def test_repo_config_is_valid_and_loads(config):
    assert config["version"] >= 1
    assert config["style_library"], "style library must not be empty"
    assert config["templates"]["subject"]


def test_missing_config_raises_with_path(tmp_path):
    with pytest.raises(prompts.PromptConfigError, match="not found"):
        prompts.load_config(tmp_path / "nope.json")


def test_invalid_json_reports_position(tmp_path):
    bad = tmp_path / "prompts.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(prompts.PromptConfigError, match="invalid JSON"):
        prompts.load_config(bad)


def test_missing_template_key_is_named(tmp_path, config):
    broken = json.loads(REPO_CONFIG.read_text(encoding="utf-8"))
    del broken["templates"]["subject"]
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(prompts.PromptConfigError, match="subject"):
        prompts.load_config(path)


def test_edited_templates_are_used(tmp_path, config):
    """The whole point of the config file: no code change to retune wording."""
    edited = json.loads(REPO_CONFIG.read_text(encoding="utf-8"))
    edited["templates"]["subject"] = "PROBE-SUBJECT {subject}"
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps(edited), encoding="utf-8")
    prompts.reset_cache()

    text = prompts.compose(req(), prompts.load_config(path))
    assert "PROBE-SUBJECT a pigeon head" in text
    prompts.reset_cache()


# ---------------------------------------------------------------- compose


def test_instruction_asks_for_technique_not_style_copying(config):
    text = prompts.compose(req(), config)
    technique = config["templates"]["technique_from_reference"]
    assert "technique" in text.lower()
    # The old wording is what caused the wholesale copy; it must not come back.
    assert "same art style" not in text.lower()
    assert technique.split("{style}")[0].strip()[:20] in text


def test_style_key_expands_from_config(config):
    text = prompts.compose(req(style="painterly-2d"), config)
    assert config["style_library"]["painterly-2d"] in text


def test_unknown_style_passes_through_verbatim(config):
    text = prompts.compose(req(style="ink wash, no outlines"), config)
    assert "ink wash, no outlines" in text


def test_structure_clause_is_present_for_known_parts(config):
    text = prompts.compose(req(), config)
    assert config["part_structure"]["head"] in text


def test_structure_clause_can_be_overridden(config):
    text = prompts.compose(req(extra={"structure": "square skull, flat brow"}), config)
    assert "square skull, flat brow" in text
    assert config["part_structure"]["head"] not in text


def test_structure_clause_can_be_disabled(config):
    text = prompts.compose(req(extra={"structure": ""}), config)
    assert config["part_structure"]["head"] not in text


def test_subject_article_is_not_doubled(config):
    for subject in ("pigeon head", "a pigeon head", "an owl head", "the dove head"):
        text = prompts.compose(req(subject=subject), config)
        assert "a a " not in text and "a an " not in text
        assert "as a pigeon head" in text or "as an owl head" in text or "as a dove head" in text


def test_aspect_clause_only_with_dimensions(config):
    without = prompts.compose(req(), config)
    assert "Canvas shape" not in without
    with_dims = prompts.compose(req(width=597, height=474), config)
    assert "1.26:1" in with_dims


def test_instruction_override_wins(config):
    text = prompts.compose(req(instruction="do exactly this"), config)
    assert text == "do exactly this"


def test_clause_order_puts_subject_first(config):
    text = prompts.compose(req(), config)
    assert text.index("Redraw the subject") < text.index("rendering technique")
    assert text.index("rendering technique") < text.index("Required geometric changes")


# --------------------------------------------------------------- negative


def test_negative_merges_baseline_view_and_features(config):
    text = prompts.negative(req(), config)
    assert config["negative"]["baseline"] in text
    assert config["negative"]["view"]["front"] in text
    assert config["negative"]["features_from_rig"] in text


def test_caller_negative_replaces_baseline_but_not_guards(config):
    text = prompts.negative(req(negative="neon colours"), config)
    assert "neon colours" in text
    assert config["negative"]["baseline"] not in text
    assert config["negative"]["features_from_rig"] in text


def test_feature_guard_can_be_disabled(config):
    text = prompts.negative(req(extra={"features_from_rig": False}), config)
    assert config["negative"]["features_from_rig"] not in text


def test_side_view_uses_its_own_guard(config):
    text = prompts.negative(req(extra={"view": "side"}), config)
    assert config["negative"]["view"]["side"] in text


# ------------------------------------------------------------- compatibility


def test_legacy_module_constants_still_resolve():
    prompts.reset_cache()
    assert prompts.DEFAULT_NEGATIVE == prompts.load_config(REPO_CONFIG)["negative"]["baseline"]
    assert "painterly-2d" in prompts.STYLE_LIBRARY
    assert prompts.is_face_plate("head-base")
