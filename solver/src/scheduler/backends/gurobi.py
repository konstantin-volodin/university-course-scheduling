"""Gurobi backend — optional.

Kept because the formulation was written against Gurobi and a university often
already has a licence, where it is usually the stronger solver on a large MIP.
It is not the default: the free licence bundled with ``pip install gurobipy``
caps out at 2000 columns, which will not hold a real academic year.

``gurobipy`` is an optional dependency. Nothing imports this module unless the
backend is actually asked for.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from ..errors import SolverError
from ..model.program import LinearExpr, Program, Sense, VarKind
from .base import Outcome, SolutionStatus

__all__ = ["GurobiBackend"]

_LICENCE_HINTS = ("size-limited", "license", "licence")


class GurobiBackend:
    """Solves a :class:`~scheduler.model.program.Program` with Gurobi."""

    name = "gurobi"

    def __init__(self, *, threads: int = 4, seed: int = 0) -> None:
        try:
            import gurobipy as gp
        except ImportError as exc:  # pragma: no cover - depends on install
            raise SolverError(
                "the gurobi backend needs gurobipy: pip install 'workload-scheduler[gurobi]'"
            ) from exc

        self._gp = gp
        # The licence banner prints when the environment starts, and it goes to
        # stdout — which would corrupt the JSON a caller is parsing.
        self._env = gp.Env(empty=True)
        self._env.setParam("OutputFlag", 0)
        self._env.setParam("Threads", threads)
        self._env.setParam("Seed", seed)
        self._env.start()
        self._model = gp.Model("workload_allocation", env=self._env)
        self._vars: list[Any] = []

    def load(self, program: Program) -> None:
        gp = self._gp
        kinds = {
            VarKind.CONTINUOUS: gp.GRB.CONTINUOUS,
            VarKind.INTEGER: gp.GRB.INTEGER,
            VarKind.BINARY: gp.GRB.BINARY,
        }
        try:
            self._vars = [
                self._model.addVar(
                    lb=v.lower,
                    ub=gp.GRB.INFINITY if v.upper == float("inf") else v.upper,
                    vtype=kinds[v.kind],
                    name=v.name,
                )
                for v in program.variables
            ]
            self._model.update()
            for row in program.rows:
                self._add(row.name, row.terms, row.sense, row.rhs)
            self._model.update()
        except gp.GurobiError as exc:
            raise self._translate(exc, program) from exc

    def add_row(self, name: str, terms: dict[int, float], sense: Sense, rhs: float) -> None:
        try:
            self._add(name, terms, sense, rhs)
            self._model.update()
        except self._gp.GurobiError as exc:
            raise SolverError(f"Gurobi rejected a constraint: {exc}") from exc

    def _add(self, name: str, terms: Mapping[int, float], sense: Sense, rhs: float) -> None:
        expression = self._gp.LinExpr(
            list(terms.values()), [self._vars[i] for i in terms]
        )
        if sense is Sense.LE:
            self._model.addLConstr(expression, self._gp.GRB.LESS_EQUAL, rhs, name)
        elif sense is Sense.GE:
            self._model.addLConstr(expression, self._gp.GRB.GREATER_EQUAL, rhs, name)
        else:
            self._model.addLConstr(expression, self._gp.GRB.EQUAL, rhs, name)

    def warm_start(self, values: list[float]) -> None:
        for variable, value in zip(self._vars, values, strict=True):
            variable.Start = value
        self._model.update()

    def optimise(
        self, objective: LinearExpr, *, maximise: bool, gap: float, time_limit: float | None
    ) -> Outcome:
        gp = self._gp
        try:
            self._model.setObjective(
                gp.LinExpr(
                    list(objective.terms.values()), [self._vars[i] for i in objective.terms]
                ),
                gp.GRB.MAXIMIZE if maximise else gp.GRB.MINIMIZE,
            )
            self._model.Params.MIPGap = gap
            self._model.Params.TimeLimit = (
                time_limit if time_limit is not None else gp.GRB.INFINITY
            )

            started = time.perf_counter()
            self._model.optimize()
            elapsed = time.perf_counter() - started
        except gp.GurobiError as exc:
            raise self._translate(exc, None) from exc

        if self._model.SolCount == 0:
            detail = _explain(self._model.Status)
            return Outcome(SolutionStatus.NO_SOLUTION, 0.0, [], elapsed, detail)

        status = (
            SolutionStatus.OPTIMAL
            if self._model.Status == gp.GRB.OPTIMAL
            else SolutionStatus.FEASIBLE
        )
        values = [float(v.X) for v in self._vars]
        return Outcome(status, float(self._model.ObjVal), values, elapsed)

    def close(self) -> None:
        self._model.dispose()
        self._env.dispose()

    def _translate(self, exc: Exception, program: Program | None) -> SolverError:
        text = str(exc)
        if any(hint in text.lower() for hint in _LICENCE_HINTS):
            size = ""
            if program is not None:
                size = (
                    f" This model has {len(program.variables):,} variables and "
                    f"{len(program.rows):,} constraints."
                )
            return SolverError(
                f"Gurobi will not solve a model this size with the licence available: {text}."
                f"{size} The licence bundled with pip is capped at 2000 of each, which only "
                "fits a toy problem. Use the default HiGHS backend, which has no such limit, "
                "or install a full Gurobi licence."
            )
        return SolverError(f"Gurobi failed: {text}")


def _explain(status: int) -> str:
    import gurobipy as gp

    return {
        gp.GRB.INFEASIBLE: "infeasible",
        gp.GRB.UNBOUNDED: "unbounded, which means a constraint is missing",
        gp.GRB.INF_OR_UNBD: "infeasible or unbounded",
        gp.GRB.TIME_LIMIT: "hit the time limit before finding any solution",
        gp.GRB.INTERRUPTED: "interrupted before finding any solution",
    }.get(status, f"gurobi status {status}")
