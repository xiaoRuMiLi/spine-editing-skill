"""Prompt composition for skin generation.

Written for image-to-image services: the reference is supplied as an input image,
so the instruction's job is to say *what to redraw* and *which properties of the
reference to preserve*.

The templates and word lists live in ``config/prompts.json`` so the wording can
be tuned without touching code (see ``PROJECT_LOG.md`` for why). This module only
knows how to fill them in, in the right order.

Two rules are structural, not cosmetic:

* **Technique, not shapes.** The instruction asks the model to keep the
  reference's *rendering technique* and explicitly discard its *shapes*. Asking
  for "the same art style" instead is what makes the model copy the reference
  wholesale -- tested: an owl head plate came back as an owl head plate, just
  repainted.
* **Geometry is its own clause.** The new species' silhouette has to be stated
  as a required change, otherwise the model inherits the reference's outline
  (ear tufts, facial disc, ringed eye sockets) even when the subject noun says
  otherwise.

Style words are spelled out rather than left to "same style" because these
models weight concrete terms far more heavily than abstract instructions.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from .request import SkinRequest

CONFIG_RELPATH = Path("config") / "prompts.json"
"""Location of the prompt config relative to the repository root."""

CONFIG_ENV_VAR = "SPINE_PROMPTS_FILE"
"""Environment override; useful for A/B tests and for packaging."""

_REQUIRED_TEMPLATES = ("subject", "viewpoint")
_REQUIRED_NEGATIVE = ("baseline",)


class PromptConfigError(RuntimeError):
    """Raised when the prompt config is missing or malformed.

    The message names the file and the offending key: this config is meant to be
    edited by hand, so a silent default would hide exactly the mistake the editor
    made.
    """


def _repo_root() -> Path:
    """Repository root, derived from this file's location.

    ``src/spine_forge/skins/prompts.py`` -> parents[3] is the repo root.
    """
    return Path(__file__).resolve().parents[3]


def candidate_paths() -> list[Path]:
    """Every place the config may live, most specific first."""
    found: list[Path] = []
    override = os.environ.get(CONFIG_ENV_VAR, "").strip()
    if override:
        found.append(Path(override).expanduser())
    found.append(_repo_root() / CONFIG_RELPATH)
    # Installed-package fallback: walk up from the working directory.
    current = Path.cwd().resolve()
    for directory in (current, *current.parents):
        found.append(directory / CONFIG_RELPATH)
    return found


def resolve_config_path(path: str | Path | None = None) -> Path:
    """First existing candidate, or raise with the places that were tried."""
    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_file():
            raise PromptConfigError(f"prompt config not found: {candidate}")
        return candidate
    for candidate in candidate_paths():
        if candidate.is_file():
            return candidate
    tried = "\n  ".join(str(p) for p in candidate_paths())
    raise PromptConfigError(
        "no prompt config found; looked in:\n  " + tried
    )


def _require(mapping: dict[str, Any], keys: tuple[str, ...], where: str, source: Path) -> None:
    missing = [k for k in keys if k not in mapping]
    if missing:
        raise PromptConfigError(
            f"{source}: missing {where} key(s) {', '.join(missing)}"
        )


def validate(data: dict[str, Any], source: Path) -> dict[str, Any]:
    """Check the keys this module reads, so a typo fails loudly and early."""
    _require(data, ("version", "defaults", "templates", "style_library", "negative"), "top-level", source)
    _require(data["templates"], _REQUIRED_TEMPLATES, "templates", source)
    _require(data["negative"], _REQUIRED_NEGATIVE, "negative", source)
    if not isinstance(data["style_library"], dict):
        raise PromptConfigError(f"{source}: style_library must be an object")
    return data


@lru_cache(maxsize=8)
def _load_cached(path: str) -> dict[str, Any]:
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PromptConfigError(f"{source}: invalid JSON at {error.lineno}:{error.colno}: {error.msg}") from error
    return validate(data, source)


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the prompt config.

    Cached per resolved path, so callers may invoke it per request without
    re-reading the file.
    """
    resolved = resolve_config_path(path)
    return _load_cached(str(resolved))


def reset_cache() -> None:
    """Drop the cache. Tests that rewrite the config call this."""
    _load_cached.cache_clear()


# --------------------------------------------------------------- lookups


