"""What a solver has to provide.

The staged solve needs four things: load a program, optimise an expression,
read the answer back, and bolt on a new row before the next stage. Anything a
solver offers beyond that is not the formulation's business.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from ..model.program import LinearExpr, Program, Sense

__all__ = ["Backend", "Outcome", "SolutionStatus"]


class SolutionStatus(Enum):
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    NO_SOLUTION = "no solution"


@dataclass(frozen=True, slots=True)
class Outcome:
    status: SolutionStatus
    objective: float
    values: list[float]
    seconds: float
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.status is not SolutionStatus.NO_SOLUTION


@runtime_checkable
class Backend(Protocol):
    """A MIP solver, reduced to what this package actually asks of one."""

    name: str

    def load(self, program: Program) -> None:
        """Hand over the variables and rows. Called once."""

    def add_row(self, name: str, terms: dict[int, float], sense: Sense, rhs: float) -> None:
        """Add a row after loading. Used to freeze one stage before the next."""

    def warm_start(self, values: list[float]) -> None:
        """Offer a known-feasible point for the next solve to start from.

        Each stage only adds rows, so the previous stage's answer is always
        feasible for the next one. Without this the solver restarts cold every
        stage and a big instance can burn its whole time limit before finding
        any incumbent at all -- reported as "no solution", which reads like
        infeasibility and is not.
        """

    def optimise(
        self, objective: LinearExpr, *, maximise: bool, gap: float, time_limit: float | None
    ) -> Outcome:
        """Solve for one objective and report what was found."""

    def close(self) -> None:
        """Release solver resources."""
