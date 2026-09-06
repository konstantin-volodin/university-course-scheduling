"""Structural checks on the program, before any solver sees it.

Because the model is now plain data, these need no solver at all — they read
the variables and rows directly. The model is built over indexes, so it is easy
to emit rows and columns for combinations nothing can reach: harmless to the
answer, expensive for everything else.
"""

from __future__ import annotations

from typing import Any

import pytest

from scheduler.config.instance import PART_TIMER, Instance
from scheduler.model import build
from scheduler.model.builder import _maximal_slot_cliques
from scheduler.model.program import Program, Sense, VarKind
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


def test_assignment_bounds_follow_section_equalities(program: Program) -> None:
    """Fallbacks can be shared, but each variable belongs to exactly one section."""
    section_rows = [row for row in program.rows if row.name.startswith("section_taught_once[")]
    assert len(section_rows) == 3
    for index, variable in enumerate(program.variables):
        if not variable.name.startswith("assign["):
            continue
        assert variable.kind is VarKind.BINARY, variable.name
        assert variable.lower == 0.0 and variable.upper == 1.0, variable.name
        owners = [row for row in section_rows if index in row.terms]
        assert len(owners) == 1
        row = owners[0]
        assert row.sense is Sense.EQ and row.rhs == 1.0
        assert all(coefficient == 1.0 for coefficient in row.terms.values())


def test_section_identity_includes_its_course(payload: dict[str, Any]) -> None:
    """Section ids are commonly reused as 1, 2, ... within each course."""
    adm2000 = next(section for section in payload["section_subset"] if section[0] == "ADM2000")
    adm2000[1] = "1"
    attendance = next(
        row for row in payload["section_attendance"] if row["key"][0] == "ADM2000"
    )
    attendance["key"][1] = "1"
    payload["section_set"] = ["1", "2"]

    built = build(Instance.from_payload(payload), Progress(silent))
    rows = [
        row for row in built.program.rows if row.name.startswith("section_taught_once[")
    ]

    assert len(rows) == 3
    assert {row.name for row in rows} == {
        "section_taught_once[ADM1000,1,Fall,Day]",
        "section_taught_once[ADM1000,2,Fall,Day]",
        "section_taught_once[ADM2000,1,Fall,Night]",
    }


def test_course_block_penalty_only_marks_non_preferred_slots(payload: dict[str, Any]) -> None:
    built = build(Instance.from_payload(payload), Progress(silent))
    penalised = {
        key
        for key, variable in built.assign.items()
        if variable in built.objectives.block_violation.terms
    }

    assert penalised
    assert all(key.course == "ADM1000" for key in penalised)
    assert all(key.timeslot.startswith("placeholder_") for key in penalised)


def test_balance_rows_cover_every_calendar_day(program: Program) -> None:
    minimums = [r for r in program.rows if r.name.startswith("day_of_week_min[")]
    assert len(minimums) == 2  # Mon and Wed; one semester
    assert {row.name for row in minimums} == {
        "day_of_week_min[Fall,Mon]",
        "day_of_week_min[Fall,Wed]",
    }


def test_overlap_rows_cover_different_sections(payload: dict[str, Any]) -> None:
    payload["timeslot_concurrency"] = [["Mon0900", "Wed0900"]]
    built = build(Instance.from_payload(payload), Progress(silent))

    row = next(
        row
        for row in built.program.rows
        if row.name == "professor_no_overlap[prof_a,Fall,Mon0900,Wed0900]"
    )
    assignments = {
        key for key, variable in built.assign.items() if variable in row.terms
    }

    assert {key.section for key in assignments if key.course == "ADM1000"} == {"1", "2"}
    assert {key.timeslot for key in assignments} == {"Mon0900", "Wed0900"}

    room_row = next(
        row
        for row in built.program.rows
        if row.name == "classroom_no_overlap[DMS1150,Fall,Mon0900,Wed0900]"
    )
    room_assignments = {
        key for key, variable in built.assign.items() if variable in room_row.terms
    }
    assert {key.section for key in room_assignments if key.course == "ADM1000"} == {"1", "2"}


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


def test_uses_room_indicators_are_binary_and_forced(program: Program) -> None:
    indicators = [v for v in program.variables if v.name.startswith("uses_room[")]
    assert indicators
    assert all(v.kind is VarKind.BINARY for v in indicators)
    forcing = [row for row in program.rows if row.name.startswith("professor_uses_room[")]
    assert len(forcing) == len(indicators)
    for row in forcing:
        assert row.sense is Sense.LE
        assert min(row.terms.values()) <= -1.0


def test_indicator_bounds_use_professor_slot_capacity(payload: dict[str, Any]) -> None:
    built = build(Instance.from_payload(payload), Progress(silent))
    assignments = {variable: key for key, variable in built.assign.items()}
    tightened = False
    for row in built.program.deferred_rows:
        if not row.name.startswith(("professor_teaches_day[", "professor_uses_room[")):
            continue
        keys = [assignments[index] for index in row.terms if index in assignments]
        slots = {key.timeslot for key in keys}
        sections = {(key.course, key.section, key.semester, key.time_of_day) for key in keys}
        assert row.defines is not None
        assert -row.terms[row.defines] == min(len(slots), len(sections))
        tightened |= len(slots) < len(sections)
    assert tightened, "fixture must exercise an improvement over section-count bounds"


@pytest.mark.parametrize("self_overlaps", [False, True])
def test_program_periods_do_not_merge_non_overlapping_slots(self_overlaps: bool) -> None:
    """A-B and B-C overlap does not imply that A and C overlap."""
    overlaps = {
        "A": [("A", "B")],
        "B": [("A", "B"), ("B", "C")],
        "C": [("B", "C")],
    }
    if self_overlaps:
        for slot in overlaps:
            overlaps[slot].append((slot, slot))
    assert _maximal_slot_cliques(["A", "B", "C"], overlaps) == [
        ("A", "B"),
        ("B", "C"),
    ]


def test_professor_and_room_cliques_exclude_fractional_overlap_triangles(
    payload: dict[str, Any],
) -> None:
    slots = ["Mon0900", "Wed0900", "Mon1800"]
    payload["timeslot_concurrency"] = [
        [slots[0], slots[1]], [slots[0], slots[2]], [slots[1], slots[2]],
    ]
    built = build(Instance.from_payload(payload), Progress(silent))
    chosen = [next(column for key, column in built.assign.items()
                   if key.professor == "prof_a" and key.classroom == "DMS1150"
                   and key.timeslot == slot) for slot in slots]
    for prefix in ("professor_no_overlap[prof_a,Fall,", "classroom_no_overlap[DMS1150,Fall,"):
        rows = [row for row in built.program.rows if row.name.startswith(prefix)]
        assert len(rows) == 1
        row = rows[0]
        assert all(column in row.terms for column in chosen)
        assert sum(row.terms[column] * 0.5 for column in chosen) > row.rhs
        assert all(row.terms[column] <= row.rhs for column in chosen)
