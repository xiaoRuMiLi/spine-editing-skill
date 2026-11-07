"""Provider registry.

Adding a vendor means adding a module under ``providers/`` and one entry in
``_BUILDERS``. Callers keep using :func:`build_provider` and never import a
concrete provider, so switching services is a configuration change.
"""

from __future__ import annotations

import os
from typing import Callable

from .base import SkinProvider, SkinProviderError

DEFAULT_PROVIDER = "qwen"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _build_qwen() -> SkinProvider:
    from .providers.qwen import DEFAULT_BASE_URL, DEFAULT_MODEL, QwenSkinProvider

    return QwenSkinProvider(
        api_key=_env("QIANWEN_API_KEY") or "",
        base_url=_env("SPINE_SKIN_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL,
        model=_env("SPINE_SKIN_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
        timeout=float(_env("SPINE_SKIN_TIMEOUT", "180") or 180),
    )


def _build_null() -> SkinProvider:
    from .providers.null import NullSkinProvider

    return NullSkinProvider()


_BUILDERS: dict[str, Callable[[], SkinProvider]] = {
    "qwen": _build_qwen,
    "null": _build_null,
}


def available_providers() -> list[str]:
    """Names that :func:`build_provider` accepts."""
    return sorted(_BUILDERS)


def build_provider(name: str | None = None) -> SkinProvider:
    """Instantiate a provider from environment configuration.

    Resolution order: explicit ``name`` argument, then ``SPINE_SKIN_PROVIDER``,
    then :data:`DEFAULT_PROVIDER`. Unknown names raise rather than silently
    falling back, so a typo in configuration surfaces immediately.
    """
    chosen = (name or _env("SPINE_SKIN_PROVIDER") or DEFAULT_PROVIDER).lower()
    builder = _BUILDERS.get(chosen)
    if builder is None:
        raise SkinProviderError(
            f"unknown skin provider {chosen!r}; available: {', '.join(available_providers())}"
        )
    return builder()
