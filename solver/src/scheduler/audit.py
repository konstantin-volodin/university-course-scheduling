"""Independently audit exported assignments against hard scheduling rules.

This checks the declared instance directly, without constructing model rows. It
does not certify objective values, optimality, soft course concurrency, teaching
overload penalties, or other preference scores. Null fallback assignments remain
legal subject to the same qualifications and load rules as scheduled sections.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations

from .config import LARGE_SECTION, Instance, SectionKey
from .solve import Result

__all__ = ["AuditIssue", "audit_result"]


@dataclass(frozen=True, slots=True)
class AuditIssue:
    """A hard-rule failure with zero-based indices into result.assignments."""

    code: str
    message: str
    assignment_indices: tuple[int, ...] = ()


def audit_result(instance: Instance, result: Result) -> list[AuditIssue]:
    """Return deterministic hard-rule findings; an empty list means checks passed.

    Program conflicts follow the current formulation: for programs requiring at
    least two distinct courses in a semester, *all sections* of those courses
    compete for the same conflict period, including sections of the same course.
    No instructor or room occupancy is attributed to unscheduled assignments.
    """
    issues: list[AuditIssue] = []
    sections: Counter[SectionKey] = Counter()
    loads: Counter[str] = Counter()
    real_professors = instance.real_professors
    real_rooms = instance.real_classrooms
    real_slots = instance.real_timeslots

    def issue(code: str, message: str, *indices: int) -> None:
        issues.append(AuditIssue(code, message, indices))

    for index, assignment in enumerate(result.assignments):
        key = (
            assignment.course_id,
            str(assignment.section_id),
            assignment.semester_id,
            assignment.time_of_day_id,
        )
        sections[key] += 1
        professor = assignment.professor_id
        slot = assignment.timeslot_id
        room = assignment.classroom_id
        if key not in instance.section_keys:
            issue(
                "unknown_section", f"Undeclared course/section/semester/time-of-day: {key!r}", index
            )
        if not math.isfinite(assignment.solution_value) or not math.isclose(
            assignment.solution_value, 1.0, rel_tol=0, abs_tol=1e-6
        ):
            issue("assignment_value", "An exported assignment must have solution_value 1.", index)
        if professor is not None:
            if professor not in real_professors:
                issue("unknown_professor", f"Unknown named professor {professor!r}.", index)
            else:
                loads[professor] += 1
                if (professor, assignment.course_id) not in instance.qualifications:
                    issue(
                        "qualification",
                        f"{professor!r} is not qualified for {assignment.course_id!r}.",
                        index,
                    )
                if (
                    assignment.time_of_day_id == "Night"
                    and professor not in instance.can_teach_night
                ):
                    issue("night_permission", f"{professor!r} cannot teach at night.", index)
                if (
                    slot is not None
                    and room is None
                    and professor not in instance.can_teach_off_campus
                ):
                    issue("off_campus_permission", f"{professor!r} cannot teach off campus.", index)
        if slot is not None:
            if slot not in real_slots:
                issue("unknown_timeslot", f"Unknown real meeting slot {slot!r}.", index)
            elif (slot, assignment.time_of_day_id) not in instance.timeslot_time_of_day:
                issue(
                    "timeslot_period",
                    f"Slot {slot!r} does not match {assignment.time_of_day_id!r}.",
                    index,
                )
            if (
                key in instance.attendance
                and instance.attendance[key] > LARGE_SECTION
                and (slot, "3.0") in instance.timeslot_block
                and (slot, "Night") not in instance.timeslot_time_of_day
            ):
                issue(
                    "large_section_block",
                    "A large section cannot use a daytime double block.",
                    index,
                )
        elif room is not None:
            issue("unscheduled_room", "An unscheduled section cannot occupy a real room.", index)
        if room is not None:
            if room not in real_rooms:
                issue("unknown_room", f"Unknown real classroom {room!r}.", index)
            elif key in instance.attendance:
                heads, capacity = instance.attendance[key], instance.classroom_capacity[room]
                if heads > capacity:
                    issue(
                        "room_capacity",
                        f"{heads} students exceed {room!r} capacity {capacity}.",
                        index,
                    )
                if heads < instance.minimum_room_fill * capacity:
                    issue(
                        "room_fill",
                        f"{heads} students fall below the configured minimum fill "
                        f"for {room!r} ({instance.minimum_room_fill:g} x {capacity}).",
                        index,
                    )

    for key in sorted(instance.section_keys):
        count = sections[key]
        if count != 1:
            issue("section_count", f"Section {key!r} appears {count} times; expected exactly once.")
    for professor in sorted(real_professors):
        required = instance.teaching_load[professor]
        if loads[professor] < required:
            issue(
                "minimum_load",
                f"{professor!r} teaches {loads[professor]} sections; minimum load is {required}.",
            )

    overlaps = {frozenset(pair) for pair in instance.overlapping_timeslots}
    programs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for program, semester, course in instance.program_requirements:
        programs[(program, semester)].add(course)
    for (first_index, first), (second_index, second) in combinations(
        enumerate(result.assignments), 2
    ):
        if (
            first.semester_id != second.semester_id
            or first.timeslot_id is None
            or second.timeslot_id is None
        ):
            continue
        if (
            first.timeslot_id != second.timeslot_id
            and frozenset((first.timeslot_id, second.timeslot_id)) not in overlaps
        ):
            continue
        if first.professor_id in real_professors and first.professor_id == second.professor_id:
            issue(
                "professor_overlap",
                f"{first.professor_id!r} has overlapping assignments.",
                first_index,
                second_index,
            )
        if first.classroom_id in real_rooms and first.classroom_id == second.classroom_id:
            issue(
                "room_overlap",
                f"{first.classroom_id!r} has overlapping assignments.",
                first_index,
                second_index,
            )
        for (program, semester), courses in sorted(programs.items()):
            if (
                semester == first.semester_id
                and len(courses) >= 2
                and first.course_id in courses
                and second.course_id in courses
            ):
                issue(
                    "program_overlap",
                    f"Program {program!r} has overlapping required sections in {semester!r}.",
                    first_index,
                    second_index,
                )
    return issues
