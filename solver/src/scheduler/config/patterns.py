"""Immutable weekly bundles and deterministic candidate generation."""

from __future__ import annotations

import hashlib
import itertools
import re
from dataclasses import dataclass
from typing import Any, NoReturn

from ..errors import InvalidInstanceError

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True, order=True)
class Meeting:
    day: str
    start_minutes: int
    duration_minutes: int


@dataclass(frozen=True)
class MeetingPattern:
    id: str
    meetings: tuple[Meeting, ...]
    time_of_day: str = "Day"


def overlaps(left: MeetingPattern, right: MeetingPattern) -> bool:
    """Touching endpoints do not overlap."""
    return any(
        a.day == b.day
        and a.start_minutes < b.start_minutes + b.duration_minutes
        and b.start_minutes < a.start_minutes + a.duration_minutes
        for a in left.meetings
        for b in right.meetings
    )


def _fail(path: str, message: str) -> NoReturn:
    raise InvalidInstanceError([f"{path}: {message}"])


def _mapping(raw: Any, path: str, allowed: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        _fail(path, "must be a mapping with text keys")
    if allowed is not None and (extra := set(raw) - allowed):
        _fail(path, f"unknown fields: {', '.join(sorted(extra))}")
    return raw


def _integer(raw: Any, path: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        _fail(path, "must be a positive integer")
    return raw


def _clock(raw: Any, path: str, *, endpoint: bool = False) -> int:
    if endpoint and raw == "24:00":
        return 1440
    if not isinstance(raw, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw):
        _fail(path, 'must be a quoted clock time such as "08:30"')
    hour, minute = raw.split(":")
    return int(hour) * 60 + int(minute)


def _days(raw: Any, path: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        _fail(path, "must be a nonempty list of weekdays")
    if any(not isinstance(day, str) or day not in DAYS for day in raw):
        _fail(path, f"weekdays must be one of {', '.join(DAYS)}")
    if len(set(raw)) != len(raw):
        _fail(path, "weekdays must be distinct")
    return tuple(raw)


def _starts(raw: Any, path: str) -> list[int]:
    if isinstance(raw, list):
        if not raw:
            _fail(path, "must contain at least one start time")
        return sorted({_clock(value, path) for value in raw})
    window = _mapping(raw, path, {"start", "end", "every_minutes"})
    start = _clock(window.get("start"), f"{path}.start")
    end = _clock(window.get("end"), f"{path}.end")
    step = _integer(window.get("every_minutes"), f"{path}.every_minutes")
    if end < start:
        _fail(path, "end must be at or after start")
    return list(range(start, end + 1, step))


def _custom(raw: Any, path: str) -> tuple[Meeting, ...]:
    if not isinstance(raw, list) or not raw:
        _fail(path, "must be a nonempty list of meetings")
    meetings = []
    for i, value in enumerate(raw):
        p = f"{path}[{i}]"
        item = _mapping(value, p, {"day", "start", "minutes"})
        day = _days([item.get("day")], f"{p}.day")[0]
        start = _clock(item.get("start"), f"{p}.start")
        duration = _integer(item.get("minutes"), f"{p}.minutes")
        if start + duration > 1440:
            _fail(p, "meeting must finish within its day")
        meetings.append(Meeting(day, start, duration))
    if len({meeting.day for meeting in meetings}) != len(meetings):
        _fail(path, "meeting weekdays must be distinct")
    return tuple(sorted(meetings))


def _generate(raw: Any, path: str) -> list[tuple[Meeting, ...]]:
    config = _mapping(raw, path, {"formats", "start_times", "finish_by", "same_start"})
    starts = _starts(config.get("start_times"), f"{path}.start_times")
    finish = _clock(config.get("finish_by", "24:00"), f"{path}.finish_by", endpoint=True)
    same = config.get("same_start", False)
    if not isinstance(same, bool):
        _fail(f"{path}.same_start", "must be a boolean")
    formats = config.get("formats")
    if not isinstance(formats, list) or not formats:
        _fail(f"{path}.formats", "must be a nonempty list")
    result = []
    for i, raw_format in enumerate(formats):
        p = f"{path}.formats[{i}]"
        item = _mapping(raw_format, p, {"meetings", "minutes_each", "day_combinations", "days"})
        count = _integer(item.get("meetings"), f"{p}.meetings")
        duration = _integer(item.get("minutes_each"), f"{p}.minutes_each")
        combinations: list[tuple[str, ...]]
        if "days" in item:
            if count != 1 or "day_combinations" in item:
                _fail(p, "days requires meetings: 1 and cannot accompany day_combinations")
            combinations = [(day,) for day in _days(item["days"], f"{p}.days")]
        else:
            raw_combinations = item.get("day_combinations")
            if not isinstance(raw_combinations, list) or not raw_combinations:
                _fail(f"{p}.day_combinations", "must be a nonempty list")
            combinations = [_days(value, f"{p}.day_combinations") for value in raw_combinations]
        valid_starts = [start for start in starts if start + duration <= finish]
        for days in combinations:
            if len(days) != count:
                _fail(p, "each day combination must match the number of meetings")
            choices = (
                ((start,) * count for start in valid_starts)
                if same
                else itertools.product(valid_starts, repeat=count)
            )
            for times in choices:
                result.append(
                    tuple(
                        sorted(
                            Meeting(day, start, duration)
                            for day, start in zip(days, times, strict=True)
                        )
                    )
                )
    if not result:
        _fail(path, "generation produced no bundles; check start times and finish_by")
    return result


def parse_patterns(raw: Any) -> tuple[dict[str, MeetingPattern], dict[str, tuple[str, ...]]]:
    """Return patterns and pool IDs; equivalent bundles share a canonical ID.

    An explicit ID takes precedence; multiple equivalent explicit IDs use the
    alphabetically first. Categories are significant when deduplicating.
    """
    pools_raw = _mapping(raw, "meeting_patterns")
    if not pools_raw:
        _fail("meeting_patterns", "must contain at least one pool")
    candidates: list[tuple[str, tuple[Meeting, ...], str]] = []
    explicit: dict[str, tuple[tuple[Meeting, ...], str]] = {}
    for name, value in sorted(pools_raw.items()):
        path = f"meeting_patterns.{name}"
        pool = _mapping(value, path, {"generate", "custom", "time_of_day"})
        tod = pool.get("time_of_day", "Day")
        if not isinstance(tod, str) or not tod.strip():
            _fail(f"{path}.time_of_day", "must be nonempty text")
        if tod == "Any":
            _fail(f"{path}.time_of_day", "Any is reserved for section eligibility")
        if "custom" not in pool and "generate" not in pool:
            _fail(path, "requires custom or generate")
        for identifier, value in sorted(_mapping(pool.get("custom", {}), path).items()):
            if not identifier.strip():
                _fail(path, "custom bundle IDs must be nonempty")
            meetings = _custom(value, f"{path}.custom.{identifier}")
            key = (meetings, tod)
            if identifier in explicit and explicit[identifier] != key:
                _fail(path, f"custom bundle ID {identifier!r} describes different bundles")
            explicit[identifier] = key
            candidates.append((name, meetings, tod))
        if "generate" in pool:
            candidates.extend(
                (name, meetings, tod)
                for meetings in _generate(pool["generate"], f"{path}.generate")
            )
    canonical = {key: identifier for identifier, key in sorted(explicit.items(), reverse=True)}
    patterns: dict[str, MeetingPattern] = {}
    memberships: dict[str, set[str]] = {name: set() for name in pools_raw}
    for name, meetings, tod in candidates:
        key = (meetings, tod)
        canonical_id = canonical.get(key)
        if canonical_id is None:
            digest = hashlib.sha256(repr(key).encode()).hexdigest()[:16]
            identifier = f"generated-{digest}"
            if identifier in explicit and explicit[identifier] != key:
                _fail("meeting_patterns", f"ID collision: {identifier}")
            canonical[key] = identifier
        else:
            identifier = canonical_id
        patterns[identifier] = MeetingPattern(identifier, meetings, tod)
        memberships[name].add(identifier)
    for name, members in memberships.items():
        if not members:
            _fail(f"meeting_patterns.{name}", "pool contains no bundles")
    return dict(sorted(patterns.items())), {
        name: tuple(sorted(members)) for name, members in sorted(memberships.items())
    }
