"""Regression checks for lexicographic priorities and feasible stage handoffs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import fields, replace
from types import SimpleNamespace
from typing import Any

import pytest

from scheduler import silent
from scheduler.backends import highs
from scheduler.backends.base import Outcome, finite_or_none
from scheduler.backends.highs import HighsBackend
from scheduler.config import Instance
from scheduler.model import Objectives, build
from scheduler.model.program import LinearExpr, Program, Row, Sense, VarKind
from scheduler.progress import Progress
from scheduler.solve import solver
from scheduler.solve.solver import (
    EXACT,
    STAGES,
    StageSpec,
    _repair,
    _StagedSolve,
)


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

    monkeypatch.setattr(solver, "_repair", bad_room_hint)
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


@pytest.mark.parametrize(
    ("limit", "warm", "threshold", "presolve"),
    [(30.0, True, 1, "off"), (31.0, True, 1, "choose"),
     (None, True, 1, "choose"), (30.0, False, 1, "choose"),
     (30.0, True, 2, "choose")],
)
def test_short_search_presolve_policy_preserves_solution(
    monkeypatch: pytest.MonkeyPatch, limit: float | None, warm: bool,
    threshold: int, presolve: str,
) -> None:
    monkeypatch.setattr(highs, "_SHORT_SEARCH_COLUMNS", threshold)
    program = Program()
    variable = program.add_variable("required", upper=1, kind=VarKind.BINARY)
    program.add_row("cover", {variable: 1}, Sense.EQ, 1)
    backend = HighsBackend()
    try:
        backend.load(program)
        if warm:
            backend.warm_start([1])
        outcome = backend.optimise(
            LinearExpr({variable: 1}), maximise=False, gap=0, time_limit=limit,
        )
        assert outcome.usable and outcome.objective == 1
        assert_feasible(program, program.rows, outcome.values)
        assert backend._highs.getOptionValue("presolve")[1] == presolve
        # A later long search must restore normal preprocessing.
        backend.optimise(LinearExpr({variable: 1}), maximise=False, gap=0, time_limit=60)
        assert backend._highs.getOptionValue("presolve")[1] == "choose"
    finally:
        backend.close()


@pytest.mark.parametrize("setup_seconds", [2.0, 35.0])
def test_short_search_charges_setup_and_reserves_completion_time(
    monkeypatch: pytest.MonkeyPatch, setup_seconds: float,
) -> None:
    monkeypatch.setattr(highs, "_SHORT_SEARCH_COLUMNS", 1)
    clock = iter([100.0, 100.0 + setup_seconds, 101.0 + setup_seconds])
    monkeypatch.setattr(highs, "time", SimpleNamespace(perf_counter=lambda: next(clock)))
    program = Program()
    variable = program.add_variable("required", lower=1, upper=1, kind=VarKind.BINARY)
    backend = HighsBackend()
    try:
        backend.load(program)
        backend.warm_start([1])
        outcome = backend.optimise(
            LinearExpr({variable: 1}), maximise=False, gap=0, time_limit=30,
        )
        assert backend._highs.getOptionValue("time_limit")[1] == max(0, 24 - setup_seconds)
        assert outcome.seconds == setup_seconds + 1
        assert outcome.usable and outcome.objective == 1
    finally:
        backend.close()


@pytest.mark.parametrize("maximise", [False, True])
def test_highs_reports_full_model_bound_and_gap(maximise: bool) -> None:
    program = Program()
    x = program.add_variable("x", upper=4, kind=VarKind.INTEGER)
    program.add_row("required", {x: 1}, Sense.GE, 1)
    backend = HighsBackend()
    try:
        backend.load(program)
        outcome = backend.optimise(LinearExpr({x: 1}), maximise=maximise, gap=0, time_limit=5)
        assert outcome.objective == (4 if maximise else 1)
        assert outcome.best_bound == outcome.objective
        assert outcome.relative_gap == 0
    finally:
        backend.close()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 1e100, -1e100])
def test_unavailable_bounds_are_not_exported_as_numbers(value: float) -> None:
    assert finite_or_none(value, 1e100) is None


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

        expected = [(spec, spec.objective(objective)) for spec in STAGES]
        assert backend.calls == [
            (expression.terms, spec.maximise, EXACT, 5.0)
            for index, (spec, expression) in enumerate(expected)
            if staged.stages[index].optimality_source == "backend"
        ]
        assert backend.starts == len(backend.calls) - 1
        assert backend.deferred_after == [
            sum(stage.optimality_source == "backend" for stage in staged.stages[:6])
        ]
        assert len(staged.stages) == len(STAGES)
        for stage, (_, expression) in zip(staged.stages[:-1], expected, strict=False):
            final_value = sum(c * staged.values[i] for i, c in expression.terms.items())
            assert final_value <= stage.value + 1e-6, stage.name
    finally:
        backend.close()


@pytest.mark.parametrize(
    ("lower", "coefficient", "initial", "skipped"),
    [(0.0, 1.0, 0.0, True), (0.0, 1.0, 1.0, False),
     (0.0, 1.0, 1e-8, False), (-1.0, 1.0, 0.0, False),
     (0.0, -1.0, 0.0, False)],
)
def test_lower_bound_shortcut_requires_an_attained_global_bound(
    lower: float, coefficient: float, initial: float, skipped: bool,
) -> None:
    program = Program()
    variable = program.add_variable("decision", lower=lower, upper=1.0)
    backend = CheckedHighs(program)
    try:
        staged = _StagedSolve(backend, Progress(silent), 5.0, program)
        staged.values = [initial]
        first_objective = LinearExpr({variable: coefficient})
        first_spec = StageSpec("first", "first", "", lambda _: first_objective)
        staged._minimise_then_cap(first_spec, first_objective)
        first = staged.stages[0]
        assert (first.optimality_source == "lower_bound") is skipped
        assert len(backend.calls) == (0 if skipped else 1)
        assert first.proven
        # Even a skipped stage must constrain a later competing objective.
        competing = LinearExpr({variable: -coefficient})
        staged._optimise(StageSpec("competing", "competing", "", lambda _: competing), competing)
        assert coefficient * staged.values[variable] <= first.value + 1e-6
        assert_feasible(program, backend.rows, staged.values)
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
        staged._minimise_then_cap(
            StageSpec("balance", "balance", "", lambda _: objective, integral=False), objective
        )
        staged._optimise(
            StageSpec("reward", "reward", "", lambda _: objective, maximise=True), objective
        )
        assert staged.values[variable] == pytest.approx(0.5, abs=2e-6)
    finally:
        backend.close()
