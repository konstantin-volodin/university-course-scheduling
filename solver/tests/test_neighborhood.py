"""Neighborhoods improve schedules without weakening the full model or stage caps."""

from itertools import product
from typing import Any

import pytest

from scheduler import silent
from scheduler.config import Instance
from scheduler.errors import SolveError
from scheduler.model import BuiltModel, build
from scheduler.model.program import LinearExpr, Program, Row, Sense, VarKind
from scheduler.progress import Progress
from scheduler.solve.neighborhood import NeighborhoodSearch, _satisfied, project
from scheduler.solve.result import Assignment
from scheduler.solve.solver import _extract, _schedule_seed
from scheduler.solve.warm_start import validate_initial_assignments


def room_fixture(payload: dict[str, Any]) -> tuple[BuiltModel, list[float], list[Row]]:
    payload["classroom_set"] = ["DMS1150"]
    payload["classroom_cap"] = [{"DMS1150": 40}]
    payload["section_subset"][1][0] = "ADM2000"
    payload["section_attendance"][1]["key"][0] = "ADM2000"
    payload["professor_qualification"].append(["prof_b", "ADM2000"])
    built = build(Instance.from_payload(payload), Progress(silent))
    assignments = [
        Assignment("prof_a", "ADM1000", "1", "Fall", "Mon0900", None, "Day", 1),
        Assignment("prof_b", "ADM2000", "2", "Fall", "Mon0900", "DMS1150", "Day", 1),
        Assignment("prof_a", "ADM2000", "3", "Fall", "Mon1800", "DMS1150", "Night", 1),
    ]
    validate_initial_assignments(built.instance, assignments)
    values = _schedule_seed(built, assignments)
    rows = [*built.program.core_rows,
            Row("load_cap", built.objectives.teaching_load.terms, Sense.LE, 0),
            Row("timetable_cap",
                (built.objectives.concurrency + built.objectives.placeholder_use).terms,
                Sense.LE, 0)]
    return built, values, rows


def test_neighborhood_moves_timeslots_to_recover_a_room(payload: dict[str, Any]) -> None:
    built, values, rows = room_fixture(payload)
    original = list(values)
    candidate = NeighborhoodSearch(built, "highs", Progress(silent)).improve(
        values, rows, built.objectives.off_campus_use, maximise=False, time_limit=2,
    )
    assignments = _extract(built, candidate)
    validate_initial_assignments(built.instance, assignments)
    assert all(assignment.classroom_id is not None for assignment in assignments)
    assert any(assignment.timeslot_id == "Wed0900" for assignment in assignments)
    assert {(a.course_id, a.section_id, a.professor_id) for a in assignments} == {
        (a.course_id, a.section_id, a.professor_id) for a in _extract(built, original)
    }
    assert values == original
    assert all(_satisfied(row, sum(c * candidate[i] for i, c in row.terms.items())) for row in rows)


def test_neighborhood_cannot_buy_a_room_by_breaking_an_earlier_cap(payload: dict[str, Any]) -> None:
    built, values, rows = room_fixture(payload)
    rows.append(Row("earlier_day_cap", {
        column: 1.0 for key, column in built.assign.items() if key.timeslot == "Wed0900"
    }, Sense.LE, 0))
    candidate = NeighborhoodSearch(built, "highs", Progress(silent)).improve(
        values, rows, built.objectives.off_campus_use, maximise=False, time_limit=2,
    )
    assert candidate is values


def test_projection_preserves_equalities_inequalities_and_fixed_contributions() -> None:
    program = Program()
    x = program.add_variable("x", upper=1, kind=VarKind.BINARY)
    y = program.add_variable("fixed", upper=1, kind=VarKind.BINARY)
    z = program.add_variable("z", lower=-2, upper=3, kind=VarKind.INTEGER)
    program.add_row("minimum", {x: 1, y: 1}, Sense.GE, 1)
    program.add_row("equality", {x: 1, y: -1, z: 1}, Sense.EQ, 1)
    program.add_row("cap", {y: 2, z: 1}, Sense.LE, 4)
    objective = LinearExpr({x: -1, y: 4, z: 2})
    projected = project(program, program.rows, objective, [0, 1, 2], {x, z})
    for x_value, z_value in product(range(2), range(-2, 4)):
        full = [x_value, 1, z_value]
        local = [x_value, z_value]
        feasible = all(_satisfied(row, sum(c * full[i] for i, c in row.terms.items()))
                       for row in program.rows)
        assert feasible == all(
            _satisfied(row, sum(c * local[i] for i, c in row.terms.items()))
            for row in projected.program.rows
        )
        assert sum(c * full[i] for i, c in objective.terms.items()) == 4 + sum(
            c * local[i] for i, c in projected.objective.terms.items()
        )


def test_projection_rejects_infeasible_fixed_incumbent() -> None:
    program = Program()
    x = program.add_variable("fixed", upper=1)
    program.add_row("required", {x: 1}, Sense.EQ, 1)
    with pytest.raises(SolveError, match="fixed incumbent violates required"):
        project(program, program.rows, LinearExpr(), [0], set())


@pytest.mark.parametrize("budget", [0.0, -1.0, float("nan"), float("inf")])
def test_neighborhood_without_usable_budget_retains_incumbent(
    payload: dict[str, Any], budget: float,
) -> None:
    built, values, rows = room_fixture(payload)
    assert NeighborhoodSearch(built, "highs", Progress(silent)).improve(
        values, rows, built.objectives.off_campus_use, maximise=False, time_limit=budget,
    ) is values
