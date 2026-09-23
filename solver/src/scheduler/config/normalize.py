"""Normalize hand-edited pattern configuration and institution policy."""

from __future__ import annotations

import copy
import math
import re
from dataclasses import asdict
from typing import Any, NoReturn

from ..errors import InvalidInstanceError
from .patterns import parse_patterns


def _fail(where: str, message: str) -> NoReturn:
    raise InvalidInstanceError([f"{where}: {message}"])


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        _fail(where, "expected a mapping with named fields")
    return dict(value)


def _names(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        _fail(where, "expected a non-empty list of names")
    return list(value)


def _clock(value: Any, where: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        _fail(where, 'expected a quoted time such as "09:00"')
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _fields(value: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        _fail(where, f"unknown fields: {', '.join(sorted(unknown))}")


def normalize(cfg: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return grouped loader input and JSON-serializable model metadata.

    Only the maintained meeting_patterns YAML schema is accepted.
    """
    cfg = copy.deepcopy(cfg)
    metadata: dict[str, Any] = {}
    if "meeting_patterns" not in cfg:
        _fail("meeting_patterns", "required: provide custom bundles or generate settings")
    conflicting = {"calendar", "timeslots", "overlapping_timeslots", "meeting_times"} & set(cfg)
    if conflicting:
        _fail("config", f"meeting_patterns cannot be mixed with {sorted(conflicting)}")
    preset = cfg.pop("preset", "general")
    if preset not in ("general", "telfer"):
        _fail("preset", "expected general or telfer")
    policy = _mapping(cfg.pop("policy", {}), "policy")
    _fields(
        policy,
        {
            "minimum_room_fill",
            "large_section_threshold",
            "long_meeting_minutes",
            "night_period",
            "allowed_durations",
        },
        "policy",
    )
    fill = policy.get(
        "minimum_room_fill", cfg.get("minimum_room_fill", 0.8 if preset == "telfer" else 0)
    )
    cfg["minimum_room_fill"] = fill
    threshold = policy.get("large_section_threshold", 75 if preset == "telfer" else None)
    if threshold is not None and (type(threshold) is not int or threshold < 0):
        _fail("policy.large_section_threshold", "expected a non-negative integer or null")
    long_minutes = policy.get("long_meeting_minutes", 180)
    if type(long_minutes) is not int or long_minutes <= 0:
        _fail("policy.long_meeting_minutes", "expected a positive integer")
    night = policy.get("night_period", "Night")
    if not isinstance(night, str) or not night:
        _fail("policy.night_period", "expected a non-empty name")
    strict = cfg.pop("strict", False)
    if not isinstance(strict, bool):
        _fail("strict", "expected true or false")
    metadata.update(
        strict=strict,
        large_section_threshold=threshold,
        long_meeting_minutes=long_minutes,
        night_period=night,
        preset=preset,
    )
    if preset == "telfer":
        defaults = _mapping(cfg.get("course_defaults", {}), "course_defaults")
        cfg["course_defaults"] = {"penalise_friday_night": True, **defaults}
    else:
        defaults = _mapping(cfg.get("professor_defaults", {}), "professor_defaults")
        cfg["professor_defaults"] = {"can_teach_night": True, **defaults}

    allowed_durations = policy.get("allowed_durations", [90, 180] if preset == "telfer" else None)
    if allowed_durations is not None and (
        not isinstance(allowed_durations, list)
        or not allowed_durations
        or any(type(v) is not int or v <= 0 for v in allowed_durations)
    ):
        _fail("policy.allowed_durations", "expected positive integer minutes")
    patterns, pools = parse_patterns(cfg.pop("meeting_patterns"))

    if allowed_durations is not None:
        for pattern in patterns.values():
            if any(m.duration_minutes not in allowed_durations for m in pattern.meetings):
                _fail(
                    f"meeting_patterns.{pattern.id}",
                    "duration is not allowed by institution policy",
                )

    semesters = _names(cfg.get("semesters"), "semesters")
    if len(set(semesters)) != len(semesters):
        _fail("semesters", "names must be unique")
    defaults = _mapping(cfg.get("course_defaults", {}), "course_defaults")
    inherited: dict[str, Any] = {
        k: defaults.pop(k)
        for k in ("meeting_patterns", "semester", "time_of_day", "formats")
        if k in defaults
    }
    cfg["course_defaults"] = defaults
    courses = _mapping(cfg.get("courses"), "courses")
    section_patterns = []
    for course, raw_course in courses.items():
        spec = _mapping(raw_course, f"courses.{course}")
        local = {**inherited}
        for name in ("meeting_patterns", "semester", "time_of_day", "formats"):
            if name in spec:
                local[name] = spec.pop(name)
        sections = spec.get("sections")
        if not isinstance(sections, list):
            _fail(f"courses.{course}.sections", "expected a list")
        new_sections = []
        for i, raw_section in enumerate(sections):
            where = f"courses.{course}.sections[{i}]"
            section = _mapping(raw_section, where)
            selection: dict[str, Any] = {**local, **section}
            chosen_pools = _names(
                selection.get("meeting_patterns", list(pools)), f"{where}.meeting_patterns"
            )
            unknown = set(chosen_pools) - set(pools)
            if unknown:
                _fail(where, f"unknown meeting pattern pools: {sorted(unknown)}")
            eligible = {slot for pool in chosen_pools for slot in pools[pool]}
            formats = selection.get("formats")
            if formats is not None:
                if not isinstance(formats, list) or not formats:
                    _fail(f"{where}.formats", "expected a non-empty list of meeting formats")
                structures = set()
                for j, raw in enumerate(formats):
                    fmt = _mapping(raw, f"{where}.formats[{j}]")
                    _fields(fmt, {"meetings", "minutes_each"}, f"{where}.formats[{j}]")
                    count, duration = fmt.get("meetings"), fmt.get("minutes_each")
                    if (
                        type(count) is not int
                        or count <= 0
                        or type(duration) is not int
                        or duration <= 0
                    ):
                        _fail(
                            f"{where}.formats[{j}]",
                            "meetings and minutes_each must be positive integers",
                        )
                    structures.add(tuple([duration] * count))
                eligible = {
                    slot
                    for slot in eligible
                    if tuple(sorted(m.duration_minutes for m in patterns[slot].meetings))
                    in structures
                }
            period = selection.get("time_of_day", "Any")
            if period != "Any":
                eligible = {slot for slot in eligible if patterns[slot].time_of_day == period}
            if not eligible:
                _fail(
                    where, "no candidate bundles match the selected pools, formats and time_of_day"
                )
            section.pop("meeting_patterns", None)
            section.pop("formats", None)
            section["semester"] = selection.get(
                "semester", semesters[0] if len(semesters) == 1 else None
            )
            section["time_of_day"] = period
            if section["semester"] is None:
                _fail(where, "semester is required when there is more than one semester")
            section_patterns.append(
                {
                    "key": [course, str(section.get("id", "")), section["semester"], period],
                    "patterns": sorted(eligible),
                }
            )
            new_sections.append(section)
        spec["sections"] = new_sections
        courses[course] = spec
    cfg["courses"] = courses
    metadata["section_pattern_data"] = section_patterns
    metadata["meeting_pattern_data"] = [asdict(patterns[key]) for key in sorted(patterns)]

    forbidden = []
    preferences: list[dict[str, Any]] = []
    professors = _mapping(cfg.get("professors"), "professors")
    for prof, raw_prof in professors.items():
        spec = _mapping(raw_prof, f"professors.{prof}")
        for field in ("unavailable", "time_preferences"):
            rules = spec.pop(field, [])
            if not isinstance(rules, list):
                _fail(f"professors.{prof}.{field}", "expected a list of day/time windows")
            for i, raw in enumerate(rules):
                where = f"professors.{prof}.{field}[{i}]"
                rule = _mapping(raw, where)
                _fields(
                    rule,
                    {"semester", "days", "start", "end"}
                    | ({"score"} if field == "time_preferences" else set()),
                    where,
                )
                days = _names(rule.get("days"), f"{where}.days")
                if set(days) - {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}:
                    _fail(where, "unknown weekday")
                start = _clock(rule.get("start"), f"{where}.start")
                end = _clock(rule.get("end"), f"{where}.end")
                if end <= start:
                    _fail(where, "end must be after start")
                terms = [rule["semester"]] if "semester" in rule else semesters
                if any(term not in semesters for term in terms):
                    _fail(where, "unknown semester")
                score = rule.get("score", 0)
                if (
                    isinstance(score, bool)
                    or not isinstance(score, (int, float))
                    or not math.isfinite(score)
                ):
                    _fail(where, "score must be a finite number")
                for slot, pattern in patterns.items():
                    if any(
                        m.day in days
                        and m.start_minutes < end
                        and start < m.start_minutes + m.duration_minutes
                        for m in pattern.meetings
                    ):
                        for term in terms:
                            if field == "unavailable":
                                forbidden.append([prof, term, slot])
                            else:
                                preferences.append({"key": [prof, term, slot], "value": score})
        professors[prof] = spec
    cfg["professors"] = professors
    metadata["forbidden_professor_patterns"] = forbidden
    # Multiple preference windows contribute cumulatively to a bundle's score.
    summed: dict[tuple[str, ...], float] = {}
    for row in preferences:
        key = tuple(row["key"])
        summed[key] = summed.get(key, 0) + row["value"]
        if not math.isfinite(summed[key]):
            _fail(f"professors.{key[0]}.time_preferences", "combined score must be finite")
    metadata["professor_pattern_preference"] = [
        {"key": list(key), "value": value} for key, value in sorted(summed.items())
    ]
    periods = sorted({p.time_of_day for p in patterns.values()})
    if any(row["key"][3] == "Any" for row in section_patterns):
        periods.append("Any")
    cfg.pop("semesters")
    cfg["calendar"] = {
        "semesters": semesters,
        "days": sorted({m.day for p in patterns.values() for m in p.meetings}),
        "times_of_day": periods,
        "class_lengths": sorted(
            {str(m.duration_minutes / 60) for p in patterns.values() for m in p.meetings}
        ),
    }
    cfg["timeslots"] = [
        {
            "days": sorted({m.day for m in p.meetings}),
            "length": str(p.meetings[0].duration_minutes / 60),
            "slots": {p.time_of_day: [p.id]},
        }
        for p in patterns.values()
    ]
    cfg["overlapping_timeslots"] = [
        [a.id, b.id]
        for i, a in enumerate(patterns.values())
        for b in list(patterns.values())[i + 1 :]
        if any(
            x.day == y.day
            and x.start_minutes < y.start_minutes + y.duration_minutes
            and y.start_minutes < x.start_minutes + x.duration_minutes
            for x in a.meetings
            for y in b.meetings
        )
    ]
    return cfg, metadata
