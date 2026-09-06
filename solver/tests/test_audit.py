"""Tamper with a legal tiny schedule to exercise the independent audit."""

from dataclasses import replace
from typing import Any

import pytest

from scheduler.audit import audit_result
from scheduler.config import Instance
from scheduler.solve import Assignment, Result


@pytest.fixture
def instance(payload: dict[str, Any]) -> Instance:
    return Instance.from_payload(payload)


@pytest.fixture
def result() -> Result:
    return Result(
        "optimal",
        0,
        [
            Assignment("prof_a", "ADM1000", "1", "Fall", "Mon0900", "DMS1160", "Day", 1),
            Assignment("prof_b", "ADM1000", "2", "Fall", "Wed0900", "DMS1160", "Day", 1),
            Assignment("prof_a", "ADM2000", "3", "Fall", "Mon1800", "DMS1150", "Night", 1),
        ],
    )


def test_valid_tiny_schedule_passes(instance: Instance, result: Result) -> None:
    assert audit_result(instance, result) == []


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"course_id": "missing"}, "unknown_section"),
        ({"section_id": "missing"}, "unknown_section"),
        ({"semester_id": "missing"}, "unknown_section"),
        ({"time_of_day_id": "Night"}, "unknown_section"),
        ({"professor_id": "missing"}, "unknown_professor"),
        ({"classroom_id": "missing"}, "unknown_room"),
        ({"timeslot_id": "missing"}, "unknown_timeslot"),
        ({"timeslot_id": "Mon1800"}, "timeslot_period"),
        ({"timeslot_id": None}, "unscheduled_room"),
        ({"solution_value": 0.5}, "assignment_value"),
        ({"solution_value": float("nan")}, "assignment_value"),
    ],
)
def test_assignment_tampering(
    instance: Instance,
    result: Result,
    changes: dict[str, Any],
    code: str,
) -> None:
    changed = replace(
        result, assignments=[replace(result.assignments[0], **changes), *result.assignments[1:]]
    )
    assert code in {issue.code for issue in audit_result(instance, changed)}


def test_missing_duplicate_and_underload(instance: Instance, result: Result) -> None:
    missing = replace(result, assignments=result.assignments[1:])
    assert {"section_count", "minimum_load"} <= {
        issue.code for issue in audit_result(instance, missing)
    }
    duplicate = replace(result, assignments=[*result.assignments, result.assignments[0]])
    assert "section_count" in {issue.code for issue in audit_result(instance, duplicate)}


def test_qualification_and_night_permission(instance: Instance, result: Result) -> None:
    changed = replace(
        result,
        assignments=[
            *result.assignments[:2],
            replace(result.assignments[2], professor_id="prof_b"),
        ],
    )
    assert {"qualification", "night_permission"} <= {
        issue.code for issue in audit_result(instance, changed)
    }


def test_room_capacity_and_configurable_fill(instance: Instance, result: Result) -> None:
    small = replace(instance, classroom_capacity={**instance.classroom_capacity, "DMS1160": 30})
    assert "room_capacity" in {issue.code for issue in audit_result(small, result)}
    strict = replace(instance, minimum_room_fill=0.9)
    assert "room_fill" in {issue.code for issue in audit_result(strict, result)}
    permissive = replace(instance, minimum_room_fill=0.5)
    assert audit_result(permissive, result) == []


def test_fallbacks_and_off_campus_permission(instance: Instance, result: Result) -> None:
    restricted = replace(instance, can_teach_off_campus=frozenset())
    changed = replace(
        result,
        assignments=[replace(result.assignments[0], classroom_id=None), *result.assignments[1:]],
    )
    assert "off_campus_permission" in {issue.code for issue in audit_result(restricted, changed)}
    unscheduled = replace(
        changed,
        assignments=[replace(changed.assignments[0], timeslot_id=None), *changed.assignments[1:]],
    )
    assert audit_result(restricted, unscheduled) == []
    no_loads = replace(restricted, teaching_load=dict.fromkeys(instance.professors, 0))
    fallback = replace(
        result,
        assignments=[
            replace(a, professor_id=None, timeslot_id=None, classroom_id=None)
            for a in result.assignments
        ],
    )
    assert audit_result(no_loads, fallback) == []


@pytest.mark.parametrize("declared_overlap", [False, True])
def test_resource_overlaps(instance: Instance, result: Result, declared_overlap: bool) -> None:
    changed = replace(
        result,
        assignments=[
            result.assignments[0],
            replace(
                result.assignments[1],
                professor_id="prof_a",
                timeslot_id="Wed0900" if declared_overlap else "Mon0900",
            ),
            result.assignments[2],
        ],
    )
    if declared_overlap:
        instance = replace(instance, overlapping_timeslots=frozenset({("Wed0900", "Mon0900")}))
    codes = {issue.code for issue in audit_result(instance, changed)}
    assert {"professor_overlap", "room_overlap"} <= codes


def test_program_conflicts_include_parallel_sections(instance: Instance, result: Result) -> None:
    instance = replace(
        instance,
        program_requirements=frozenset(
            {
                ("degree", "Fall", "ADM1000"),
                ("degree", "Fall", "ADM2000"),
            }
        ),
    )
    assert audit_result(instance, result) == []
    changed = replace(
        result,
        assignments=[
            result.assignments[0],
            replace(result.assignments[1], timeslot_id="Mon0900", classroom_id="DMS1150"),
            result.assignments[2],
        ],
    )
    assert "program_overlap" in {issue.code for issue in audit_result(instance, changed)}
    one_course = replace(instance, program_requirements=frozenset({("degree", "Fall", "ADM1000")}))
    assert "program_overlap" not in {issue.code for issue in audit_result(one_course, changed)}


def test_large_sections_cannot_use_daytime_double_blocks(
    instance: Instance, result: Result
) -> None:
    key = ("ADM1000", "1", "Fall", "Day")
    instance = replace(
        instance,
        attendance={**instance.attendance, key: 500},
        timeslot_block=instance.timeslot_block | {("Mon0900", "3.0")},
    )
    assert "large_section_block" in {issue.code for issue in audit_result(instance, result)}


def test_overlaps_do_not_cross_semesters(instance: Instance, result: Result) -> None:
    winter = [replace(a, semester_id="Winter") for a in result.assignments]
    instance = replace(
        instance,
        semesters=instance.semesters | {"Winter"},
        section_keys=instance.section_keys
        | {(course, section, "Winter", tod) for course, section, _, tod in instance.section_keys},
        attendance={
            **instance.attendance,
            **{
                (course, section, "Winter", tod): heads
                for (course, section, _, tod), heads in instance.attendance.items()
            },
        },
    )
    assert audit_result(instance, replace(result, assignments=[*result.assignments, *winter])) == []


def test_soft_course_concurrency_does_not_fail_audit(instance: Instance, result: Result) -> None:
    instance = replace(instance, must_run_together=frozenset({("ADM1000", "ADM2000", "Fall")}))
    assert audit_result(instance, result) == []