def _defaults(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("defaults") or {}


def style_words(style: str | None, config: dict[str, Any] | None = None) -> str:
    """Expand a style key into concrete technique descriptors.

    An unknown key is passed through verbatim: the caller may be describing
    something the library does not cover, and dropping their words would be
    worse than trusting them.
    """
    data = config if config is not None else load_config()
    library: dict[str, str] = data.get("style_library") or {}
    if not style:
        fallback = _defaults(data).get("style") or "flat-vector"
        return library.get(fallback, fallback)
    key = style.strip().lower()
    return library.get(key, style)


def view_words(view: str | None, config: dict[str, Any] | None = None) -> str:
    data = config if config is not None else load_config()
    words: dict[str, str] = data.get("view_words") or {}
    key = (view or _defaults(data).get("view") or "front").lower()
    return words.get(key, words.get("front", key))


def part_hint(part: str, config: dict[str, Any] | None = None) -> str | None:
    """Composition cue for a part name, matched by substring."""
    data = config if config is not None else load_config()
    lowered = part.lower()
    for key, hint in (data.get("part_hints") or {}).items():
        if key in lowered:
            return hint
    return None


def part_structure(part: str, config: dict[str, Any] | None = None) -> str | None:
    """Required geometric change for a part name, matched by substring."""
    data = config if config is not None else load_config()
    lowered = part.lower()
    for key, structure in (data.get("part_structure") or {}).items():
        if key in lowered:
            return structure
    return data.get("default_structure")


def normalize_subject(subject: str) -> str:
    """Ensure exactly one indefinite article.

    The template says "as {subject}"; callers write both "pigeon head" and
    "a pigeon head". Without this, the first form produced "as a a pigeon head"
    in testing -- a small thing the model did not forgive.
    """
    text = subject.strip()
    lowered = text.lower()
    for article in ("a ", "an ", "the "):
        if lowered.startswith(article):
            text = text[len(article):].strip()
            break
    first = text.split(" ")[0].lower() if text else ""
    if first and first[0] in "aeiou":
        return "an " + text
    return "a " + text


# --------------------------------------------------------------- compose


def _render(template: str, values: dict[str, Any]) -> str:
    """Fill placeholders, skipping the clause when a value is missing.

    A missing placeholder means "this clause does not apply here", which is why
    it yields an empty string instead of raising: the same template set serves
    image-to-image and text-to-image paths.
    """
    for key in values:
        if "{" + key + "}" in template and not values[key]:
            return ""
    try:
        return template.format(**values)
    except KeyError:
        # Unknown placeholder in a user-edited template: skip rather than crash
        # the generation run mid-pipeline.
        return ""


def compose(request: SkinRequest, config: dict[str, Any] | None = None) -> str:
    """Build the instruction sent to the model.

    Clause order matters: subject first, then the technique/geometry split, then
    framing. Models read the opening clause as the primary instruction.

    When the caller supplied ``instruction`` it is used verbatim: they may be
    describing something the defaults cannot express.
    """
    if request.instruction:
        return request.instruction

    data = config if config is not None else load_config()
    templates: dict[str, str] = data.get("templates") or {}
    defaults = _defaults(data)

    view = request.extra.get("view") or defaults.get("view") or "front"
    style = style_words(request.style, data)
    style_from_reference = bool(
        request.extra.get("style_from_reference", defaults.get("style_from_reference", True))
    )

    pieces: list[str] = []

    # 1. what to draw
    subject = normalize_subject(request.subject)
    pieces.append(_render(templates["subject"], {"subject": subject}))

    # 2. what of the reference to keep: technique only, shapes discarded
    technique_key = "technique_from_reference" if style_from_reference else "technique_standalone"
    technique_template = templates.get(technique_key) or templates.get("technique_standalone")
    if technique_template and style:
        pieces.append(_render(technique_template, {"style": style}))

    # 3. what must change geometrically
    structure = request.extra.get("structure")
    if structure is None:
        structure = part_structure(request.part, data)
    if structure:
        template = templates.get("structure")
        if template:
            pieces.append(_render(template, {"structure": structure}))

    # 4. framing
    pieces.append(_render(templates["viewpoint"], {"view": view_words(view, data)}))

    hint = part_hint(request.part, data)
    if hint and templates.get("composition"):
        pieces.append(_render(templates["composition"], {"composition": hint}))

    # 5. canvas: the service cannot emit alpha, so a flat fill it is; the
    #    pipeline removes it afterwards with assets/matting.py.
    background = data.get("background")
    if background and templates.get("background"):
        pieces.append(_render(templates["background"], {"background": background}))

    if request.width and request.height and templates.get("aspect"):
        ratio = request.width / request.height
        pieces.append(
            _render(
                templates["aspect"],
                {"ratio": f"{ratio:.2f}", "width": request.width, "height": request.height},
            )
        )

    return " ".join(piece for piece in pieces if piece)


def negative(request: SkinRequest, config: dict[str, Any] | None = None) -> str:
    """Negative prompt, caller override first, then the configured guards.

    Two guards are always appended regardless of the caller's list:

    * the view correction, because an abstract "same angle" is routinely ignored
      and a profile returned for a front-facing rig gets squashed on fit;
    * the facial-feature exclusion, because the rig owns eyes and beak as their
      own attachments. A caller's custom negative list is about content, not
      about suppressing layers the template supplies.
    """
    data = config if config is not None else load_config()
    negative_cfg: dict[str, Any] = data.get("negative") or {}
    defaults = _defaults(data)
    view = (request.extra.get("view") or defaults.get("view") or "front").lower()

    parts: list[str] = [request.negative or negative_cfg.get("baseline", "")]

    guard = (negative_cfg.get("view") or {}).get(view)
    if guard:
        parts.append(guard)

    features_on = bool(
        request.extra.get("features_from_rig", defaults.get("features_from_rig", True))
    )
    if features_on and negative_cfg.get("features_from_rig"):
        parts.append(negative_cfg["features_from_rig"])

    return ", ".join(part for part in parts if part)


def is_face_plate(part: str) -> bool:
    """True when the part is a head plate that must not carry its own features."""
    return "head" in part.lower()


# ------------------------------------------------------------- compat API
#
# These module-level names existed before the config split. They are recomputed
# on first access instead of at import time, so a missing config does not break
# importing the module (the error surfaces on use, with the file path in it).

_COMPAT: dict[str, Any] = {
    "DEFAULT_NEGATIVE": lambda: load_config()["negative"]["baseline"],
    "STYLE_LIBRARY": lambda: load_config()["style_library"],
    "PART_HINTS": lambda: load_config().get("part_hints", {}),
    "VIEW_WORDS": lambda: load_config().get("view_words", {}),
    "DEFAULT_STYLE": lambda: load_config()["defaults"].get("style", "flat-vector"),
}


def __getattr__(name: str) -> Any:  # pragma: no cover - thin shim
    factory = _COMPAT.get(name)
    if factory is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return factory()
