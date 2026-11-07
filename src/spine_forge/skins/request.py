"""Data shapes for a skin request.

Deliberately dumb structs: no network, no Pillow logic, no configuration reads.
That keeps them trivially constructable in tests and keeps providers free to
decide how to talk to their service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PIL import Image


@dataclass
class SkinRequest:
    """What the caller wants a new part to look like."""

    part: str
    """Slot or attachment name being replaced, e.g. ``head-base``."""

    subject: str
    """What the new art should depict, e.g. ``pigeon head``."""

    reference: Image.Image | None = None
    """The art being replaced. A reference-capable model edits this in place,
    which is what keeps the new art in the same style and framing."""

    width: int | None = None
    """Exact canvas width to return. ``None`` lets the provider decide."""

    height: int | None = None
    """Exact canvas height to return."""

    style: str | None = None
    """Optional style hint, e.g. ``flat vector, thick outline``."""

    instruction: str | None = None
    """Full instruction override. When set, providers use this verbatim instead
    of composing one from ``subject``/``style``/``part``."""

    negative: str | None = None
    """Things to avoid, e.g. ``text, watermark, extra limbs``."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Provider-specific escape hatch; ignored by providers that do not use it."""


@dataclass
class SkinResult:
    """Artwork returned by a provider."""

    image: Image.Image
    provider: str
    model: str | None = None
    prompt: str | None = None
    notes: list[str] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    """Untouched provider response, for debugging only."""
