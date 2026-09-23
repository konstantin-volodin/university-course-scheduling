"""Regression checks for pattern eligibility and institutional policy."""

from dataclasses import replace
from typing import Any

import pytest

from scheduler.config import OFF_CAMPUS, PART_TIMER, Instance, is_placeholder
from scheduler.model import build
from scheduler.progress import Progress, silent


def test_strict_candidates_have_real_resources(payload: dict[str, Any]) -> None:
    instance = replace(Instance.from_payload(payload), strict=True)
    model = build(instance, Progress(silent))
    assert model.assign
    assert all(
        key.professor != PART_TIMER
        and key.classroom != OFF_CAMPUS
        and not is_placeholder(key.timeslot)
        for key in model.assign
    )


def test_section_and_professor_pattern_restrictions(payload: dict[str, Any]) -> None:
    instance = Instance.from_payload(payload)
    section = ("ADM1000", "1", "Fall", "Day")
    instance = replace(
        instance,
        section_patterns={section: frozenset({"Wed0900"})},
        forbidden_professor_patterns=frozenset({("prof_a", "Fall", "Wed0900")}),
    )
    model = build(instance, Progress(silent))
    choices = [
        key for key in model.assign
        if (key.course, key.section, key.semester, key.time_of_day) == section
        and not is_placeholder(key.timeslot)
    ]
    assert choices
    assert all(key.timeslot == "Wed0900" and key.professor != "prof_a" for key in choices)


def test_empty_eligibility_is_infeasible_in_strict_mode(payload: dict[str, Any]) -> None:
    section = ("ADM1000", "1", "Fall", "Day")
    instance = replace(
        Instance.from_payload(payload), strict=True,
        section_patterns={section: frozenset()},
    )
    model = build(instance, Progress(silent))
    row = next(
        row for row in model.program.rows
        if row.name == "section_taught_once[ADM1000,1,Fall,Day]"
    )
    assert row.terms == {}
    assert row.rhs == 1.0


def test_pattern_preference_contributes_to_time_reward(payload: dict[str, Any]) -> None:
    instance = Instance.from_payload(payload)
    original = build(instance, Progress(silent))
    preferred = build(
        replace(instance, professor_pattern_preference={("prof_a", "Fall", "Wed0900"): 7.0}),
        Progress(silent),
    )
    assert original.assign == preferred.assign
    for key, variable in original.assign.items():
        delta = (
            preferred.objectives.time_reward.terms.get(variable, 0)
            - original.objectives.time_reward.terms.get(variable, 0)
        )
        assert delta == (
            7 if key.professor == "prof_a" and key.timeslot == "Wed0900" else 0
        )


def test_daily_load_uses_each_meeting_duration(payload: dict[str, Any]) -> None:
    from scheduler.config.patterns import Meeting, MeetingPattern

    instance = Instance.from_payload(payload)
    instance = replace(
        instance,
        meeting_patterns={
            "Mon0900": MeetingPattern(
                "Mon0900", (Meeting("Mon", 540, 50), Meeting("Wed", 600, 75))
            )
        },
        timeslot_day=instance.timeslot_day | {("Mon0900", "Wed")},
    )
    model = build(instance, Progress(silent))
    variable = next(
        variable for key, variable in model.assign.items() if key.timeslot == "Mon0900"
    )
    rows = {row.name: row for row in model.program.rows}
    assert rows["day_of_week_max[Fall,Mon]"].terms[variable] == 50 / 180
    assert rows["day_of_week_max[Fall,Wed]"].terms[variable] == 75 / 180


def test_any_period_uses_eligible_patterns_and_night_permission(payload: dict[str, Any]) -> None:
    original = Instance.from_payload(payload)
    section = ("ADM1000", "1", "Fall", "Any")
    instance = replace(
        original,
        section_keys=frozenset({section}),
        attendance={section: 40},
        section_patterns={section: frozenset({"Mon0900", "Mon1800"})},
        can_teach_night=frozenset({"prof_a"}),
    )
    model = build(instance, Progress(silent))
    assert any(key.timeslot == "Mon1800" for key in model.assign)
    assert any(key.timeslot == "Mon0900" for key in model.assign)
    assert not any(
        key.timeslot == "Mon1800" and key.professor == "prof_b" for key in model.assign
    )


def test_modern_strict_solve_with_long_meeting(tmp_path: Any) -> None:
    from scheduler.config import load
    from scheduler.solve import solve_instance

    path = tmp_path / "instance.yaml"
    path.write_text("""
semesters: [Fall]
strict: true
meeting_patterns:
  long:
    custom:
      four_hours:
        - {day: Mon, start: "08:00", minutes: 240}
classrooms: {R: 40}
professors:
  professor: {teaching_load: 1, qualified_for: all}
courses:
  COURSE:
    sections: [{id: "1", students: 30}]
""")
    instance = Instance.from_payload(load(path))
    result = solve_instance(instance, time_limit=5)
    assert result.assignments[0].timeslot_id == "four_hours"
    assert result.assignments[0].professor_id == "professor"
    assert result.assignments[0].classroom_id == "R"

    from scheduler.errors import SolveError

    impossible = replace(instance, attendance=dict.fromkeys(instance.section_keys, 50))
    with pytest.raises(SolveError):
        solve_instance(impossible, time_limit=5)


def test_modern_mixed_pool_solve(tmp_path: Any) -> None:
    from scheduler.config import load
    from scheduler.solve import solve_instance

    path = tmp_path / "instance.yaml"
    path.write_text("""
semesters: [Fall]
strict: true
meeting_patterns:
  day:
    time_of_day: Day
    generate:
      formats:
        - meetings: 1
          minutes_each: 50
          day_combinations: [[Mon]]
      start_times: ["09:00"]
  night:
    time_of_day: Night
    custom:
      evening:
        - {day: Mon, start: "18:00", minutes: 50}
classrooms: {R: 40}
professors:
  professor: {teaching_load: 2, qualified_for: all}
courses:
  COURSE:
    sections:
      - {id: "1", students: 30}
      - {id: "2", students: 30}
""")
    instance = Instance.from_payload(load(path))
    model = build(instance, Progress(silent))
    assert not any(row.name == "time_of_day_max[Fall,Any]" for row in model.program.rows)
    result = solve_instance(instance, time_limit=5)
    assert len({assignment.timeslot_id for assignment in result.assignments}) == 2
    assert all(assignment.time_of_day_id == "Any" for assignment in result.assignments)


def test_fractional_balance_cannot_be_traded_for_pattern_reward(tmp_path: Any) -> None:
    from scheduler.config import load
    from scheduler.solve import solve_instance

    path = tmp_path / "instance.yaml"
    path.write_text("""
semesters: [Fall]
strict: true
meeting_patterns:
  options:
    custom:
      short:
        - {day: Mon, start: "09:00", minutes: 50}
      long:
        - {day: Tue, start: "09:00", minutes: 75}
classrooms: {R: 40}
professors:
  professor: {teaching_load: 1, qualified_for: all}
courses:
  COURSE:
    sections: [{id: "1", students: 30}]
""")
    instance = replace(
        Instance.from_payload(load(path)),
        professor_pattern_preference={("professor", "Fall", "long"): 100},
    )
    result = solve_instance(instance, time_limit=5)
    assert result.assignments[0].timeslot_id == "short"
    assert result.stages[6].value == pytest.approx(50 / 180)
