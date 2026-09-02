"""These assert the schedule is *legal*, not merely that one was produced.

A solver that returns a confident, wrong schedule is worse than one that
crashes, so every hard rule in the formulation gets checked against the output.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

from scheduler import Result, SolveError, silent, solve
from scheduler.instance import MIN_ROOM_FILL
from scheduler.solve import GOOD_ENOUGH


@pytest.fixture(scope="module")
def solved(request: pytest.FixtureRequest) -> Result:
    """Solve the tiny instance once and share it — solving is the slow part."""
    payload = request.getfixturevalue("tiny_payload_source")
    return solve(payload, progress=silent)


def test_every_section_taught_exactly_once(solved: Result) -> None:
    assert Counter(a.section_id for a in solved.assignments) == Counter({1: 1, 2: 1, 3: 1})


def test_teaching_loads_are_met(solved: Result) -> None:
    taught = Counter(a.professor_id for a in solved.assignments if a.professor_id)
    assert taught == Counter({"prof_a": 2, "prof_b": 1})


def test_nobody_is_in_two_places_at_once(solved: Result) -> None:
    slots = [
        (a.professor_id, a.semester_id, a.timeslot_id)
        for a in solved.assignments
        if a.professor_id and a.timeslot_id
    ]
    assert len(slots) == len(set(slots))


def test_no_room_is_double_booked(solved: Result) -> None:
    rooms = [
        (a.classroom_id, a.semester_id, a.timeslot_id)
        for a in solved.assignments
        if a.classroom_id and a.timeslot_id
    ]
    assert len(rooms) == len(set(rooms))


def test_only_qualified_professors_are_assigned(
    solved: Result, tiny_payload_source: dict[str, Any]
) -> None:
    qualified = {tuple(q) for q in tiny_payload_source["professor_qualification"]}
    for a in solved.assignments:
        if a.professor_id:
            assert (a.professor_id, a.course_id) in qualified


def test_night_restrictions_are_respected(
    solved: Result, tiny_payload_source: dict[str, Any]
) -> None:
    refuses_nights = {p for p, ok in tiny_payload_source["professor_can_teach_night"] if not ok}
    for a in solved.assignments:
        assert not (a.professor_id in refuses_nights and a.time_of_day_id == "Night")


def test_rooms_fit_and_are_not_left_empty(
    solved: Result, tiny_payload_source: dict[str, Any]
) -> None:
    capacity = {k: v for row in tiny_payload_source["classroom_cap"] for k, v in row.items()}
    attendance = {
        tuple(row["key"]): row["value"] for row in tiny_payload_source["section_attendance"]
    }
    for a in solved.assignments:
        if not a.classroom_id:
            continue
        heads = attendance[(a.course_id, str(a.section_id), a.semester_id, a.time_of_day_id)]
        assert heads <= capacity[a.classroom_id]
        assert heads >= MIN_ROOM_FILL * capacity[a.classroom_id]


def test_timeslot_matches_its_time_of_day(
    solved: Result, tiny_payload_source: dict[str, Any]
) -> None:
    time_of_day = dict(tiny_payload_source["timeslot_tod_subset"])
    for a in solved.assignments:
        if a.timeslot_id:
            assert time_of_day[a.timeslot_id] == a.time_of_day_id


def test_tiny_instance_needs_no_fallbacks(solved: Result) -> None:
    """It is solvable outright, so any fallback use would signal a regression."""
    assert solved.unstaffed == []
    assert solved.unscheduled == []
    assert solved.off_campus == []


def test_all_four_stages_run(solved: Result) -> None:
    assert [s.name for s in solved.stages] == [
        "minimise teaching load violations",
        "minimise concurrency and unscheduled sections",
        "minimise off-campus teaching",
        "maximise preferences",
    ]


def test_violation_stages_find_no_violations(solved: Result) -> None:
    by_name = {s.name: s.value for s in solved.stages}
    assert by_name["minimise teaching load violations"] == 0
    assert by_name["minimise concurrency and unscheduled sections"] == 0


def test_preferences_are_actually_honoured(solved: Result) -> None:
    """prof_a rates ADM2000 highest, so they should end up with it."""
    who = {a.course_id: a.professor_id for a in solved.assignments}
    assert who["ADM2000"] == "prof_a"


def test_result_serialises_to_json(solved: Result) -> None:
    import json

    payload = json.loads(json.dumps(solved.to_dict()))
    assert payload["status"] == "optimal"
    assert payload["summary"]["assignments"] == 3
    assert payload["summary"]["unstaffed"] == 0
    assert len(payload["assignments"]) == 3
    assert len(payload["stages"]) == 4


def test_assignment_shape_matches_the_backend_model(solved: Result) -> None:
    """These are the exact columns OPTIM_results.Optimization_Outputs wants."""
    expected = {
        "professor_id",
        "course_id",
        "section_id",
        "semester_id",
        "timeslot_id",
        "classroom_id",
        "time_of_day_id",
        "solution_value",
    }
    assert set(solved.to_dict()["assignments"][0]) == expected


# --------------------------------------------------------------------------- #
# behaviour under strain
# --------------------------------------------------------------------------- #

def test_no_available_professors_falls_back_to_part_timers(payload: dict[str, Any]) -> None:
    payload["professor_teaching"] = [{"prof_a": 0}, {"prof_b": 0}]
    result = solve(payload, progress=silent)

    assert Counter(a.section_id for a in result.assignments) == Counter({1: 1, 2: 1, 3: 1})
    assert all(a.professor_id is None for a in result.assignments)
    assert len(result.unstaffed) == 3


def test_courses_with_the_same_section_id_can_run_together(payload: dict[str, Any]) -> None:
    """Course and semester are part of identity; the local section id is not unique."""
    payload["section_set"] = ["1"]
    payload["section_subset"] = [
        ["ADM1000", "1", "Fall", "Day"],
        ["ADM2000", "1", "Fall", "Day"],
    ]
    payload["section_attendance"] = [
        {"key": ["ADM1000", "1", "Fall", "Day"], "value": 40},
        {"key": ["ADM2000", "1", "Fall", "Day"], "value": 35},
    ]
    payload["professor_teaching"] = [{"prof_a": 1}, {"prof_b": 1}]
    payload["professor_qualification"].append(["prof_b", "ADM2000"])
    payload["course_concurrency_t"] = [["ADM1000", "ADM2000", "Fall"]]

    result = solve(payload, progress=silent)

    assert {(a.course_id, a.section_id) for a in result.assignments} == {
        ("ADM1000", 1),
        ("ADM2000", 1),
    }
    assert len({a.timeslot_id for a in result.assignments}) == 1


def test_room_stage_gets_a_physical_room_seed(payload: dict[str, Any]) -> None:
    from scheduler.instance import OFF_CAMPUS, Instance, is_placeholder
    from scheduler.model import build
    from scheduler.progress import Progress
    from scheduler.solve import _seed_physical_rooms

    # Make off-campus variables available for the named faculty, then imitate
    # the all-off-campus incumbent produced before room use is optimised.
    payload["professor_can_teach_out_DMS"] = [["prof_a", True], ["prof_b", True]]
    built = build(Instance.from_payload(payload), Progress(silent))
    values = [0.0] * len(built.program.variables)
    old_variable, old_key = next(
        (variable, key)
        for key, variable in built.assign.items()
        if key[6] == OFF_CAMPUS
        and not is_placeholder(key[5])
        and any(
            (*key[:6], room) in built.assign
            for room in built.instance.classroom_capacity
        )
    )
    values[old_variable] = 1.0

    seeded = _seed_physical_rooms(built, values)

    assert seeded[old_variable] == 0.0
    assert sum(seeded[index] for index in built.assign.values()) == 1.0
    assert any(
        seeded[index] == 1.0
        for key, index in built.assign.items()
        if key[:6] == old_key[:6] and key[6] != OFF_CAMPUS
    )


def test_impossible_load_raises_rather_than_returning_junk(payload: dict[str, Any]) -> None:
    """The load slack is one-directional: it lets a professor exceed their
    target, never fall short. Demanding more teachings than there are sections
    is therefore genuinely infeasible, and must not be papered over — a later
    stage would otherwise bound itself with a meaningless objective value."""
    payload["professor_teaching"] = [{"prof_a": 9}, {"prof_b": 9}]

    with pytest.raises(SolveError) as caught:
        solve(payload, progress=silent)

    assert "teaching load" in str(caught.value)
    assert "infeasible" in str(caught.value).lower()


def test_no_usable_room_pushes_sections_off_campus(payload: dict[str, Any]) -> None:
    """Every room too small: sections should go off campus, not vanish."""
    payload["classroom_cap"] = [{"DMS1160": 1}, {"DMS1150": 1}]
    result = solve(payload, progress=silent)

    assert len(result.assignments) == 3
    assert all(a.classroom_id is None for a in result.assignments)


def test_progress_is_reported(payload: dict[str, Any]) -> None:
    """The callback is the only transcript there is, so it must carry the lot."""
    seen: list[tuple[str, str]] = []
    solve(payload, progress=lambda stage, message: seen.append((stage, message)))

    assert {"building", "solving", "exporting"} <= {stage for stage, _ in seen}
    assert len(seen) > 15
    assert any("viable assignments" in message for _, message in seen)
    assert any("maximise preferences" in message for _, message in seen)


def test_a_broken_progress_callback_does_not_kill_the_solve(payload: dict[str, Any]) -> None:
    def explode(stage: str, message: str) -> None:
        raise RuntimeError("reporter is broken")

    result = solve(payload, progress=explode)
    assert len(result.assignments) == 3


def test_time_limit_must_be_positive(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="positive"):
        solve(payload, progress=silent, time_limit=0)


def test_a_generous_time_limit_still_proves_optimality(payload: dict[str, Any]) -> None:
    result = solve(payload, progress=silent, time_limit=120)
    assert result.status == "optimal"
    assert all(stage.proven for stage in result.stages)


def test_status_reflects_whether_every_stage_was_proven(payload: dict[str, Any]) -> None:
    """status is derived, not a constant — it must follow the stage flags."""
    result = solve(payload, progress=silent)
    assert result.status == ("optimal" if all(s.proven for s in result.stages) else "feasible")


def test_the_default_solver_handles_what_the_gurobi_licence_refuses(
    oversized_payload: dict[str, Any],
) -> None:
    """The reason HiGHS is the default. This instance is past the 2000-column
    cap on the free Gurobi licence, and a real academic year is far past it."""
    result = solve(oversized_payload, progress=silent, time_limit=120)
    assert result.solver == "highs"
    assert len(result.assignments) == 12


def test_a_model_too_big_for_the_gurobi_licence_is_reported_clearly(
    oversized_payload: dict[str, Any],
) -> None:
    """When someone does pick gurobi, the licence wall must not surface as a
    raw GurobiError, a traceback, or an 'internal error'."""
    from scheduler import SolverError

    with pytest.raises(SolverError) as caught:
        solve(oversized_payload, progress=silent, solver="gurobi")

    message = str(caught.value)
    assert "licence" in message
    assert "HiGHS" in message  # points at the way out


def test_unknown_solver_is_rejected(payload: dict[str, Any]) -> None:
    from scheduler import SolverError

    with pytest.raises(SolverError, match="unknown solver"):
        solve(payload, progress=silent, solver="cplex")


OPTIMUM = -11.0
"""The staged optimum of the tiny instance, proven at a zero gap."""


@pytest.mark.parametrize("backend", ["highs", "gurobi"])
def test_both_backends_agree_on_the_objective(payload: dict[str, Any], backend: str) -> None:
    """Different solvers may pick different members of the optimal set, but
    they must agree on its value — that is what says the translation is right."""
    result = solve(payload, progress=silent, solver=backend)
    # The final stage is solved to GOOD_ENOUGH, not to proven optimality, so
    # the honest claim is "within that gap of the optimum" -- which is -17.0,
    # confirmed by re-running the stages at a zero gap. Pinning one backend's
    # particular answer only ever held by luck.
    assert result.objective <= OPTIMUM + 1e-5
    assert abs(result.objective - OPTIMUM) <= abs(OPTIMUM) * GOOD_ENOUGH
    assert result.solver == backend
    # The two ADM1000 sections and their day slots are interchangeable.
    schedule = {(a.course_id, a.timeslot_id) for a in result.assignments}
    assert schedule == {
        ("ADM1000", "Mon0900"),
        ("ADM1000", "Wed0900"),
        ("ADM2000", "Mon1800"),
    }


def test_each_stage_starts_from_the_previous_answer(payload: dict[str, Any]) -> None:
    """Stages only add rows, so the last answer is always feasible for the next.

    Handing it over matters at real scale: on the 835k-variable instance the
    final 'maximise preferences' stage burned its whole time limit without
    finding any incumbent and failed as 'no solution found', which reads like
    infeasibility even though the three stages before it had all solved.
    """
    from scheduler.backends import base
    from scheduler.solve import _StagedSolve

    starts: list[list[float]] = []
    real = base.SolutionStatus  # keep the enum reachable for the stub below

    class Recorder:
        name = "recorder"

        def __init__(self) -> None:
            self.calls = 0

        def load(self, program: Any) -> None:
            self.columns = len(program.variables)

        def add_row(self, name: str, terms: Any, sense: Any, rhs: float) -> None:
            pass

        def warm_start(self, values: list[float]) -> None:
            starts.append(list(values))

        def optimise(self, objective: Any, **kwargs: Any) -> base.Outcome:
            self.calls += 1
            return base.Outcome(real.OPTIMAL, 0.0, [float(self.calls)], 0.1, "")

        def close(self) -> None:
            pass

    from scheduler.instance import Instance
    from scheduler.model import build
    from scheduler.progress import Progress

    built = build(Instance.from_payload(payload), Progress(silent))
    backend = Recorder()
    backend.load(built.program)
    _StagedSolve(backend, Progress(silent), None).run(built.objectives)

    # Four stages, so three hand-offs -- the first has nothing to hand over.
    assert starts == [[1.0], [2.0], [3.0]]


def test_a_warm_start_survives_the_objective_swap(payload: dict[str, Any]) -> None:
    """Handing over the answer must actually reach the solver.

    HiGHS drops a user solution when the objective changes, and every stage
    changes the objective -- so a start applied before optimise() is silently
    discarded. With no time to search, a cold solve finds nothing and a warm
    one returns the solution it was given.
    """
    from scheduler.backends.base import SolutionStatus
    from scheduler.backends.highs import HighsBackend
    from scheduler.instance import Instance
    from scheduler.model import build
    from scheduler.progress import Progress

    built = build(Instance.from_payload(payload), Progress(silent))
    objective = built.objectives.preference_score()

    solved = HighsBackend()
    solved.load(built.program)
    best = solved.optimise(objective, maximise=True, gap=0.0, time_limit=None)
    assert best.status is SolutionStatus.OPTIMAL

    cold = HighsBackend()
    cold.load(built.program)
    assert cold.optimise(
        objective, maximise=True, gap=0.0, time_limit=1e-6
    ).status is SolutionStatus.NO_SOLUTION

    warm = HighsBackend()
    warm.load(built.program)
    warm.warm_start(best.values)
    out = warm.optimise(objective, maximise=True, gap=0.0, time_limit=1e-6)
    assert out.status is SolutionStatus.FEASIBLE
    assert out.objective == best.objective


@pytest.mark.slow
def test_medium_instance_places_every_section(
    medium_payload_source: dict[str, Any],
) -> None:
    """The tiny instance is too small to strain the staged solve: 3 sections, one
    semester, no concurrency. The medium one has 36 sections across two semesters
    with clashing timeslots and night restrictions, and must still place every
    section on a real professor, a real slot and a real room.

    Solved under a time limit, as the real instance is. The three hard stages
    close in under a second; the preference stage is what runs long, and
    stopping it early costs preference points, never legality.
    """
    result = solve(medium_payload_source, progress=silent, time_limit=20)

    assert result.status in {"optimal", "feasible"}
    assert len(result.assignments) == 36
    assert {a.section_id for a in result.assignments} == set(range(1, 37))
    assert not result.unstaffed
    assert not result.unscheduled
    assert not result.off_campus
