"""Solver backends.

``highs`` is the default: open source, no licence, no size cap. ``gurobi`` is
available for sites that have a full licence and want it.
"""

from __future__ import annotations

from ..errors import SolverError
from .base import Backend, Outcome, SolutionStatus

__all__ = ["BACKENDS", "DEFAULT_BACKEND", "Backend", "Outcome", "SolutionStatus", "open_backend"]

DEFAULT_BACKEND = "highs"
BACKENDS = ("highs", "gurobi")


def open_backend(name: str = DEFAULT_BACKEND, *, threads: int = 4, seed: int = 0) -> Backend:
    """Start a solver backend by name.

    Imported lazily so a missing optional solver only matters to whoever asks
    for it.
    """
    if name == "highs":
        from .highs import HighsBackend

        return HighsBackend(threads=threads, seed=seed)
    if name == "gurobi":
        from .gurobi import GurobiBackend

        return GurobiBackend(threads=threads, seed=seed)
    raise SolverError(f"unknown solver backend {name!r}; choose from {', '.join(BACKENDS)}")
