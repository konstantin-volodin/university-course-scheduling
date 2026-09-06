"""YAML instance loading and validation."""

from __future__ import annotations

import itertools
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from ..errors import InvalidInstanceError, SchedulerError
from .normalize import normalize

__all__ = ["load", "loads"]

LENGTH_HOURS = {"single": "1.5", "double": "3.0"}


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


def loads(text: str) -> dict[str, Any]:
    """Parse YAML into the flat model payload."""
    yaml = _import_yaml()

    try:
        cfg = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise InvalidInstanceError([f"invalid YAML: {exc}"]) from exc
    if not isinstance(cfg, dict):
        raise InvalidInstanceError(["config must be a mapping of sections"])
    cfg, metadata = normalize(cfg)
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
            "minimum_room_fill",
            "timeslots",
            "overlapping_timeslots",
            "classrooms",
            "professors",
            "courses",
            "course_concurrency",
            "professor_defaults",
            "course_defaults",
            "programs",
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
                dow.extend([sid, day] for day in days)

    overlaps = cfg.get("overlapping_timeslots")
    pairs = (
        [list(p) for p in overlaps]
        if overlaps is not None
        else []
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
                [course, hours_of.get(
                    course_length_pref, LENGTH_HOURS.get(course_length_pref, course_length_pref)
                )]
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
                [prof, hours_of.get(
                    prof_length_pref, LENGTH_HOURS.get(prof_length_pref, prof_length_pref)
                )]
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

    program_requirements: list[list[str]] = []
    programs_cfg = cfg.get("programs") or {}
    if not isinstance(programs_cfg, dict):
        problems.append(f"programs: expected a mapping, got {type(programs_cfg).__name__}")
        programs_cfg = {}
    for raw_program, terms in programs_cfg.items():
        program = as_id(raw_program)
        if not isinstance(terms, dict):
            problems.append(
                f"programs.{program}: expected a semester-to-courses mapping, "
                f"got {type(terms).__name__}"
            )
            continue
        for semester, required in terms.items():
            where = f"programs.{program}.{semester}"
            if not isinstance(required, list) or not all(
                isinstance(item, str) for item in required
            ):
                problems.append(f"{where}: expected a list of course ids")
                continue
            for course in required:
                program_requirements.append([program, str(semester), course])

    if problems:
        raise InvalidInstanceError(problems)

    payload = {
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
        "program_requirements": program_requirements,
    }
    if "minimum_room_fill" in cfg:
        payload["minimum_room_fill"] = cfg["minimum_room_fill"]
    payload.update(metadata)
    return payload


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

    allowed_manifest = {
        "semesters", "files", "professor_defaults", "course_defaults", "programs",
        "minimum_room_fill", "preset", "policy", "strict", "meeting_patterns",
    }
    problems = [
        f"instance.yaml: unknown field {key!r}"
        for key in manifest
        if key not in allowed_manifest
    ]
    files = manifest.get("files")
    required = {"classrooms", "professors", "courses"}
    if not isinstance(files, dict):
        problems.append("instance.yaml.files: expected a mapping")
        files = {}
    if "meeting_patterns" not in files and "meeting_patterns" not in manifest:
        problems.append("instance.yaml.files: missing meeting_patterns")
    for key in sorted(required - set(files)):
        problems.append(f"instance.yaml.files: missing {key!r}")
    optional_files = {"course_concurrency", "programs", "meeting_patterns"}
    for key in sorted(set(files) - required - optional_files):
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
        mapping_kind = key in {
            "classrooms", "professors", "courses", "programs", "meeting_patterns",
        }
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
        "classrooms": fragments.get("classrooms"),
        "professors": fragments.get("professors"),
        "courses": fragments.get("courses"),
    }
    if "meeting_patterns" in fragments:
        combined["meeting_patterns"] = fragments["meeting_patterns"]
    for key in ("preset", "policy", "strict", "meeting_patterns"):
        if key in manifest:
            combined[key] = manifest[key]
    if "course_concurrency" in fragments:
        combined["course_concurrency"] = fragments["course_concurrency"]
    if "programs" in fragments:
        combined["programs"] = fragments["programs"]
    for optional_key in ("professor_defaults", "course_defaults", "programs", "minimum_room_fill"):
        if optional_key in manifest:
            combined[optional_key] = manifest[optional_key]
    return loads(yaml.safe_dump(combined, sort_keys=False))
