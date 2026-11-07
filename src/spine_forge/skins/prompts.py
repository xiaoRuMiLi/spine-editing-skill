"""Prompt composition for skin generation.

Written for image-to-image services: the reference is supplied as an input image,
so the instruction's job is to say *what to redraw* and *which properties of the
reference to preserve*.

The distinction that matters is framing the reference as the object to edit
versus the style to imitate. Asking to "replace X with Y" makes the model treat
the reference as something to erase and it invents its own look. Asking it to
redraw the subject in the reference's style keeps the look.

Style words are spelled out rather than left to "same style" because these
models weight concrete terms far more heavily than abstract instructions.

The instruction is written for an image-to-image model: it is told to keep the
existing framing and style, and to change only the subject. That is what stops
the model from inventing a whole new character on a different canvas.
"""

from __future__ import annotations

from .request import SkinRequest

DEFAULT_NEGATIVE = (
    "text, watermark, signature, logo, frame, border, "
    "photograph, photorealistic, 3d render, depth of field, "
    "multiple characters, extra limbs, cropped, blurry, low quality"
)

# Concrete descriptors per art style. Vague phrases like "same style" are ignored
# by these models; naming the technique is what actually steers them.
STYLE_LIBRARY: dict[str, str] = {
    "flat-vector": (
        "flat 2D vector illustration, thick dark outlines, cel shading, "
        "hard colour blocks with no gradients, limited warm palette, "
        "simple shapes, no photographic texture, no depth of field"
    ),
    "cartoon": (
        "hand-drawn cartoon style, clean outlines, soft cel shading, "
        "expressive simplified shapes, flat background"
    ),
    "pixel": (
        "pixel art, limited palette, hard pixel edges, no anti-aliasing, "
        "no gradients"
    ),
    "watercolour": (
        "watercolour painting, soft pigment bleeds, visible paper texture, "
        "organic edges, no hard digital lines"
    ),
    "3d-render": (
        "stylised 3D render, soft global illumination, rounded forms, "
        "clean surface shading"
    ),
}

DEFAULT_STYLE = "flat-vector"

# Parts read differently in a prompt. Without a framing cue the model tends to
# draw a whole character on a small canvas.
#
# The head entry deliberately asks for a blank face layer. The rig already owns
# the eyes and beak as separate attachments hung off their own bones, so art that
# includes them double-draws the features and the template's eyes end up stacked
# under the generated ones. Replacing the face plate only keeps the rig's
# structure intact, which is the whole point of reskinning.
PART_HINTS = {
    "head": (
        "the head and face plate only, blank surface, no eyes, no pupils, "
        "no beak, no nostril, no facial features — those are separate layers"
    ),
    "body": "torso only, no head, no limbs",
    "wing": "a single wing, isolated, side view",
    "foot": "a single foot, isolated, side view",
    "beak": "only the beak, isolated, side view",
    "eye": "a single eye, isolated, front view",
    "leaf": "a single leaf, isolated",
    "wood": "one segment of branch, isolated",
}

# Viewpoint the model must match. Stated as its own clause and repeated in the
# negative list because image models honour a vague "same angle" only weakly and
# will happily return a profile for a front-facing rig; that mismatch then gets
# squashed when the art is fitted to the part it replaces.
VIEW_WORDS = {
    "front": (
        "strictly front view, symmetrical, facing the viewer directly, "
        "both eyes visible at the same height, full face, not a profile"
    ),
    "side": "strict side profile, one eye visible, facing left",
    "three-quarter": "three-quarter view, facing slightly to the left",
}

NEGATIVE_VIEW = {
    "front": "side profile, three-quarter view, profile, one eye visible, turned head",
    "side": "front view, symmetrical face, both eyes",
    "three-quarter": "strict profile, symmetrical front view",
}

# Always excluded for a head plate: the rig supplies these itself.
NEGATIVE_FEATURES = (
    "eyes, eyeballs, pupils, iris, eyelashes, beak, nostrils, "
    "facial features, mouth, teeth"
)

def _hint_for(part: str) -> str | None:
    lowered = part.lower()
    for key, hint in PART_HINTS.items():
        if key in lowered:
            return hint
    return None


def view_words(view: str | None) -> str:
    return VIEW_WORDS.get((view or "front").lower(), VIEW_WORDS["front"])


def style_words(style: str | None) -> str:
    """Expand a style key into concrete descriptors.

    An unknown key is passed through verbatim: the caller may be describing
    something the library does not cover, and dropping their words would be
    worse than trusting them.
    """
    if not style:
        return STYLE_LIBRARY[DEFAULT_STYLE]
    key = style.strip().lower()
    return STYLE_LIBRARY.get(key, style)


def compose(request: SkinRequest) -> str:
    """Build the instruction sent to the model.

    When the caller supplied ``instruction`` it is used verbatim: they may be
    describing something the defaults cannot express.
    """
    if request.instruction:
        return request.instruction

    view = (request.extra.get("view") or "front")
    style = style_words(request.style)
    pieces: list[str] = []

    # Frame the reference as the style source, not as an object to delete.
    pieces.append(
        f"Redraw the subject in the reference image as a {request.subject}, "
        "keeping exactly the same art style as the reference."
    )
    pieces.append(f"Art style: {style}.")

    # Viewpoint is restated here in full rather than as "same as reference"
    # because the abstract phrasing is routinely ignored.
    pieces.append(f"Viewpoint: {view_words(view)}.")

    hint = _hint_for(request.part)
    if hint:
        pieces.append(f"Composition: {hint}.")

    # The service cannot emit alpha; a flat fill is the next best thing and the
    # pipeline removes it afterwards.
    pieces.append(
        "Background: one plain solid colour, completely flat, "
        "no shadow, no vignette, no gradient, no props."
    )

    if request.width and request.height:
        ratio = request.width / request.height
        pieces.append(
            f"Canvas shape: aspect ratio close to {ratio:.2f}:1 "
            f"(reference is {request.width}x{request.height})."
        )

    return " ".join(pieces)


def negative(request: SkinRequest) -> str:
    """Negative prompt, caller override first, then the shared baseline.

    Two guards are always appended regardless of the caller's list:

    * the view correction, because an abstract "same angle" is routinely ignored
      and a profile returned for a front-facing rig gets squashed on fit;
    * the facial-feature exclusion, because the rig owns eyes and beak as their
      own attachments. A caller's custom negative list is about content, not
      about suppressing layers the template supplies.
    """
    view = (request.extra.get("view") or "front")
    parts: list[str] = [request.negative if request.negative else DEFAULT_NEGATIVE]

    guard = NEGATIVE_VIEW.get(view.lower())
    if guard:
        parts.append(guard)

    if request.extra.get("features_from_rig", True):
        parts.append(NEGATIVE_FEATURES)

    return ", ".join(parts)


def is_face_plate(part: str) -> bool:
    """True when the part is a head plate that must not carry its own features."""
    return "head" in part.lower()
