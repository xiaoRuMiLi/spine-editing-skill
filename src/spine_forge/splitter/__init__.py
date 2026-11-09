"""Splitter implementations."""

from .base import Part, Splitter
from .grid import ConnectedComponentSplitter

__all__ = ["Part", "Splitter", "ConnectedComponentSplitter"]

from .colors import ColourSplitter  # noqa: E402

__all__ += ["ColourSplitter"]
