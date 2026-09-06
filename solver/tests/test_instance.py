"""Validation is the whole point of this layer: every problem it catches here
is a bare KeyError from deep inside constraint generation that it prevents."""

from __future__ import annotations

from typing import Any

import pytest

from scheduler import Instance, InvalidInstanceError
from scheduler.config.instance import OFF_CAMPUS, PART_TIMER, placeholder_for


def problems_from(payload: dict[str, Any]) -> list[str]:
    with pytest.raises(InvalidInstanceError) as caught:
        Instance.from_payload(payload)
    return caught.value.problems


def test_tiny_payload_parses(payload: dict[str, Any]) -> None:
    instance = Instance.from_payload(payload)
    assert instance.real_professors == {"prof_a", "prof_b"}
    assert instance.courses == {"ADM1000", "ADM2000"}
    assert instance.teaching_load == {"prof_a": 2, "prof_b": 1}
    assert instance.can_teach_night == {"prof_a"}  # prof_b's flag is false


def test_fallbacks_are_added(payload: dict[str, Any]) -> None:
    instance = Instance.from_payload(payload)

    assert PART_TIMER in instance.professors
    assert OFF_CAMPUS in instance.classrooms
    assert placeholder_for("Day") in instance.timeslots
    assert placeholder_for("Night") in instance.timeslots
    assert (placeholder_for("Night"), "Night") in instance.timeslot_time_of_day

    # ... and the "real" views exclude them again
    assert PART_TIMER not in instance.real_professors
    assert OFF_CAMPUS not in instance.real_classrooms
    assert instance.real_timeslots == {"Mon0900", "Wed0900", "Mon1800"}


def test_missing_keys_are_all_reported(payload: dict[str, Any]) -> None:
    del payload["classroom_cap"]
    del payload["section_set"]
    problems = problems_from(payload)
    assert any("classroom_cap" in p for p in problems)
    assert any("section_set" in p for p in problems)


def test_reports_every_problem_not_just_the_first(payload: dict[str, Any]) -> None:
    payload["professor_qualification"].append(["ghost", "ADM1000"])
    payload["course_friday_penalty"] = ["NOSUCH"]
    problems = problems_from(payload)
    assert len(problems) >= 2
    assert any("ghost" in p for p in problems)
    assert any("NOSUCH" in p for p in problems)


def test_unknown_reference_is_caught(payload: dict[str, Any]) -> None:
    payload["section_subset"].append(["NOSUCH", "9", "Fall", "Day"])
    payload["section_attendance"].append(
        {"key": ["NOSUCH", "9", "Fall", "Day"], "value": 10}
    )
    assert any("NOSUCH" in p and "course" in p for p in problems_from(payload))


def test_missing_attendance_is_caught(payload: dict[str, Any]) -> None:
    payload["section_attendance"].pop()
    assert any("section_attendance" in p for p in problems_from(payload))


def test_missing_teaching_load_is_caught(payload: dict[str, Any]) -> None:
    payload["professor_teaching"] = [{"prof_a": 2}]
    assert any("prof_b" in p for p in problems_from(payload))


def test_missing_capacity_is_caught(payload: dict[str, Any]) -> None:
    payload["classroom_cap"] = [{"DMS1160": 50}]
    assert any("DMS1150" in p for p in problems_from(payload))


def test_reserved_ids_are_rejected(payload: dict[str, Any]) -> None:
    payload["professor_set"].append(PART_TIMER)
    payload["classroom_set"].append(OFF_CAMPUS)
    problems = problems_from(payload)
    assert any(PART_TIMER in p and "reserved" in p for p in problems)
    assert any(OFF_CAMPUS in p and "reserved" in p for p in problems)


def test_placeholder_timeslot_id_is_rejected(payload: dict[str, Any]) -> None:
    payload["timeslot_set"].append(placeholder_for("Day"))
    assert any("reserved" in p for p in problems_from(payload))


def test_unknown_block_type_is_rejected(payload: dict[str, Any]) -> None:
    """A block with no weight would silently contribute nothing to balance."""
    payload.pop("meeting_pattern_data", None)
    payload["block_type_set"].append("7.0")
    assert any("7.0" in p and "weight" in p for p in problems_from(payload))


def test_time_of_day_with_no_timeslots_is_rejected(payload: dict[str, Any]) -> None:
    """Sections at such a time could only ever get a placeholder."""
    payload["timeslot_tod_subset"] = [
        row for row in payload["timeslot_tod_subset"] if row[1] != "Night"
    ]
    assert any("Night" in p for p in problems_from(payload))


def test_malformed_row_is_reported_with_its_index(payload: dict[str, Any]) -> None:
    payload["professor_qualification"].append(["only_one_value"])
    assert any("professor_qualification[" in p for p in problems_from(payload))


def test_non_numeric_capacity_is_reported(payload: dict[str, Any]) -> None:
    payload["classroom_cap"] = [{"DMS1160": "big"}, {"DMS1150": 40}]
    assert any("classroom_cap" in p for p in problems_from(payload))


def test_payload_must_be_an_object() -> None:
    with pytest.raises(InvalidInstanceError):
        Instance.from_payload([])  # type: ignore[arg-type]


def test_instance_is_immutable(payload: dict[str, Any]) -> None:
    instance = Instance.from_payload(payload)
    with pytest.raises(AttributeError):
        instance.courses = frozenset()  # type: ignore[misc]


def test_summary_mentions_the_real_sizes(payload: dict[str, Any]) -> None:
    summary = Instance.from_payload(payload).summary()
    assert "2 professors" in summary
    assert "3 sections" in summary


def test_timeslot_concurrency_accepts_pairs_as_well_as_mappings(
    payload: dict[str, Any],
) -> None:
    """Pair form used to be silently discarded, taking the clash with it.

    The Django endpoint sends {"timeslot_1": a, "timeslot_2": b}; a config file
    or a hand-written instance sends [a, b]. A dropped clash does not fail — it
    produces a schedule that double-books, and looks fine.
    """
    payload["timeslot_concurrency"] = [["Mon0900", "Wed0900"]]
    assert Instance.from_payload(payload).overlapping_timeslots == {("Mon0900", "Wed0900")}

    payload["timeslot_concurrency"] = [{"timeslot_1": "Mon0900", "timeslot_2": "Wed0900"}]
    assert Instance.from_payload(payload).overlapping_timeslots == {("Mon0900", "Wed0900")}


def test_malformed_timeslot_concurrency_is_reported(payload: dict[str, Any]) -> None:
    payload["timeslot_concurrency"] = ["Mon0900", ["a", "b", "c"]]
    with pytest.raises(InvalidInstanceError, match="expected two timeslot ids"):
        Instance.from_payload(payload)


def test_program_requirements_reference_known_courses_and_semesters(
    payload: dict[str, Any],
) -> None:
    payload["program_requirements"].append(["bcom", "NOSUCH", "ADM1000"])
    payload["program_requirements"].append(["bcom", "Fall", "NOSUCH"])
    problems = problems_from(payload)
    assert len(problems) >= 2
    assert any("semester" in p and "NOSUCH" in p for p in problems)
    assert any("course" in p and "NOSUCH" in p for p in problems)
