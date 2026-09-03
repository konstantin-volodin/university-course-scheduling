"""YAML instance loading and validation."""

from __future__ import annotations

import itertools
import re
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from ..errors import InvalidInstanceError, SchedulerError

__all__ = ["load", "loads"]

LENGTH_HOURS = {"single": "1.5", "double": "3.0"}
MINUTES_TO_LENGTH = {90: "single", 180: "double"}


def _check_unknown_fields(
    where: str, value: dict[Any, Any], allowed: set[str], problems: list[str]
) -> None:
    """Add unknown fields and likely corrections to ``problems``."""
    for raw_key in value:
        key = str(raw_key)
        if key in allowed:
            continue
        suggestion = get_close_matches(key, allowed, n=1)
        hint = f"; did you mean {suggestion[0]!r}?" if suggestion else ""
        problems.append(f"{where}: unknown field {key!r}{hint}")


def _import_yaml() -> Any:
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise SchedulerError("reading YAML config needs PyYAML: pip install pyyaml") from exc
    return yaml


def _derive_overlaps(
    slots: list[str], days_of: dict[str, set[str]], tod_of: dict[str, str]
) -> set[tuple[str, str]]:
    return {
        tuple(sorted((a, b)))  # type: ignore[misc]
        for a, b in itertools.combinations(slots, 2)
        if days_of[a] & days_of[b] and tod_of[a] == tod_of[b]
    }


def _expand_meeting_times(cfg: dict[str, Any]) -> dict[str, Any]:
    """Convert meeting times to the internal grouped shape."""
    problems: list[str] = []
    _check_unknown_fields(
        "config",
        cfg,
        {
            "semesters",
            "meeting_times",
            "classrooms",
            "professors",
            "courses",
            "course_concurrency",
            "professor_defaults",
            "course_defaults",
        },
        problems,
    )
    semesters = cfg.get("semesters")
    meetings = cfg.get("meeting_times")
    if not isinstance(semesters, list) or not semesters:
        problems.append("semesters: expected a non-empty list")
        semesters = []
    if not isinstance(meetings, list) or not meetings:
        problems.append("meeting_times: expected a non-empty list")
        meetings = []

    timeslots: list[dict[str, Any]] = []
    intervals: list[tuple[str, str, int, int]] = []
    days_seen: list[str] = []
    periods_seen: list[str] = []
    lengths_seen: list[str] = []
    ids_seen: set[str] = set()

    allowed = {"id", "days", "duration_minutes", "time_of_day"}
    for index, meeting in enumerate(meetings):
        where = f"meeting_times[{index}]"
        if not isinstance(meeting, dict):
            problems.append(f"{where}: expected a mapping")
            continue
        _check_unknown_fields(where, meeting, allowed, problems)
        for key in allowed:
            if key not in meeting:
                problems.append(f"{where}: missing {key!r}")
        if not allowed <= set(meeting):
            continue

        slot_id = str(meeting["id"])
        if slot_id in ids_seen:
            problems.append(f"{where}.id: duplicate meeting time id {slot_id!r}")
        ids_seen.add(slot_id)

        schedule = meeting["days"]
        if (
            not isinstance(schedule, dict)
            or not schedule
            or not all(isinstance(day, str) for day in schedule)
        ):
            problems.append(
                f"{where}.days: expected day-to-start mappings such as "
                "{Mon: '09:00', Wed: '09:00'}"
            )
            continue
        period = meeting["time_of_day"]
        if not isinstance(period, str) or not period:
            problems.append(f"{where}.time_of_day: expected a name")
            continue

        raw_duration = meeting["duration_minutes"]
        if isinstance(raw_duration, bool) or raw_duration not in MINUTES_TO_LENGTH:
            problems.append(
                f"{where}.duration_minutes: expected 90 or 180, got {raw_duration!r}"
            )
            continue
        duration = int(raw_duration)
        starts: dict[str, int] = {}
        for day, raw_start in schedule.items():
            match = (
                re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", raw_start)
                if isinstance(raw_start, str)
                else None
            )
            if match is None:
                problems.append(
                    f"{where}.days.{day}: expected a quoted 24-hour time such as '09:00'"
                )
                continue
            start = int(match.group(1)) * 60 + int(match.group(2))
            if start + duration > 24 * 60:
                problems.append(f"{where}.days.{day}: meeting cannot continue past midnight")
                continue
            starts[day] = start
        if len(starts) != len(schedule):
            continue

        length = MINUTES_TO_LENGTH[duration]
        days = list(schedule)
        for day in days:
            if day not in days_seen:
                days_seen.append(day)
        if period not in periods_seen:
            periods_seen.append(period)
        if length not in lengths_seen:
            lengths_seen.append(length)
        timeslots.append(
            {"days": days, "length": length, "slots": {period: [slot_id]}}
        )
        intervals.extend((slot_id, day, start, start + duration) for day, start in starts.items())

    overlap_pairs = {
        tuple(sorted((first_id, second_id)))
        for (first_id, first_day, first_start, first_end),
        (second_id, second_day, second_start, second_end) in itertools.combinations(intervals, 2)
        if first_id != second_id
        and first_day == second_day
        and max(first_start, second_start) < min(first_end, second_end)
    }
    overlaps = [list(pair) for pair in sorted(overlap_pairs)]
    if problems:
        raise InvalidInstanceError(problems)

    expanded = {
        "calendar": {
            "semesters": semesters,
            "days": days_seen,
            "times_of_day": periods_seen,
            "class_lengths": lengths_seen,
        },
        "timeslots": timeslots,
        "overlapping_timeslots": overlaps,
        "classrooms": cfg.get("classrooms"),
        "professors": cfg.get("professors"),
        "courses": cfg.get("courses"),
    }
    if "course_concurrency" in cfg:
        expanded["course_concurrency"] = cfg["course_concurrency"]
    for defaults_key in ("professor_defaults", "course_defaults"):
        if defaults_key in cfg:
            expanded[defaults_key] = cfg[defaults_key]
    return expanded


