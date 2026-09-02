"""A solver-agnostic mixed-integer program.

The model used to be built directly out of Gurobi objects, which welded the
formulation to a commercial licence — and that licence refuses instances of any
realistic size. Everything here is a plain Python value instead: variables,
sparse rows, and linear expressions. A backend translates it and solves it.

The representation is deliberately small, because the formulation only needs
linear rows over integer and continuous variables. Nothing here knows what a
professor is, and nothing here knows what a solver is.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "INFINITY",
    "LinearExpr",
    "Program",
    "Row",
    "Sense",
    "VarKind",
    "Variable",
]

#: Stand-in for an unbounded variable. Backends map this to their own infinity.
INFINITY = float("inf")


class VarKind(Enum):
    CONTINUOUS = "continuous"
    INTEGER = "integer"
    BINARY = "binary"


class Sense(Enum):
    LE = "<="
    GE = ">="
    EQ = "=="


@dataclass(frozen=True, slots=True)
class Variable:
    name: str
    lower: float
    upper: float
    kind: VarKind


@dataclass(frozen=True, slots=True)
class Row:
    """One linear constraint: ``terms (sense) rhs``.

    ``terms`` maps a variable index to its coefficient. Absent means zero, so a
    row only ever carries what it actually constrains.
    """

    name: str
    terms: Mapping[int, float]
    sense: Sense
    rhs: float


class LinearExpr:
    """A sparse linear expression over variable indices.

    Mutable and additive, because the objective terms are accumulated a slice at
    a time while the model is built. Arithmetic is only what the formulation
    needs: add another expression, scale it, add a single term.
    """

    __slots__ = ("terms",)

    def __init__(self, terms: Mapping[int, float] | None = None) -> None:
        self.terms: dict[int, float] = dict(terms) if terms else {}

    def add(self, index: int, coefficient: float = 1.0) -> LinearExpr:
        if coefficient:
            self.terms[index] = self.terms.get(index, 0.0) + coefficient
        return self

    def extend(self, other: LinearExpr, scale: float = 1.0) -> LinearExpr:
        for index, coefficient in other.terms.items():
            self.add(index, coefficient * scale)
        return self

    def __add__(self, other: LinearExpr) -> LinearExpr:
        return LinearExpr(self.terms).extend(other)


@dataclass(slots=True)
class Program:
    """Variables and rows, addressed by index.

    Indices are handed out in creation order and never change, so a backend can
    hold parallel arrays and a solution can be read back positionally.
    """

    variables: list[Variable] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)

    def add_variable(
        self,
        name: str,
        *,
        lower: float = 0.0,
        upper: float = INFINITY,
        kind: VarKind = VarKind.CONTINUOUS,
    ) -> int:
        self.variables.append(Variable(name, lower, upper, kind))
        return len(self.variables) - 1

    def add_row(self, name: str, terms: Mapping[int, float], sense: Sense, rhs: float) -> int:
        self.rows.append(Row(name, dict(terms), sense, rhs))
        return len(self.rows) - 1

    @property
    def nonzeros(self) -> int:
        return sum(len(row.terms) for row in self.rows)
