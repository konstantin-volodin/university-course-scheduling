"""Course workload allocation API."""

from __future__ import annotations

from .backends import BACKENDS, DEFAULT_BACKEND
from .config import PAYLOAD_KEYS, Instance
from .errors import InvalidInstanceError, SchedulerError, SolveError, SolverError
from .progress import Progress, silent, to_stderr
from .solve import Assignment, Result, Stage, solve, solve_instance

__version__ = "1.0.0"

__all__ = [
    "BACKENDS",
    "DEFAULT_BACKEND",
    "PAYLOAD_KEYS",
    "Assignment",
    "Instance",
    "InvalidInstanceError",
    "Progress",
    "Result",
    "SchedulerError",
    "SolveError",
    "SolverError",
    "Stage",
    "__version__",
    "silent",
    "solve",
    "solve_instance",
    "to_stderr",
]