def loads(text: str) -> dict[str, Any]:
    """Parse YAML into the flat model payload."""
    yaml = _import_yaml()

    try:
        cfg = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise InvalidInstanceError([f"invalid YAML: {exc}"]) from exc
    if not isinstance(cfg, dict):
        raise InvalidInstanceError(["config must be a mapping of sections"])
    if "meeting_times" in cfg:
        cfg = _expand_meeting_times(cfg)

    missing = [k for k in ("calendar", "timeslots", "classrooms", "professors", "courses")
               if k not in cfg]
    if missing:
        raise InvalidInstanceError([f"missing required section: {k}" for k in missing])

    if "preferences" in cfg:
        raise InvalidInstanceError([
            "top-level 'preferences:' is the old layout -- move each professor's "
            "entries under that professor as 'availability:' and 'course_ranks:'"
        ])

    problems: list[str] = []
    _check_unknown_fields(
        "config",
        cfg,
        {
            "calendar",
            "timeslots",
            "overlapping_timeslots",
            "classrooms",
            "professors",
            "courses",
            "course_concurrency",
            "professor_defaults",
            "course_defaults",
        },
        problems,
    )

    def as_id(value: Any) -> str:
        return str(value)

    def flag_defaults(name: str, allowed: set[str]) -> dict[str, Any]:
        """Read an optional ``*_defaults`` block of per-field defaults."""
        raw = cfg.get(name)
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            problems.append(f"{name}: expected a mapping, got {type(raw).__name__}")
            return {}
        _check_unknown_fields(name, raw, allowed, problems)
        return {str(key): value for key, value in raw.items() if str(key) in allowed}

    professor_defaults = flag_defaults(
        "professor_defaults",
        {
            "can_teach_night",
            "can_teach_off_campus",
            "prefers_packed_days",
            "preferred_class_length",
        },
    )
    for option in ("can_teach_night", "can_teach_off_campus", "prefers_packed_days"):
        if option in professor_defaults and not isinstance(professor_defaults[option], bool):
            problems.append(f"professor_defaults.{option}: expected true or false")
    course_defaults = flag_defaults(
        "course_defaults", {"penalise_friday_night", "preferred_class_length"}
    )
    if "penalise_friday_night" in course_defaults and not isinstance(
        course_defaults["penalise_friday_night"], bool
    ):
        problems.append("course_defaults.penalise_friday_night: expected true or false")
    for block_name, block in (
        ("professor_defaults", professor_defaults),
        ("course_defaults", course_defaults),
    ):
        if "preferred_class_length" in block and not isinstance(
            block["preferred_class_length"], str
        ):
            problems.append(f"{block_name}.preferred_class_length: expected a class-length name")

    cal = cfg["calendar"]
    if not isinstance(cal, dict):
        problems.append(f"calendar: expected a mapping, got {type(cal).__name__}")
        cal = {}
    else:
        _check_unknown_fields(
            "calendar",
            cal,
            {"semesters", "days", "times_of_day", "class_lengths"},
            problems,
        )
        for name in ("semesters", "days", "times_of_day", "class_lengths"):
            if name not in cal:
                problems.append(f"calendar: missing '{name}'")

    class_lengths = cal.get("class_lengths") or []
    if not isinstance(class_lengths, list):
        problems.append(
            f"calendar.class_lengths: expected a list, got {type(class_lengths).__name__}"
        )
        class_lengths = []
    hours_of = {name: LENGTH_HOURS.get(name, name) for name in class_lengths}

    slots: list[str] = []
    dow: list[list[str]] = []
    tod: list[list[str]] = []
    blk: list[list[Any]] = []  # slot id + block length, which YAML may give as a number
    days_of: dict[str, set[str]] = {}
    tod_of: dict[str, str] = {}
    timeslot_patterns = cfg["timeslots"]
    if not isinstance(timeslot_patterns, list):
        problems.append(f"timeslots: expected a list, got {type(timeslot_patterns).__name__}")
        timeslot_patterns = []
    for index, pattern in enumerate(timeslot_patterns):
        if not isinstance(pattern, dict):
            problems.append(f"timeslots[{index}]: expected a mapping, got {type(pattern).__name__}")
            continue
        _check_unknown_fields(
            f"timeslots[{index}]", pattern, {"days", "length", "slots"}, problems
        )
        for name in ("days", "length", "slots"):
            if name not in pattern:
                problems.append(f"timeslots[{index}]: missing '{name}'")
        days = pattern.get("days")
        slot_map = pattern.get("slots")
        if not isinstance(days, list):
            if "days" in pattern:
                problems.append(
                    f"timeslots[{index}].days: expected a list, got {type(days).__name__}"
                )
            continue
        if not isinstance(slot_map, dict):
            if "slots" in pattern:
                problems.append(
                    f"timeslots[{index}].slots: expected a mapping, got {type(slot_map).__name__}"
                )
            continue
        hours = hours_of.get(pattern.get("length"), pattern.get("length"))
        for time_name, ids in slot_map.items():
            for sid in ids:
                slots.append(sid)
                tod.append([sid, time_name])
                blk.append([sid, hours])
                days_of[sid] = set(days)
                tod_of[sid] = time_name
                dow.extend([sid, day] for day in days)

    overlaps = cfg.get("overlapping_timeslots")
    pairs = (
        [list(p) for p in overlaps]
        if overlaps is not None
        else [list(p) for p in sorted(_derive_overlaps(slots, days_of, tod_of))]
    )

    classrooms = cfg["classrooms"]
    if not isinstance(classrooms, dict):
        problems.append(f"classrooms: expected a mapping, got {type(classrooms).__name__}")
        classrooms = {}

    professors_cfg = cfg["professors"]
    courses_cfg = cfg["courses"]
    if not isinstance(professors_cfg, dict):
        problems.append(f"professors: expected a mapping, got {type(professors_cfg).__name__}")
        professors_cfg = {}
    if not isinstance(courses_cfg, dict):
        problems.append(f"courses: expected a mapping, got {type(courses_cfg).__name__}")
        courses_cfg = {}

    professors = [as_id(p) for p in professors_cfg]
    courses = [as_id(c) for c in courses_cfg]

    sections: list[str] = []
    section_subset: list[list[str]] = []
    attendance: list[dict[str, Any]] = []
    friday: list[str] = []
    course_length: list[list[str]] = []
    for raw_course, spec in courses_cfg.items():
        course = as_id(raw_course)
        if spec is None:
            spec = {}
        elif not isinstance(spec, dict):
            problems.append(f"courses.{course}: expected a mapping, got {type(spec).__name__}")
            continue
        _check_unknown_fields(
            f"courses.{course}",
            spec,
            {"preferred_class_length", "penalise_friday_night", "sections"},
            problems,
        )
        if "sections" not in spec:
            problems.append(f"courses.{course}: missing 'sections'")
        penalty = spec.get(
            "penalise_friday_night", course_defaults.get("penalise_friday_night", False)
        )
        if not isinstance(penalty, bool):
            problems.append(f"courses.{course}.penalise_friday_night: expected true or false")
        if penalty:
            friday.append(course)
        course_length_pref = spec.get(
            "preferred_class_length", course_defaults.get("preferred_class_length")
        )
        if course_length_pref is not None:
            course_length.append(
                [course, hours_of.get(course_length_pref, course_length_pref)]
            )
        raw_sections = spec.get("sections") or []
        if not isinstance(raw_sections, list):
            problems.append(f"courses.{course}.sections: expected a list")
            raw_sections = []
        for index, sec in enumerate(raw_sections):
            if not isinstance(sec, dict):
                problems.append(
                    f"courses.{course}.sections[{index}]: expected a mapping, "
                    f"got {type(sec).__name__}"
                )
                continue
            _check_unknown_fields(
                f"courses.{course}.sections[{index}]",
                sec,
                {"id", "semester", "time_of_day", "students"},
                problems,
            )
            for name in ("id", "semester", "time_of_day", "students"):
                if name not in sec:
                    problems.append(f"courses.{course}.sections[{index}]: missing '{name}'")
            if not all(name in sec for name in ("id", "semester", "time_of_day", "students")):
                continue
            key = [course, str(sec["id"]), sec["semester"], sec["time_of_day"]]
            sections.append(str(sec["id"]))
            section_subset.append(key)
            attendance.append({"key": key, "value": sec["students"]})

    qualification: list[list[str]] = []
    teaching: list[dict[str, int]] = []
    night: list[list[Any]] = []
    offc: list[list[Any]] = []
    pack: list[list[Any]] = []
    prof_length: list[list[str]] = []
    course_pref: list[dict[str, Any]] = []
    time_pref: list[dict[str, Any]] = []
    for raw_prof, spec in professors_cfg.items():
        prof = as_id(raw_prof)
        if spec is None:
            spec = {}
        elif not isinstance(spec, dict):
            problems.append(f"professors.{prof}: expected a mapping, got {type(spec).__name__}")
            continue
        _check_unknown_fields(
            f"professors.{prof}",
            spec,
            {
                "teaching_load",
                "can_teach_night",
                "can_teach_off_campus",
                "prefers_packed_days",
                "preferred_class_length",
                "qualified_for",
                "availability",
                "course_ranks",
            },
            problems,
        )
        if "teaching_load" not in spec:
            problems.append(f"professors.{prof}: missing 'teaching_load'")
        teaching_load = spec.get("teaching_load", 0)
        if (
            isinstance(teaching_load, bool)
            or not isinstance(teaching_load, int)
            or teaching_load < 0
        ):
            problems.append(f"professors.{prof}.teaching_load: expected a non-negative integer")
        teaching.append({prof: teaching_load})
        for option in (
            "can_teach_night",
            "can_teach_off_campus",
            "prefers_packed_days",
        ):
            if option in spec and not isinstance(spec[option], bool):
                problems.append(f"professors.{prof}.{option}: expected true or false")
        night.append([prof, bool(spec.get("can_teach_night",
                                          professor_defaults.get("can_teach_night", False)))])
        offc.append([prof, bool(spec.get("can_teach_off_campus",
                                         professor_defaults.get("can_teach_off_campus", False)))])
        pack.append([prof, int(bool(spec.get("prefers_packed_days",
                                             professor_defaults.get("prefers_packed_days",
                                                                    False))))])
        prof_length_pref = spec.get(
            "preferred_class_length", professor_defaults.get("preferred_class_length")
        )
        if prof_length_pref is not None:
            prof_length.append(
                [prof, hours_of.get(prof_length_pref, prof_length_pref)]
            )
        qualified = spec.get("qualified_for", "all")
        if qualified != "all" and not isinstance(qualified, list):
            problems.append(
                f"professors.{prof}.qualified_for: expected 'all' or a list of course ids"
            )
            qualified = []
        for course in courses if qualified == "all" else qualified:
            qualification.append([prof, as_id(course)])
        availability = spec.get("availability") or {}
        if not isinstance(availability, dict):
            problems.append(f"professors.{prof}.availability: expected a mapping")
            availability = {}
        for semester, times in availability.items():
            if not isinstance(times, dict):
                problems.append(
                    f"professors.{prof}.availability.{semester}: expected a mapping"
                )
                continue
            for time_name, value in (times or {}).items():
                time_pref.append({"key": [prof, str(semester), str(time_name)], "value": value})
        ranks = spec.get("course_ranks") or {}
        if not isinstance(ranks, dict):
            problems.append(f"professors.{prof}.course_ranks: expected a mapping")
            ranks = {}
        for course, value in ranks.items():
            course_pref.append({"key": [prof, as_id(course)], "value": value})

    together: list[list[str]] = []
    apart: list[list[str]] = []
    for index, rule in enumerate(cfg.get("course_concurrency") or []):
        if not isinstance(rule, dict):
            problems.append(
                f"course_concurrency[{index}]: expected a mapping, got {type(rule).__name__}"
            )
            continue
        _check_unknown_fields(
            f"course_concurrency[{index}]",
            rule,
            {"courses", "semester", "must_run"},
            problems,
        )
        if "courses" not in rule:
            problems.append(f"course_concurrency[{index}]: missing 'courses'")
        if "must_run" not in rule:
            problems.append(f"course_concurrency[{index}]: missing 'must_run'")
        if "courses" not in rule or "must_run" not in rule:
            continue
        rule_courses = rule["courses"]
        if not isinstance(rule_courses, list) or len(rule_courses) < 2:
            problems.append(f"course_concurrency[{index}].courses: expected at least two courses")
            continue
        kind = rule["must_run"]
        if kind not in {"together", "apart"}:
            problems.append(
                f"course_concurrency[{index}].must_run: expected 'together' or 'apart'"
            )
            continue
        if kind == "together" and len(rule_courses) != 2:
            problems.append(
                f"course_concurrency[{index}].courses: 'together' expects exactly two courses"
            )
            continue
        # A missing semester applies to every semester; more than two courses
        # under 'apart' keeps every pair apart.
        raw_semesters = rule.get("semester")
        if raw_semesters is None:
            semesters = list(cal.get("semesters") or [])
        elif isinstance(raw_semesters, str):
            semesters = [raw_semesters]
        elif isinstance(raw_semesters, list) and all(
            isinstance(item, str) for item in raw_semesters
        ):
            semesters = list(raw_semesters)
        else:
            problems.append(
                f"course_concurrency[{index}].semester: expected a name or a list of names"
            )
            continue
        target = together if kind == "together" else apart
        for first, second in itertools.combinations(rule_courses, 2):
            for semester in semesters:
                target.append([as_id(first), as_id(second), semester])

    if problems:
        raise InvalidInstanceError(problems)

    return {
        "professor_set": professors,
        "course_set": courses,
        "section_set": sections,
        "classroom_set": [as_id(r) for r in classrooms],
        "semester_set": list(cal.get("semesters") or []),
        "timeslot_set": slots,
        "time_of_day_set": list(cal.get("times_of_day") or []),
        "day_of_week_set": list(cal.get("days") or []),
        "block_type_set": [hours_of[n] for n in class_lengths],
        "section_subset": section_subset,
        "timeslot_tod_subset": tod,
        "timeslot_dow_subset": dow,
        "timeslot_block_subset": blk,
        "timeslot_concurrency": pairs,
        "professor_teaching": teaching,
        "professor_qualification": qualification,
        "professor_can_teach_night": night,
        "professor_can_teach_out_DMS": offc,
        "professor_course_pref": course_pref,
        "professor_time_pref": time_pref,
        "professor_block_pref": prof_length,
        "professor_pack_day_pref": pack,
        "classroom_cap": [{as_id(r): c} for r, c in classrooms.items()],
        "section_attendance": attendance,
        "course_concurrency_t": together,
        "course_concurrency_nt": apart,
        "course_friday_penalty": friday,
        "course_block_pref": course_length,
    }


