"""Structural checks on the program, before any solver sees it.

Because the model is now plain data, these need no solver at all — they read
the variables and rows directly. The model is built over indexes, so it is easy
to emit rows and columns for combinations nothing can reach: harmless to the
answer, expensive for everything else.
"""

from __future__ import annotations

from typing import Any

import pytest

from scheduler.instance import PART_TIMER, Instance
from scheduler.model import build
from scheduler.program import Program, Sense, VarKind
from scheduler.progress import Progress, silent


@pytest.fixture
def program(payload: dict[str, Any]) -> Program:
    return build(Instance.from_payload(payload), Progress(silent)).program


def test_no_empty_rows(program: Program) -> None:
    """An empty row is vacuous. One means a block is being emitted over more
    keys than any assignment can reach."""
    assert [row.name for row in program.rows if not row.terms] == []


def test_every_variable_is_used_by_a_row(program: Program) -> None:
    """A column no row touches is a column that should not exist."""
    used = {index for row in program.rows for index in row.terms}
    orphans = [v.name for i, v in enumerate(program.variables) if i not in used]
    assert orphans == []


def test_nothing_is_built_for_the_part_timer_fallback(program: Program) -> None:
    """The part-timer has no load to meet and no day to pack."""
    leaked = [
        v.name
        for v in program.variables
        if PART_TIMER in v.name
        and any(tag in v.name for tag in ("teaches_day", "teaching_load_violation"))
    ]
    assert leaked == []


def test_assignment_variables_are_integral(program: Program) -> None:
    assign = [v for v in program.variables if v.name.startswith("assign[")]
    assert assign
    assert all(v.kind is VarKind.INTEGER for v in assign)


def test_only_real_assignments_are_capped_at_one(program: Program) -> None:
    """A fallback is a counter, not a switch: many sections can pile onto it."""
    for variable in program.variables:
        if not variable.name.startswith("assign["):
            continue
        fallback = (
            PART_TIMER in variable.name
            or "placeholder_" in variable.name
            or variable.name.endswith(",other]")
        )
        if fallback:
            assert variable.upper == float("inf"), variable.name
        else:
            assert variable.upper == 1.0, variable.name


def test_every_section_gets_an_equality_row(program: Program) -> None:
    rows = [r for r in program.rows if r.name.startswith("section_taught_once[")]
    assert len(rows) == 3
    assert all(r.sense is Sense.EQ and r.rhs == 1.0 for r in rows)


def test_balance_rows_cover_every_calendar_day(program: Program) -> None:
    minimums = [r for r in program.rows if r.name.startswith("day_of_week_min[")]
    assert len(minimums) == 2  # Mon and Wed; one semester
    assert {row.name for row in minimums} == {
        "day_of_week_min[Fall,Mon]",
        "day_of_week_min[Fall,Wed]",
    }


def test_teaching_load_rows_carry_the_right_hand_side(
    program: Program, payload: dict[str, Any]
) -> None:
    loads = {k: v for row in payload["professor_teaching"] for k, v in row.items()}
    for professor, expected in loads.items():
        row = next(r for r in program.rows if r.name == f"professor_teaching_load[{professor}]")
        assert row.rhs == expected
        assert row.sense is Sense.EQ


def test_program_is_deterministic(payload: dict[str, Any]) -> None:
    """Same instance, same program — down to row order, which decides the
    solver's search path and therefore which optimum comes back."""
    first = build(Instance.from_payload(payload), Progress(silent)).program
    second = build(Instance.from_payload(payload), Progress(silent)).program

    assert [v.name for v in first.variables] == [v.name for v in second.variables]
    assert [(r.name, sorted(r.terms.items()), r.sense, r.rhs) for r in first.rows] == [
        (r.name, sorted(r.terms.items()), r.sense, r.rhs) for r in second.rows
    ]


def test_model_stays_within_the_free_gurobi_licence(program: Program) -> None:
    """The example must keep fitting pip's size-limited gurobipy, so the
    optional backend stays testable."""
    assert len(program.variables) <= 2000
    assert len(program.rows) <= 2000


def test_pack_day_penalty_weights_every_day_the_same(payload: dict[str, Any]) -> None:
    """A day spent teaching costs the professor's own preference, full stop.

    The tiny instance gives Mon two slots and Wed one. The original
    formulation multiplied the penalty by that count, so the identical spread
    cost twice as much on Mon as on Wed. Resolved 2026-08-26: equal weight.
    """
    built = build(Instance.from_payload(payload), Progress(silent))
    names = [v.name for v in built.program.variables]
    weights: dict[str, dict[str, float]] = {}
    for index, coefficient in built.objectives.pack_day_penalty.terms.items():
        professor, _, day = names[index].removeprefix("teaches_day[")[:-1].split(",")
        weights.setdefault(professor, {})[day] = coefficient

    assert weights, "no pack-day terms were emitted"
    for professor, by_day in weights.items():
        assert {"Mon", "Wed"} <= set(by_day), by_day
        assert len(set(by_day.values())) == 1, f"{professor} is charged by day: {by_day}"
