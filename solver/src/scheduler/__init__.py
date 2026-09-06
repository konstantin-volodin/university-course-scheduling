"""Course workload allocation API."""

from __future__ import annotations

from .backends import BACKENDS, DEFAULT_BACKEND
from .config import PAYLOAD_KEYS, Instance
from .errors import InvalidInstanceError, SchedulerError, SolveError, SolverError
from .progress import Progress, TerminalProgress, silent, to_stderr
from .solve import (
    Assignment,
    ObjectiveBreakdown,
    ObjectiveTerm,
    Result,
    Stage,
    solve,
    solve_instance,
)

__version__ = "1.0.0"

__all__ = [
    "BACKENDS",
    "DEFAULT_BACKEND",
    "PAYLOAD_KEYS",
    "Assignment",
    "Instance",
    "InvalidInstanceError",
    "ObjectiveBreakdown",
    "ObjectiveTerm",
    "Progress",
    "Result",
    "SchedulerError",
    "SolveError",
    "SolverError",
    "Stage",
    "TerminalProgress",
    "__version__",
    "silent",
    "solve",
    "solve_instance",
    "to_stderr",
]
