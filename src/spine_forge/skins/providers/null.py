"""Placeholder provider used when no image service is configured.

It exists so the rest of the pipeline can be exercised, and so a missing key
produces a clear sentence instead of an import error or a silent no-op.
"""

from __future__ import annotations

from ..base import SkinProvider, SkinProviderError
from ..request import SkinRequest, SkinResult


class NullSkinProvider(SkinProvider):
    name = "null"
    supports_reference = True

    def generate(self, request: SkinRequest) -> SkinResult:
        raise SkinProviderError(
            "no skin provider configured; set SPINE_SKIN_PROVIDER and the matching "
            "API key in the project .env"
        )
