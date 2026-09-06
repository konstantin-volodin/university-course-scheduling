"""Course preferences must never silently restrict declared qualifications."""

from collections import Counter
from dataclasses import replace

import pytest

from scheduler import config, silent
from scheduler.config.instance import Instance
from scheduler.solve import solve_instance


@pytest.mark.parametrize("qualification", ["", "qualified_for: all,"])
def test_nonpreferred_courses_can_be_required_for_a_legal_timetable(qualification: str) -> None:
    # Both professors can fill their load from preferred courses alone, but each
    # preferred pair meets simultaneously. A load-only check misses that clash.
    payload = config.loads(
        f"""
semesters: [Fall]
meeting_patterns:
  morning:
    time_of_day: Morning
    custom:
      AM: [{{day: Mon, start: '09:00', minutes: 90}}]
  afternoon:
    time_of_day: Afternoon
    custom:
      PM: [{{day: Mon, start: '13:00', minutes: 90}}]
classrooms: {{R1: 30, R2: 30}}
professors:
  p1: {{{qualification} teaching_load: 2, course_ranks: {{C1: 5, C2: 4}}}}
  p2: {{{qualification} teaching_load: 2, course_ranks: {{C3: 5, C4: 4}}}}
courses:
  C1:
    sections:
      - {{id: '1', semester: Fall, time_of_day: Morning, students: 30}}
  C2:
    sections:
      - {{id: '2', semester: Fall, time_of_day: Morning, students: 30}}
  C3:
    sections:
      - {{id: '3', semester: Fall, time_of_day: Afternoon, students: 30}}
  C4:
    sections:
      - {{id: '4', semester: Fall, time_of_day: Afternoon, students: 30}}
"""
    )
    inst = Instance.from_payload(payload)
    assert inst.qualifications == frozenset(
        (professor, course) for professor in ("p1", "p2") for course in ("C1", "C2", "C3", "C4")
    )
    result = solve_instance(inst, progress=silent, time_limit=10)
    assert not result.unstaffed
    assert not result.unscheduled
    assert not result.off_campus
    assert Counter(a.professor_id for a in result.assignments) == {"p1": 2, "p2": 2}
    assert all((a.professor_id, a.course_id) in inst.qualifications for a in result.assignments)
    assert len({(a.professor_id, a.timeslot_id) for a in result.assignments}) == 4
    repeated = solve_instance(inst, progress=silent, time_limit=10)
    assert repeated.assignments == result.assignments

    # Explicit restrictions still apply, even when they force unscheduled work.
    restricted = replace(inst, qualifications=frozenset(inst.course_preference))
    worse = solve_instance(restricted, progress=silent, time_limit=10)
    assert len(worse.unscheduled) == 2
    assert not worse.unstaffed
    assert all(
        (a.professor_id, a.course_id) in restricted.qualifications for a in worse.assignments
    )
    assert worse.stages[1].value > result.stages[1].value
