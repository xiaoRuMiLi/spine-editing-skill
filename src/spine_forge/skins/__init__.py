"""Skin providers: generate replacement artwork for one rig part.

Abstract interface lives in ``base``, configuration wiring in ``factory``, and
each service in ``providers/``. Adding a vendor means adding one file under
``providers/`` and one branch in ``factory`` -- never touching callers.
"""

from .base import SkinProvider, SkinProviderError
from .factory import build_provider, available_providers
from .request import SkinRequest, SkinResult

__all__ = [
    "SkinProvider",
    "SkinProviderError",
    "SkinRequest",
    "SkinResult",
    "build_provider",
    "available_providers",
]
