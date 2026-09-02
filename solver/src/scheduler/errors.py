"""Exception hierarchy.

Callers at a boundary (HTTP, CLI) can catch :class:`SchedulerError` and know the
failure came from us and is safe to report; anything else is a bug worth a
stack trace.
"""

from __future__ import annotations

__all__ = ["InvalidInstanceError", "SchedulerError", "SolveError", "SolverError"]


class SchedulerError(Exception):
    """Base class for every error this package raises deliberately."""


class InvalidInstanceError(SchedulerError, ValueError):
    """The input instance is missing data, malformed, or internally inconsistent.

    Raised before any model is built. The message names every problem found,
    not just the first, so a caller fixing their payload gets one round trip
    instead of twenty.
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        if len(problems) == 1:
            super().__init__(problems[0])
        else:
            listed = "\n".join(f"  - {p}" for p in problems)
            super().__init__(f"{len(problems)} problems with the instance:\n{listed}")


class SolverError(SchedulerError, RuntimeError):
    """The selected solver backend refused to do the work.

    Distinct from :class:`SolveError`, which means the solver ran and found
    nothing. This means it never got that far: no licence, a licence too small
    for the model, or the environment is broken. None of those are the caller's
    data being wrong, and none of them are an internal bug — so they get their
    own type rather than escaping as a raw ``GurobiError`` and being reported
    as a 500.
    """


class SolveError(SchedulerError, RuntimeError):
    """A solve stage finished without a usable solution.

    Each stage constrains the next using its own objective value, so continuing
    past a failed stage would build the rest of the search on a meaningless
    number. We stop instead.
    """

    def __init__(self, stage: str, detail: str = "") -> None:
        self.stage = stage
        self.detail = detail
        message = f"{stage}: no solution found"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(
            f"{message}. The most common cause is teaching loads that add up to more "
            "than the number of sections: the load slack lets a professor exceed "
            "their target but never fall short."
        )
