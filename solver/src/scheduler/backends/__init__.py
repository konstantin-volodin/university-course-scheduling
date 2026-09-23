"""Solver backends."""

from ..errors import SolverError
from .base import Backend, Outcome, SolutionStatus

DEFAULT_BACKEND = "highs"
BACKENDS = ("highs", "gurobi")

__all__ = [
    "BACKENDS",
    "DEFAULT_BACKEND",
    "Backend",
    "Outcome",
    "SolutionStatus",
    "open_backend",
]


def open_backend(name: str = DEFAULT_BACKEND, *, threads: int = 1, seed: int = 0) -> Backend:
    """Select a solver; import optional dependencies only when requested."""
    if name == "highs":
        from .highs import HighsBackend

        return HighsBackend(threads=threads, seed=seed)
    if name == "gurobi":
        from .gurobi import GurobiBackend

        return GurobiBackend(threads=threads, seed=seed)
    raise SolverError(f"unknown solver backend {name!r}; choose from {', '.join(BACKENDS)}")
