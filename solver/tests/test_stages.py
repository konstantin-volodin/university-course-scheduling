"""Regression checks for lexicographic priorities and feasible stage handoffs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import fields, replace
from typing import Any

import pytest

from scheduler import silent
from scheduler.backends.base import Outcome
from scheduler.backends.highs import HighsBackend
from scheduler.config import Instance
from scheduler.model import Objectives, build
from scheduler.model.program import LinearExpr, Program, Row, Sense, VarKind
from scheduler.progress import Progress
from scheduler.solve import solver as solver_module
from scheduler.solve.solver import EXACT, GOOD_ENOUGH, _repair, _StagedSolve


def test_repaired_room_hint_cannot_make_the_model_infeasible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = Program()
    room_changes = program.add_variable("room_changes", lower=1, upper=2)
    program.add_row(
        "room_definition", {room_changes: 1}, Sense.GE, 1,
        deferred=True, defines=room_changes,
    )
    objectives = Objectives(**{field.name: LinearExpr() for field in fields(Objectives)})
    objectives = replace(objectives, room_changes=LinearExpr({room_changes: 1}))

    def bad_room_hint(
        program: Program, values: list[float], rows: Sequence[Row],
        *, reset_prefixes: tuple[str, ...] = (),
    ) -> list[float]:
        if reset_prefixes:
            # An optimistic but infeasible hint must not become a hard ceiling.
            return [0.0]
        return _repair(program, values, rows)

    monkeypatch.setattr(solver_module, "_repair", bad_room_hint)
    backend = HighsBackend()
    try:
        backend.load(program)
        staged = _StagedSolve(backend, Progress(silent), 5, program)
        staged.run(objectives, deferred=program.deferred_rows)
        assert staged.values[room_changes] == pytest.approx(1)
        assert_feasible(program, program.rows, staged.values)
    finally:
        backend.close()


def assert_feasible(program: Program, rows: Sequence[Row], values: list[float]) -> None:
    assert len(values) == len(program.variables)
    for variable, value in zip(program.variables, values, strict=True):
        assert variable.lower - 1e-6 <= value <= variable.upper + 1e-6, variable.name
        if variable.kind is not VarKind.CONTINUOUS:
            assert value == pytest.approx(round(value), abs=1e-6), variable.name
    for row in rows:
        lhs = sum(coefficient * values[index] for index, coefficient in row.terms.items())
        if row.sense is Sense.LE:
            assert lhs <= row.rhs + 1e-6, row.name
        elif row.sense is Sense.GE:
            assert lhs >= row.rhs - 1e-6, row.name
        else:
            assert lhs == pytest.approx(row.rhs, abs=1e-6), row.name


class CheckedHighs(HighsBackend):
    """Use the actual solver while checking every incumbent against active rows."""

    def __init__(self, program: Program) -> None:
        super().__init__()
        self.program = program
        self.rows: list[Row] = []
        self.calls: list[tuple[dict[int, float], bool, float, float | None]] = []
        self.starts = 0
        self.deferred_after: list[int] = []
        self.load(program)

    def add_rows(self, rows: Sequence[Row]) -> None:
        if any(row.deferred for row in rows):
            self.deferred_after.append(len(self.calls))
        self.rows.extend(rows)
        super().add_rows(rows)

    def warm_start(self, values: list[float]) -> None:
        assert_feasible(self.program, self.rows, values)
        self.starts += 1
        super().warm_start(values)

    def optimise(
        self, objective: LinearExpr, *, maximise: bool, gap: float, time_limit: float | None
    ) -> Outcome:
        self.calls.append((dict(objective.terms), maximise, gap, time_limit))
        outcome = super().optimise(objective, maximise=maximise, gap=gap, time_limit=time_limit)
        assert outcome.usable, outcome.detail
        assert_feasible(self.program, self.rows, outcome.values)
        return outcome


def test_stages_preserve_priorities_and_pass_feasible_warm_starts(payload: dict[str, Any]) -> None:
    built = build(Instance.from_payload(payload), Progress(silent))
    objective = built.objectives
    backend = CheckedHighs(built.program)
    try:
        staged = _StagedSolve(backend, Progress(silent), 5.0, built.program)
        staged.run(objective, deferred=built.program.deferred_rows)

        expected = [
            (objective.teaching_load, EXACT),
            (objective.concurrency + objective.placeholder_use, EXACT),
            (objective.off_campus_use, GOOD_ENOUGH),
            (objective.part_timer_room_use, EXACT),
            (objective.time_of_day_spread + objective.day_of_week_spread, EXACT),
            (objective.block_violation, EXACT),
            (objective.friday_night, EXACT),
            (objective.room_changes, GOOD_ENOUGH),
            (objective.pack_day_penalty, EXACT),
            (objective.remaining_preference_score(), GOOD_ENOUGH),
        ]
        assert backend.calls == [
            (expression.terms, index == 9, gap, 5.0)
            for index, (expression, gap) in enumerate(expected)
        ]
        assert backend.starts == 9
        assert backend.deferred_after == [4]
        assert len(staged.stages) == 10
        for stage, (expression, _) in zip(staged.stages[:-1], expected, strict=False):
            final_value = sum(c * staged.values[i] for i, c in expression.terms.items())
            assert final_value <= stage.value + 1e-6, stage.name
    finally:
        backend.close()


@pytest.mark.parametrize(
    ("sense", "coefficient", "rhs", "initial", "expected"),
    [
        (Sense.LE, 2.0, 5.0, 8.0, 2.0),
        (Sense.GE, 2.0, 5.0, 0.0, 3.0),
        (Sense.LE, -2.0, -5.0, 0.0, 3.0),
        (Sense.GE, -2.0, -5.0, 8.0, 2.0),
        (Sense.EQ, -2.0, -6.0, 0.0, 3.0),
    ],
)
def test_repair_respects_integer_rounding_and_coefficient_sign(
    sense: Sense, coefficient: float, rhs: float, initial: float, expected: float
) -> None:
    program = Program()
    target = program.add_variable("auxiliary", upper=10, kind=VarKind.INTEGER)
    program.add_row("definition", {target: coefficient}, sense, rhs, defines=target)
    original = [initial]

    repaired = _repair(program, original, program.rows)

    assert repaired == [expected]
    assert original == [initial]
    assert_feasible(program, program.rows, repaired)


def test_repair_resets_stale_room_indicators_before_dependent_counts() -> None:
    program = Program()
    assignment = program.add_variable("assign[one]", upper=1, kind=VarKind.BINARY)
    used = program.add_variable("uses_room[one]", upper=1, kind=VarKind.BINARY)
    count = program.add_variable("room_count", upper=1, kind=VarKind.INTEGER)
    program.add_row("used", {used: 1, assignment: -1}, Sense.GE, 0, defines=used)
    program.add_row("count", {count: 1, used: -1}, Sense.EQ, 0, defines=count)

    repaired = _repair(program, [0, 1, 1], program.rows, reset_prefixes=("uses_room[",))

    assert repaired == [0, 0, 0]
    assert_feasible(program, program.rows, repaired)


def test_fractional_stage_cap_preserves_attained_value() -> None:
    program = Program()
    variable = program.add_variable("fractional_cost", lower=0.5, upper=1.0)
    objective = LinearExpr({variable: 1.0})
    backend = HighsBackend()
    try:
        backend.load(program)
        staged = _StagedSolve(backend, Progress(silent), 5, program)
        staged._minimise_then_cap("balance", objective, EXACT, integral=False)
        staged._optimise("reward", objective, maximise=True, gap=EXACT)
        assert staged.values[variable] == pytest.approx(0.5, abs=2e-6)
    finally:
        backend.close()
