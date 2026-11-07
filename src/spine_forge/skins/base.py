"""Abstract skin provider.

One provider == one image service. Providers receive a :class:`SkinRequest` and
return a :class:`SkinResult`; they never touch the rig, the atlas, or the
filesystem. That keeps swapping vendors a configuration change, not a refactor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .request import SkinRequest, SkinResult


class SkinProviderError(RuntimeError):
    """Raised when a provider cannot fulfil a request.

    Callers are expected to surface the message as-is: these strings end up in
    the CLI and the web UI, so they should name the provider and the reason.
    """


class SkinProvider(ABC):
    """Base class for every image service integration."""

    name: str = "base"
    """Stable identifier used in configuration and reports."""

    supports_reference: bool = False
    """True when the service accepts an input image (image-to-image).

    Providers that only do text-to-image must report False; callers then know a
    reference-based edit is impossible rather than receiving unrelated art.
    """

    @abstractmethod
    def generate(self, request: SkinRequest) -> SkinResult:
        """Produce artwork for one part.

        Must raise :class:`SkinProviderError` on any failure, including a missing
        key, a rejected request, or a response with no image in it.
        """

    def describe(self) -> dict[str, object]:
        """Small dict for logs and the ``skins:list`` style commands."""
        return {
            "name": self.name,
            "supports_reference": self.supports_reference,
        }
