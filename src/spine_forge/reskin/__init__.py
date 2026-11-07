"""Reskin: replace one attachment's artwork and keep the rig consistent.

The pipeline is deliberately split into three pure steps so each can be tested
and reasoned about alone:

    align.py       decide the scale factor and where the new art sits
    propagate.py   walk the bone/attachment tree and rewrite dependent values
    replace.py     compose the new atlas page and patch the rig document

Nothing here touches HTTP, files on disk beyond its explicit inputs, or the
browser. ``replace.apply`` is the only entry point a server needs.
"""

from .align import AlignResult, compute_scale
from .propagate import PropagationReport, propagate_scale
from .replace import ReskinResult, apply_reskin

__all__ = [
    "AlignResult",
    "compute_scale",
    "PropagationReport",
    "propagate_scale",
    "ReskinResult",
    "apply_reskin",
]
