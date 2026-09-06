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


BASE = """
semesters: [Fall]
meeting_times:
  - {id: A, days: {Mon: '09:00'}, duration_minutes: 90, time_of_day: Morning}
  - {id: N, days: {Mon: '19:00'}, duration_minutes: 90, time_of_day: Night}
classrooms: {R1: 30}
"""


def test_professor_defaults_apply_when_flags_are_omitted() -> None:
    payload = config.loads(
        BASE
        + """
professor_defaults: {can_teach_night: true, prefers_packed_days: true}
professors:
  p1: {teaching_load: 1, qualified_for: all}
  p2: {teaching_load: 1, qualified_for: all, can_teach_night: false}
courses:
  C1:
    sections:
      - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
"""
    )
    assert payload["professor_can_teach_night"] == [["p1", True], ["p2", False]]
    assert payload["professor_pack_day_pref"] == [["p1", 1], ["p2", 1]]


def test_course_defaults_apply_when_flags_are_omitted() -> None:
    payload = config.loads(
        BASE
        + """
course_defaults: {penalise_friday_night: true}
professors:
  p1: {teaching_load: 1, qualified_for: all}
courses:
  C1:
    sections:
      - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
  C2:
    penalise_friday_night: false
    sections:
      - {id: C2-1, semester: Fall, time_of_day: Morning, students: 30}
"""
    )
    assert payload["course_friday_penalty"] == ["C1"]


def test_defaults_without_a_block_keep_the_old_behavior() -> None:
    payload = config.loads(
        BASE
        + """
professors:
  p1: {teaching_load: 1, qualified_for: all}
courses:
  C1:
    sections:
      - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
"""
    )
    assert payload["professor_can_teach_night"] == [["p1", False]]
    assert payload["professor_pack_day_pref"] == [["p1", 0]]
    assert payload["course_friday_penalty"] == []


def test_non_boolean_default_is_reported() -> None:
    with pytest.raises(
        InvalidInstanceError,
        match=r"professor_defaults.can_teach_night: expected true or false",
    ):
        config.loads(
            BASE
            + """
professor_defaults: {can_teach_night: maybe}
professors:
  p1: {teaching_load: 1, qualified_for: all}
courses:
  C1:
    sections:
      - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
"""
        )


def test_unknown_default_key_is_reported_with_suggestion() -> None:
    with pytest.raises(
        InvalidInstanceError,
        match="professor_defaults: unknown field 'can_teach_knight'; "
        "did you mean 'can_teach_night'",
    ):
        config.loads(
            BASE
            + """
professor_defaults: {can_teach_knight: true}
professors:
  p1: {teaching_load: 1, qualified_for: all}
courses:
  C1:
    sections:
      - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
"""
        )


def test_manifest_carries_defaults(tmp_path: Path) -> None:
    (tmp_path / "instance.yaml").write_text(
        """
semesters: [Fall]
professor_defaults: {can_teach_night: true}
course_defaults: {penalise_friday_night: true}
files:
  meeting_times: meetings.yaml
  classrooms: rooms.yaml
  professors: professors.yaml
  courses: courses.yaml
"""
    )
    (tmp_path / "meetings.yaml").write_text(
        "- {id: A, days: {Mon: '09:00'}, duration_minutes: 90, time_of_day: Morning}\n"
    )
    (tmp_path / "rooms.yaml").write_text("R1: 30\n")
    (tmp_path / "professors.yaml").write_text(
        "p1: {teaching_load: 1, qualified_for: all}\n"
    )
    (tmp_path / "courses.yaml").write_text(
        """
C1:
  sections:
    - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
"""
    )

    payload = config.load(tmp_path)
    assert payload["professor_can_teach_night"] == [["p1", True]]
    assert payload["course_friday_penalty"] == ["C1"]


def test_professor_defaults_cover_preferred_class_length() -> None:
    payload = config.loads(
        BASE
        + """
professor_defaults: {preferred_class_length: single}
professors:
  p1: {teaching_load: 3, qualified_for: all}
  p2: {teaching_load: 1, qualified_for: [C1], preferred_class_length: double}
courses:
  C1:
    sections:
      - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
"""
    )
    assert payload["professor_block_pref"] == [["p1", "1.5"], ["p2", "double"]]


def test_qualified_for_defaults_to_all() -> None:
    payload = config.loads(
        BASE
        + """
professors:
  p1: {teaching_load: 1}
courses:
  C1:
    sections:
      - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
  C2:
    sections:
      - {id: C2-1, semester: Fall, time_of_day: Morning, students: 30}
"""
    )
    assert payload["professor_qualification"] == [["p1", "C1"], ["p1", "C2"]]


