"""YAML configuration tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scheduler import config, solve
from scheduler.config.instance import PAYLOAD_KEYS, Instance
from scheduler.errors import InvalidInstanceError
from scheduler.progress import silent

INSTANCES = Path(__file__).parents[2] / "instances"
TINY = INSTANCES / "tiny"
MEDIUM = INSTANCES / "medium"
TELFER = INSTANCES / "telfer"


@pytest.fixture(scope="module")
def medium_payload() -> dict[str, Any]:
    return config.load(MEDIUM)


def test_config_carries_every_payload_key(medium_payload: dict[str, Any]) -> None:
    assert set(medium_payload) == set(PAYLOAD_KEYS)


def test_config_solves(medium_payload: dict[str, Any]) -> None:
    result = solve(medium_payload, progress=silent, time_limit=20)
    assert result.status in {"optimal", "feasible"}
    assert len(result.assignments) == 36
    assert not result.unstaffed
    assert not result.unscheduled


def test_config_is_a_valid_instance(medium_payload: dict[str, Any]) -> None:
    Instance.from_payload(medium_payload)


def test_tiny_example_is_valid_and_solvable() -> None:
    result = solve(config.load(TINY), progress=silent, time_limit=10)
    assert result.status in {"optimal", "feasible"}
    assert len(result.assignments) == 3
    assert {assignment.section_id for assignment in result.assignments} == {1, 2, 3}
    assert not result.unscheduled


def test_single_file_instance_is_supported() -> None:
    Instance.from_payload(config.load(TINY))


def test_meeting_times_derive_clock_overlaps() -> None:
    payload = config.loads(
        """
semesters: [Fall]
meeting_times:
  - {id: A, days: {Mon: '09:00'}, duration_minutes: 90, time_of_day: Morning}
  - {id: B, days: {Mon: '10:00'}, duration_minutes: 90, time_of_day: Morning}
  - {id: C, days: {Mon: '11:30'}, duration_minutes: 90, time_of_day: Morning}
classrooms: {R1: 30}
professors:
  p1: {teaching_load: 1, qualified_for: all}
courses:
  C1:
    sections:
      - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
"""
    )
    assert payload["timeslot_concurrency"] == [["A", "B"]]
    assert payload["professor_pack_day_pref"] == [["p1", 0]]


def test_meeting_time_typo_is_reported() -> None:
    with pytest.raises(InvalidInstanceError, match="unknown field 'starts'"):
        config.loads(
            """
semesters: [Fall]
meeting_times:
  - {id: A, days: {Mon: '09:00'}, starts: '09:00', duration_minutes: 90, time_of_day: Morning}
classrooms: {}
professors: {}
courses: {}
"""
        )


def test_professor_field_typo_is_reported_with_suggestion() -> None:
    with pytest.raises(
        InvalidInstanceError,
        match="unknown field 'teahing_load'; did you mean 'teaching_load'",
    ):
        config.loads(
            """
semesters: [Fall]
meeting_times:
  - {id: A, days: {Mon: '09:00'}, duration_minutes: 90, time_of_day: Morning}
classrooms: {R1: 30}
professors:
  p1: {teahing_load: 1, qualified_for: all}
courses:
  C1:
    sections:
      - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
"""
        )


def test_manifest_can_merge_multiple_professor_files(tmp_path: Path) -> None:
    (tmp_path / "instance.yaml").write_text(
        """
semesters: [Fall]
files:
  meeting_times: meetings.yaml
  classrooms: rooms.yaml
  professors: [professors-a.yaml, professors-b.yaml]
  courses: courses.yaml
"""
    )
    (tmp_path / "meetings.yaml").write_text(
        "- {id: A, days: {Mon: '09:00'}, duration_minutes: 90, time_of_day: Morning}\n"
    )
    (tmp_path / "rooms.yaml").write_text("R1: 30\n")
    (tmp_path / "professors-a.yaml").write_text(
        "p1: {teaching_load: 1, qualified_for: all}\n"
    )
    (tmp_path / "professors-b.yaml").write_text(
        "p2: {teaching_load: 0, qualified_for: [C1]}\n"
    )
    (tmp_path / "courses.yaml").write_text(
        """
C1:
  sections:
    - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
"""
    )

    payload = config.load(tmp_path)
    assert payload["professor_set"] == ["p1", "p2"]


def test_all_public_examples_are_valid() -> None:
    for source in (TINY, MEDIUM, TELFER):
        Instance.from_payload(config.load(source))


def test_missing_section_is_reported_not_crashed() -> None:
    with pytest.raises(InvalidInstanceError, match="missing required section: courses"):
        config.loads("calendar: {}\ntimeslots: []\nclassrooms: {}\nprofessors: {}\n")


def test_bad_yaml_is_reported_not_crashed() -> None:
    with pytest.raises(InvalidInstanceError, match="invalid YAML"):
        config.loads("calendar: [unclosed\n")


def test_preferences_live_under_the_professor(medium_payload: dict[str, Any]) -> None:
    assert {"key": ["prof00", "Winter", "Afternoon"], "value": 1} in medium_payload[
        "professor_time_pref"
    ]
    assert {"key": ["prof00", "ADM1112"], "value": 5} in medium_payload[
        "professor_course_pref"
    ]


def test_course_codes_and_slugs_survive_as_written() -> None:
    payload = config.loads(
        """
calendar: {semesters: [Fall], days: [Mon], times_of_day: [Morning], class_lengths: [single]}
timeslots:
  - days: [Mon]
    length: single
    slots: {Morning: [F1]}
classrooms: {1110: 40}
professors:
  traore-namatie:
    teaching_load: 2
    qualified_for: [ADM2341]
    availability:
      Fall: {Morning: 3}
    course_ranks: {ADM2341: 2}
courses:
  ADM2341:
    sections:
      - {id: ADM2341-1, semester: Fall, time_of_day: Morning, students: 30}
"""
    )
    assert payload["professor_set"] == ["traore-namatie"]
    assert payload["course_set"] == ["ADM2341"]
    assert payload["section_set"] == ["ADM2341-1"]
    assert payload["professor_course_pref"] == [{"key": ["traore-namatie", "ADM2341"], "value": 2}]
    assert payload["professor_time_pref"] == [
        {"key": ["traore-namatie", "Fall", "Morning"], "value": 3}
    ]
    assert payload["classroom_set"] == ["1110"]
