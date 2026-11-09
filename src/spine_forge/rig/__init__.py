"""Rig building: read joint marks, describe a skeleton, draw it for review."""

from .markers import (
    Mark,
    annotate,
    detect_marks,
    load_marks,
    merge_close_marks,
    nearest_mark,
    read_marks,
    save_marks,
)
from .overlay import render_panel
from .skeleton import Joint, Skeleton, load_document, load_spec, save_spec
from .constraints import FollowSpec, IkSpec, add_ik_targets, default_constraints, validate

__all__ = [
    "Mark",
    "Joint",
    "Skeleton",
    "FollowSpec",
    "IkSpec",
    "add_ik_targets",
    "annotate",
    "default_constraints",
    "detect_marks",
    "load_document",
    "load_marks",
    "load_spec",
    "merge_close_marks",
    "nearest_mark",
    "read_marks",
    "render_panel",
    "save_marks",
    "save_spec",
    "validate",
]
