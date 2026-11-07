"""Core package: data model and Spine serialization. No third-party imports."""

from .model import Bone, RegionAttachment, Skeleton, Slot
from .serializer import SPINE_VERSION, to_spine_json

__all__ = [
    "Bone",
    "RegionAttachment",
    "Skeleton",
    "Slot",
    "SPINE_VERSION",
    "to_spine_json",
]