def test_course_defaults_cover_preferred_class_length() -> None:
    payload = config.loads(
        BASE
        + """
course_defaults: {preferred_class_length: single}
professors:
  p1: {teaching_load: 1, qualified_for: all}
courses:
  C1:
    sections:
      - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
"""
    )
    assert payload["course_block_pref"] == [["C1", "1.5"]]


def test_bad_preferred_class_length_default_is_reported() -> None:
    with pytest.raises(
        InvalidInstanceError,
        match=r"course_defaults\.preferred_class_length: expected a class-length name",
    ):
        config.loads(
            BASE
            + """
course_defaults: {preferred_class_length: 3}
professors:
  p1: {teaching_load: 1, qualified_for: all}
courses:
  C1:
    sections:
      - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
"""
        )


CONC = """
semesters: [Fall, Winter]
meeting_times:
  - {id: A, days: {Mon: '09:00'}, duration_minutes: 90, time_of_day: Morning}
classrooms: {R1: 30}
professors:
  p1: {teaching_load: 1, qualified_for: all}
courses:
  C1: {sections: [{id: C1-1, semester: Fall, time_of_day: Morning, students: 30}]}
  C2: {sections: [{id: C2-1, semester: Fall, time_of_day: Morning, students: 30}]}
  C3: {sections: [{id: C3-1, semester: Fall, time_of_day: Morning, students: 30}]}
"""


def test_concurrency_without_semester_covers_every_semester() -> None:
    payload = config.loads(
        CONC
        + """
course_concurrency:
  - {courses: [C1, C2], must_run: apart}
"""
    )
    assert payload["course_concurrency_nt"] == [
        ["C1", "C2", "Fall"],
        ["C1", "C2", "Winter"],
    ]


def test_concurrency_apart_expands_course_groups_to_pairs() -> None:
    payload = config.loads(
        CONC
        + """
course_concurrency:
  - {courses: [C1, C2, C3], semester: [Fall, Winter], must_run: apart}
"""
    )
    assert payload["course_concurrency_nt"] == [
        ["C1", "C2", "Fall"],
        ["C1", "C2", "Winter"],
        ["C1", "C3", "Fall"],
        ["C1", "C3", "Winter"],
        ["C2", "C3", "Fall"],
        ["C2", "C3", "Winter"],
    ]


def test_concurrency_together_still_requires_a_pair() -> None:
    with pytest.raises(
        InvalidInstanceError, match="'together' expects exactly two courses"
    ):
        config.loads(
            CONC
            + """
course_concurrency:
  - {courses: [C1, C2, C3], must_run: together}
"""
        )


def test_programs_parse_into_requirement_triples() -> None:
    payload = config.loads(
        BASE
        + """
professors:
  p1: {teaching_load: 1, qualified_for: all}
courses:
  C1:
    sections:
      - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
programs:
  bcom-finance:
    Fall: [C1]
    Winter: [C1]
"""
    )
    assert payload["program_requirements"] == [
        ["bcom-finance", "Fall", "C1"],
        ["bcom-finance", "Winter", "C1"],
    ]


def test_program_terms_must_be_course_lists() -> None:
    with pytest.raises(
        InvalidInstanceError, match=r"programs.bcom-finance.Fall: expected a list of course ids"
    ):
        config.loads(
            BASE
            + """
professors:
  p1: {teaching_load: 1, qualified_for: all}
courses:
  C1:
    sections:
      - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
programs:
  bcom-finance:
    Fall: C1
"""
        )


def test_manifest_can_carry_a_programs_file(tmp_path: Path) -> None:
    (tmp_path / "instance.yaml").write_text(
        """
semesters: [Fall]
files:
  meeting_times: meetings.yaml
  classrooms: rooms.yaml
  professors: professors.yaml
  courses: courses.yaml
  programs: programs.yaml
"""
    )
    (tmp_path / "meetings.yaml").write_text(
        "- {id: A, days: {Mon: '09:00'}, duration_minutes: 90, time_of_day: Morning}\n"
    )
    (tmp_path / "rooms.yaml").write_text("R1: 30\n")
    (tmp_path / "professors.yaml").write_text(
        "p1: {teaching_load: 1, qualified_for: all}\n"
    )
    (tmp_path / "courses.yaml").write_text(
        """
C1:
  sections:
    - {id: C1-1, semester: Fall, time_of_day: Morning, students: 30}
"""
    )
    (tmp_path / "programs.yaml").write_text("bcom:\n  Fall: [C1]\n")

    payload = config.load(tmp_path)
    assert payload["program_requirements"] == [["bcom", "Fall", "C1"]]
