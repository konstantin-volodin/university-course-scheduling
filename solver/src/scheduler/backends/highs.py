"""HiGHS backend — the default.

HiGHS is open source and has no licence server and no size cap, which is what
makes this service usable on a real academic year. Gurobi's free licence stops
at 2000 columns; a real instance is tens of thousands.

Rows are handed over in one call rather than added one at a time. Building a
model row-by-row through a solver's Python API is the slowest part of most MIP
codebases, and there is no reason to pay for it when the whole program is
already known.
"""

from __future__ import annotations

import time

import highspy
import numpy as np

from ..errors import SolverError
from ..model.program import LinearExpr, Program, Sense, VarKind
from .base import Outcome, SolutionStatus

__all__ = ["HighsBackend"]

_HIGHS_INFINITY = highspy.kHighsInf


class HighsBackend:
    """Solves a :class:`~scheduler.model.program.Program` with HiGHS."""

    name = "highs"

    def __init__(self, *, threads: int = 4, seed: int = 0) -> None:
        try:
            self._highs = highspy.Highs()  # type: ignore[no-untyped-call]
        except Exception as exc:  # pragma: no cover - only if highspy is broken
            raise SolverError(f"could not start HiGHS: {exc}") from exc
        self._highs.setOptionValue("output_flag", False)
        # Determinism: HiGHS, like any parallel MIP solver, can otherwise return
        # a different member of the optimal set run to run.
        self._highs.setOptionValue("threads", threads)
        self._highs.setOptionValue("random_seed", seed)
        self._columns = 0
        self._start: list[float] = []

    # -- construction ---------------------------------------------------- #

    def load(self, program: Program) -> None:
        highs = self._highs
        self._columns = len(program.variables)

        lower = np.array([v.lower for v in program.variables], dtype=np.float64)
        upper = np.array(
            [_HIGHS_INFINITY if v.upper == float("inf") else v.upper for v in program.variables],
            dtype=np.float64,
        )
        zeros = np.zeros(self._columns, dtype=np.float64)
        highs.addCols(self._columns, zeros, lower, upper, 0, [], [], [])

        integral = [
            index
            for index, variable in enumerate(program.variables)
            if variable.kind in (VarKind.INTEGER, VarKind.BINARY)
        ]
        if integral:
            highs.changeColsIntegrality(
                len(integral),
                np.array(integral, dtype=np.int32),
                np.array([highspy.HighsVarType.kInteger] * len(integral)),
            )

        if not program.rows:
            return

        # One flat CSR-style batch: starts, indices, values.
        starts, indices, values = [0], [], []
        row_lower, row_upper = [], []
        for row in program.rows:
            for column, coefficient in row.terms.items():
                indices.append(column)
                values.append(coefficient)
            starts.append(len(indices))
            low, high = _bounds(row.sense, row.rhs)
            row_lower.append(low)
            row_upper.append(high)

        highs.addRows(
            len(program.rows),
            np.array(row_lower, dtype=np.float64),
            np.array(row_upper, dtype=np.float64),
            len(indices),
            np.array(starts[:-1], dtype=np.int32),
            np.array(indices, dtype=np.int32),
            np.array(values, dtype=np.float64),
        )

    def add_row(self, name: str, terms: dict[int, float], sense: Sense, rhs: float) -> None:
        del name  # HiGHS addresses rows positionally; names are for the program only
        low, high = _bounds(sense, rhs)
        columns = np.array(list(terms), dtype=np.int32)
        coefficients = np.array(list(terms.values()), dtype=np.float64)
        self._highs.addRow(low, high, len(terms), columns, coefficients)

    def warm_start(self, values: list[float]) -> None:
        # Held, not applied: HiGHS drops a user solution when the objective
        # changes, and the objective is swapped at the top of every optimise().
        self._start = list(values)

    # -- solving ---------------------------------------------------------- #

    def optimise(
        self, objective: LinearExpr, *, maximise: bool, gap: float, time_limit: float | None
    ) -> Outcome:
        highs = self._highs

        costs = np.zeros(self._columns, dtype=np.float64)
        for index, coefficient in objective.terms.items():
            costs[index] = coefficient
        highs.changeColsCost(
            self._columns, np.arange(self._columns, dtype=np.int32), costs
        )
        highs.changeObjectiveSense(
            highspy.ObjSense.kMaximize if maximise else highspy.ObjSense.kMinimize
        )
        highs.setOptionValue("mip_rel_gap", gap)
        highs.setOptionValue("time_limit", time_limit if time_limit else _HIGHS_INFINITY)

        if self._start:
            highs.setSolution(
                len(self._start),
                np.arange(len(self._start), dtype=np.int32),
                np.array(self._start, dtype=np.float64),
            )

        started = time.perf_counter()
        highs.run()
        elapsed = time.perf_counter() - started

        model_status = highs.getModelStatus()
        label = highs.modelStatusToString(model_status)
        info = highs.getInfo()

        feasible = highspy.SolutionStatus.kSolutionStatusFeasible
        if getattr(info, "primal_solution_status", 0) != feasible:
            return Outcome(SolutionStatus.NO_SOLUTION, 0.0, [], elapsed, label)

        values = list(highs.getSolution().col_value)
        objective_value = float(highs.getObjectiveValue())
        status = (
            SolutionStatus.OPTIMAL
            if model_status == highspy.HighsModelStatus.kOptimal
            else SolutionStatus.FEASIBLE
        )
        return Outcome(status, objective_value, values, elapsed, label)

    def close(self) -> None:
        self._highs.clear()


def _bounds(sense: Sense, rhs: float) -> tuple[float, float]:
    """HiGHS states every row as ``low <= ax <= high``."""
    if sense is Sense.LE:
        return -_HIGHS_INFINITY, rhs
    if sense is Sense.GE:
        return rhs, _HIGHS_INFINITY
    return rhs, rhs

