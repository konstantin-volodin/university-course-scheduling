"""Modern human-edited YAML reaches the validated model without losing semantics."""

from typing import Any

import pytest
import yaml

from scheduler import config
from scheduler.config.instance import Instance
from scheduler.errors import InvalidInstanceError


@pytest.fixture
def document() -> dict[str, Any]:
    return yaml.safe_load("""
semesters: [Fall, Winter]
meeting_patterns:
  regular:
    generate:
      formats:
        - {meetings: 2, minutes_each: 75, day_combinations: [[Mon, Thu]]}
      start_times: ['09:00', '10:30']
    custom:
      special:
        - {day: Mon, start: '09:00', minutes: 75}
        - {day: Thu, start: '10:30', minutes: 75}
  evening:
    time_of_day: Night
    custom:
      evening: [{day: Tue, start: '18:00', minutes: 150}]
classrooms: {R1: 40}
professors:
  p1: {teaching_load: 2, qualified_for: all}
course_defaults:
  semester: Fall
  meeting_patterns: [regular]
courses:
  C1:
    sections: [{id: '1', students: 30}]
""")


def instance(document: dict[str, Any]) -> Instance:
    return Instance.from_payload(config.loads(yaml.safe_dump(document)))


def test_defaults_course_and_section_overrides(document: dict[str, Any]) -> None:
    document["courses"]["C2"] = {
        "semester": "Winter",
        "meeting_patterns": ["evening"],
        "sections": [
            {"id": "1", "students": 30},
            {"id": "2", "students": 30, "semester": "Fall", "meeting_patterns": ["regular"]},
        ],
    }
    result = instance(document)
    assert len(result.section_patterns[("C1", "1", "Fall", "Any")]) == 4
    assert result.section_patterns[("C2", "1", "Winter", "Any")] == {"evening"}
    assert len(result.section_patterns[("C2", "2", "Fall", "Any")]) == 4


def test_custom_and_generated_share_candidates(document: dict[str, Any]) -> None:
    result = instance(document)
    candidates = result.section_patterns[("C1", "1", "Fall", "Any")]
    assert "special" in candidates
    assert len(candidates) == 4
    assert len(result.meeting_patterns) == 5
    assert {m.start_minutes for m in result.meeting_patterns["special"].meetings} == {540, 630}


def test_formats_restrict_without_changing_pool(document: dict[str, Any]) -> None:
    document["course_defaults"]["meeting_patterns"] = ["regular", "evening"]
    document["course_defaults"]["formats"] = [{"meetings": 1, "minutes_each": 150}]
    result = instance(document)
    assert result.section_patterns[("C1", "1", "Fall", "Any")] == {"evening"}
    assert len(result.meeting_patterns) == 5
    document["course_defaults"]["formats"] = [{"meetings": 3, "minutes_each": 50}]
    with pytest.raises(InvalidInstanceError, match="no candidate bundles"):
        instance(document)


def test_any_and_explicit_time_categories(document: dict[str, Any]) -> None:
    document["course_defaults"]["meeting_patterns"] = ["regular", "evening"]
    assert len(instance(document).section_patterns[("C1", "1", "Fall", "Any")]) == 5
    document["course_defaults"]["time_of_day"] = "Night"
    assert instance(document).section_patterns[("C1", "1", "Fall", "Night")] == {"evening"}


def test_professor_windows_keep_semesters_and_negative_scores(document: dict[str, Any]) -> None:
    professor = document["professors"]["p1"]
    professor["unavailable"] = [
        {"semester": "Winter", "days": ["Thu"], "start": "10:30", "end": "11:45"}
    ]
    professor["time_preferences"] = [
        {"days": ["Mon"], "start": "09:00", "end": "10:15", "score": -3},
        {"semester": "Fall", "days": ["Thu"], "start": "10:30", "end": "11:45", "score": -2},
    ]
    result = instance(document)
    assert ("p1", "Winter", "special") in result.forbidden_professor_patterns
    assert ("p1", "Fall", "special") not in result.forbidden_professor_patterns
    assert result.professor_pattern_preference[("p1", "Fall", "special")] == -5
    assert result.professor_pattern_preference[("p1", "Winter", "special")] == -3


def test_strict_and_general_policy(document: dict[str, Any]) -> None:
    document["strict"] = True
    result = instance(document)
    assert result.strict
    assert result.large_section_threshold is None
    document["strict"] = "yes"
    with pytest.raises(InvalidInstanceError, match="strict"):
        instance(document)


def test_telfer_durations_require_explicit_override(document: dict[str, Any]) -> None:
    instance(document)
    document["preset"] = "telfer"
    with pytest.raises(InvalidInstanceError, match="duration is not allowed"):
        instance(document)
    document["policy"] = {"allowed_durations": [75, 150]}
    result = instance(document)
    assert result.large_section_threshold == 75


@pytest.mark.parametrize("location", ["policy", "course_defaults", "section", "professor"])
def test_unknown_fields_fail(document: dict[str, Any], location: str) -> None:
    if location == "section":
        target = document["courses"]["C1"]["sections"][0]
    elif location == "professor":
        target = document["professors"]["p1"]
    else:
        target = document.setdefault(location, {})
    target["typo"] = 1
    with pytest.raises(InvalidInstanceError, match="unknown field"):
        instance(document)


@pytest.mark.parametrize(
    "policy",
    [
        {"allowed_durations": [True]},
        {"long_meeting_minutes": 0},
        {"large_section_threshold": -1},
        {"minimum_room_fill": 1.1},
    ],
)
def test_policy_validation(document: dict[str, Any], policy: dict[str, Any]) -> None:
    document["policy"] = policy
    with pytest.raises(InvalidInstanceError):
        instance(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("calendar", {"typo": 123}),
        ("timeslots", "ignored"),
        ("overlapping_timeslots", [["invalid", "invalid"]]),
    ],
)
def test_modern_patterns_reject_conflicting_sources(
    document: dict[str, Any],
    field: str,
    value: Any,
) -> None:
    document[field] = value
    with pytest.raises(InvalidInstanceError, match=field):
        instance(document)


def test_duplicate_semesters_rejected(document: dict[str, Any]) -> None:
    document["semesters"] = ["Fall", "Fall"]
    with pytest.raises(InvalidInstanceError, match="semesters"):
        instance(document)


def test_accumulated_preference_must_remain_finite(document: dict[str, Any]) -> None:
    document["professors"]["p1"]["time_preferences"] = [
        {"days": ["Mon"], "start": "09:00", "end": "10:00", "score": 1e308},
        {"days": ["Mon"], "start": "09:00", "end": "10:00", "score": 1e308},
    ]
    with pytest.raises(InvalidInstanceError, match="finite"):
        instance(document)
