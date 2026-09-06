"""Configuration loading and validated scheduling inputs."""

from .instance import (
    BLOCK_WEIGHTS,
    LARGE_SECTION,
    MIN_ROOM_FILL,
    OFF_CAMPUS,
    PART_TIMER,
    PAYLOAD_KEYS,
    PLACEHOLDER_PREFIX,
    Instance,
    SectionKey,
    is_placeholder,
    placeholder_for,
)
from .loader import load, loads
from .patterns import Meeting, MeetingPattern

__all__ = [
    "BLOCK_WEIGHTS",
    "LARGE_SECTION",
    "MIN_ROOM_FILL",
    "OFF_CAMPUS",
    "PART_TIMER",
    "PAYLOAD_KEYS",
    "PLACEHOLDER_PREFIX",
    "Instance",
    "Meeting",
    "MeetingPattern",
    "SectionKey",
    "is_placeholder",
    "load",
    "loads",
    "placeholder_for",
]
