"""Concrete image service integrations, one module per vendor."""

from .null import NullSkinProvider
from .qwen import QwenSkinProvider

__all__ = ["NullSkinProvider", "QwenSkinProvider"]
