"""Bounded timetable/room neighborhoods projected from the authoritative model.

One semester can move at a time, with section ownership held fixed. Every
active row, including earlier objective caps, survives substitution. Restricted
optimality is never exported as a bound or proof for the full model.
"""

from __future__ import annotations

import math
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace

from ..backends import open_backend
from ..config import OFF_CAMPUS, SectionKey
from ..errors import SolveError
from ..model import AssignmentKey, BuiltModel
from ..model.program import LinearExpr, Program, Row, Sense, VarKind
from ..progress import Progress
from .warm_start import validate_initial_assignments


def _section(key: AssignmentKey) -> SectionKey:
    return key.course, key.section, key.semester, key.time_of_day


def _satisfied(row: Row, lhs: float) -> bool:
    if row.sense is Sense.LE:
        return lhs <= row.rhs + 1e-6
    if row.sense is Sense.GE:
        return lhs >= row.rhs - 1e-6
    return abs(lhs - row.rhs) <= 1e-6


@dataclass(frozen=True, slots=True)
class Projection:
    program: Program
    columns: list[int]
    objective: LinearExpr
    initial: list[float]


def project(
    program: Program, rows: Sequence[Row], objective: LinearExpr,
    values: list[float], free: set[int],
) -> Projection:
    """Substitute fixed columns into every row; remap the remaining columns."""
    columns = sorted(free)
    local = {column: index for index, column in enumerate(columns)}
    reduced = Program(variables=[program.variables[column] for column in columns])
    for row in rows:
        rhs = row.rhs
        terms: dict[int, float] = {}
        for column, coefficient in row.terms.items():
            index = local.get(column)
            if index is not None:
                terms[index] = coefficient
            elif values[column]:
                rhs -= coefficient * values[column]
        if terms:
            reduced.rows.append(Row(row.name, terms, row.sense, rhs))
        elif not _satisfied(replace(row, rhs=rhs), 0.0):
            raise SolveError("neighborhood", f"fixed incumbent violates {row.name}")
    return Projection(
        reduced, columns,
        LinearExpr({local[i]: c for i, c in objective.terms.items() if i in local}),
        [values[column] for column in columns],
    )


class NeighborhoodSearch:
    """Search each semester within a shared wall-time allowance."""

    def __init__(self, built: BuiltModel, solver: str, progress: Progress) -> None:
        self.built = built
        self.solver = solver
        self.progress = progress
        self.assignment_columns = set(built.assign.values())

    def improve(
        self, values: list[float], rows: Sequence[Row], objective: LinearExpr,
        *, maximise: bool, time_limit: float,
    ) -> list[float]:
        """Return only strictly better, fully feasible points; retain the seed on timeout.

        Projection, loading and candidate validation share the same allowance
        as neighborhood search. A native backend may still overrun its limit.
        """
        if not math.isfinite(time_limit) or time_limit <= 0:
            return values
        deadline = time.perf_counter() + time_limit
        built = self.built
        owners = {
            _section(key): key.professor for key, column in built.assign.items()
            if values[column] > 0.5
        }
        if len(owners) != len(built.instance.section_keys):
            return values
        # Start with the semesters carrying the most room fallbacks. Stable
        # ordering matters when a short budget reaches only one neighborhood.
        off_campus = Counter(
            key.semester for key, column in built.assign.items()
            if values[column] > 0.5 and key.classroom == OFF_CAMPUS
        )
        semesters = sorted(built.instance.semesters, key=lambda s: (-off_campus[s], s))
        auxiliaries = {
            column for row in rows for column in row.terms
            if column not in self.assignment_columns
        } | (objective.terms.keys() - self.assignment_columns)
        best = values
        for position, semester in enumerate(semesters):
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            free = auxiliaries | {
                column for key, column in built.assign.items()
                if key.semester == semester and key.professor == owners[_section(key)]
            }
            # A full-sized projection adds overhead without providing a
            # smaller search; the authoritative backend can handle it directly.
            if len(free) >= len(built.program.variables):
                continue
            projected = project(built.program, rows, objective, best, free)
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            backend = open_backend(self.solver, threads=1, seed=0)
            try:
                backend.load(projected.program)
                backend.warm_start(projected.initial)
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                # Leave room for reconstruction and checking the full rows.
                allowance = 0.8 * remaining / (len(semesters) - position)
                outcome = backend.optimise(
                    projected.objective, maximise=maximise, gap=0.0, time_limit=allowance,
                )
                if not outcome.usable:
                    continue
                old = sum(c * projected.initial[i] for i, c in projected.objective.terms.items())
                delta = outcome.objective - old
                if (delta if maximise else -delta) <= 1e-6:
                    continue
                candidate = list(best)
                for column, value in zip(projected.columns, outcome.values, strict=True):
                    candidate[column] = value
                # Do not trust a small model's optimum as a full-model proof.
                # Check all active constraints, including the stage caps, and
                # integrality/bounds before accepting a heuristic incumbent.
                for column in projected.columns:
                    variable = built.program.variables[column]
                    value = candidate[column]
                    if (
                        not math.isfinite(value)
                        or not variable.lower - 1e-6 <= value <= variable.upper + 1e-6
                        or (variable.kind is not VarKind.CONTINUOUS
                            and abs(value - round(value)) > 1e-6)
                    ):
                        raise SolveError("neighborhood", f"invalid value for {variable.name}")
                for row in rows:
                    if not _satisfied(row, sum(c * candidate[i] for i, c in row.terms.items())):
                        raise SolveError("neighborhood", f"candidate violates {row.name}")
                from .solver import _extract

                validate_initial_assignments(built.instance, _extract(built, candidate))
                best = candidate
                self.progress(f"{semester} neighborhood improved objective by {abs(delta):.2f}")
            finally:
                backend.close()
        return best