def load(path: Any) -> dict[str, Any]:
    """Read a single YAML file or a split-instance directory into a payload."""
    source = Path(path)
    if source.is_dir():
        source = source / "instance.yaml"
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise SchedulerError(f"{source}: {exc.strerror}") from exc

    yaml = _import_yaml()
    try:
        manifest = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise InvalidInstanceError([f"{source}: invalid YAML: {exc}"]) from exc
    if not isinstance(manifest, dict) or "files" not in manifest:
        return loads(text)

    allowed_manifest = {"semesters", "files", "professor_defaults", "course_defaults"}
    problems = [
        f"instance.yaml: unknown field {key!r}"
        for key in manifest
        if key not in allowed_manifest
    ]
    files = manifest.get("files")
    required = {"meeting_times", "classrooms", "professors", "courses"}
    if not isinstance(files, dict):
        problems.append("instance.yaml.files: expected a mapping")
        files = {}
    for key in sorted(required - set(files)):
        problems.append(f"instance.yaml.files: missing {key!r}")
    for key in sorted(set(files) - required - {"course_concurrency"}):
        problems.append(f"instance.yaml.files: unknown entry {key!r}")
    if problems:
        raise InvalidInstanceError(problems)

    fragments: dict[str, Any] = {}
    for key, relative in files.items():
        paths = [relative] if isinstance(relative, str) else relative
        if (
            not isinstance(paths, list)
            or not paths
            or not all(isinstance(item, str) for item in paths)
        ):
            problems.append(
                f"instance.yaml.files.{key}: expected a file path or non-empty list of paths"
            )
            continue
        mapping_kind = key in {"classrooms", "professors", "courses"}
        merged: Any = {} if mapping_kind else []
        for relative_path in paths:
            fragment_path = source.parent / relative_path
            try:
                fragment_text = fragment_path.read_text(encoding="utf-8")
                fragment = yaml.safe_load(fragment_text)
            except OSError as exc:
                problems.append(f"{fragment_path}: {exc.strerror}")
                continue
            except yaml.YAMLError as exc:
                problems.append(f"{fragment_path}: invalid YAML: {exc}")
                continue
            expected_type = dict if mapping_kind else list
            if not isinstance(fragment, expected_type):
                problems.append(
                    f"{fragment_path}: expected a YAML "
                    f"{'mapping' if mapping_kind else 'list'}"
                )
                continue
            if mapping_kind:
                duplicates = sorted(str(item) for item in set(merged) & set(fragment))
                for duplicate in duplicates:
                    problems.append(f"{fragment_path}: duplicate id {duplicate!r}")
                merged.update(fragment)
            else:
                merged.extend(fragment)
        fragments[key] = merged
    if problems:
        raise InvalidInstanceError(problems)

    combined = {
        "semesters": manifest.get("semesters"),
        "meeting_times": fragments.get("meeting_times"),
        "classrooms": fragments.get("classrooms"),
        "professors": fragments.get("professors"),
        "courses": fragments.get("courses"),
    }
    if "course_concurrency" in fragments:
        combined["course_concurrency"] = fragments["course_concurrency"]
    for defaults_key in ("professor_defaults", "course_defaults"):
        if defaults_key in manifest:
            combined[defaults_key] = manifest[defaults_key]
    return loads(yaml.safe_dump(combined, sort_keys=False))
