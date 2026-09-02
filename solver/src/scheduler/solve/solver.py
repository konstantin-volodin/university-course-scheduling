"""The staged solve, and the public :func:`solve` entry point.

The program is solved four times, not once. Each stage optimises one objective,
then freezes the result as a row before the next stage runs. That keeps the
ordering honest: a later stage can improve preferences only within the
compromises the earlier stages already proved were necessary.

Solving straight for a weighted sum of everything would let the solver buy a
better preference score by breaking a teaching load, at whatever exchange rate
the weights happened to imply. Nobody can pick those weights defensibly, so we
don't ask them to.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

from ..backends import DEFAULT_BACKEND, Backend, SolutionStatus, open_backend
from ..config import OFF_CAMPUS, PART_TIMER, Instance, is_placeholder
from ..errors import SolveError
from ..model import BuiltModel, Objectives, build
from ..model.program import LinearExpr, Sense
from ..progress import Progress, ProgressCallback
from .result import Assignment, Result, Stage
from .room_seed import seed_physical_rooms

__all__ = ["Assignment", "Result", "Stage", "solve", "solve_instance"]

#: Optimality gap for the violation stages. These count whole violations, so
#: the answer must be exact — "within 5%" of two violations is meaningless.
EXACT = 0.0

#: Optimality gap for the preference stages, where the last few percent costs
#: far more time than it is worth.
GOOD_ENOUGH = 0.05

#: Fixed so repeated runs of the same instance return the same schedule. Any
#: parallel MIP solver is only deterministic at a fixed thread count.
THREADS = 4
SEED = 0

#: Solver values are floating point; anything below this is a zero that drifted.
TOLERANCE = 0.01


class _StagedSolve:
    """Runs the stages, carrying the winning solution forward."""

    def __init__(self, backend: Backend, progress: Progress, time_limit: float | None) -> None:
        self.backend = backend
        self.progress = progress
        self.time_limit = time_limit
        self.stages: list[Stage] = []
        self.values: list[float] = []

    def _optimise(self, name: str, objective: LinearExpr, maximise: bool, gap: float) -> float:
        with self.progress.step("solving", name) as done:
            if self.values:
                self.backend.warm_start(self.values)
            outcome = self.backend.optimise(
                objective, maximise=maximise, gap=gap, time_limit=self.time_limit
            )
            if not outcome.usable:
                raise SolveError(name, outcome.detail)
            self.values = outcome.values
            proven = outcome.status is SolutionStatus.OPTIMAL
            done(f"{outcome.objective:,.2f}" + ("" if proven else " (stopped early)"))

        self.stages.append(
            Stage(name=name, value=outcome.objective, seconds=outcome.seconds, proven=proven)
        )
        return outcome.objective

    def _minimise_then_cap(self, name: str, objective: LinearExpr, gap: float) -> None:
        """Minimise, then hold the result as a ceiling for every later stage.

        Rounded up: these count whole violations, and a fractional bound would
        let a later stage exploit numerical slop to slip past an integer limit.
        """
        value = self._optimise(name, objective, maximise=False, gap=gap)
        self.backend.add_row(
            f"cap_{name.replace(' ', '_')}",
            dict(objective.terms),
            Sense.LE,
            math.ceil(value - 1e-6),
        )

    def run(
        self,
        objectives: Objectives,
        room_seed: Callable[[list[float]], list[float]] | None = None,
    ) -> float:
        self._minimise_then_cap(
            "minimise teaching load violations", objectives.teaching_load, EXACT
        )
        self._minimise_then_cap(
            "minimise concurrency and unscheduled sections",
            objectives.concurrency + objectives.placeholder_use,
            EXACT,
        )
        if room_seed is not None:
            self.values = room_seed(self.values)
        self._minimise_then_cap(
            "minimise off-campus teaching", objectives.off_campus_use, GOOD_ENOUGH
        )
        # Everything above is capped now, so this can only trade preferences
        # against each other, inside what is already known to be achievable.
        return self._optimise(
            "maximise preferences", objectives.preference_score(), True, GOOD_ENOUGH
        )


def _extract(built: BuiltModel, values: list[float]) -> list[Assignment]:
    assignments: list[Assignment] = []
    for key, index in built.assign.items():
        value = values[index]
        if value < TOLERANCE:
            continue
        professor = key.professor
        course, section, semester = key.course, key.section, key.semester
        time_of_day, slot, room = key.time_of_day, key.timeslot, key.classroom
        try:
            result_section: int | str = int(section)
        except ValueError:
            result_section = section
        assignments.append(
            Assignment(
                professor_id=None if professor == PART_TIMER else professor,
                course_id=course,
                section_id=result_section,
                semester_id=semester,
                timeslot_id=None if is_placeholder(slot) else slot,
                classroom_id=None if room == OFF_CAMPUS else room,
                time_of_day_id=time_of_day,
                solution_value=float(round(value)),
            )
        )

    assignments.sort(key=lambda a: (a.semester_id, a.course_id, str(a.section_id)))
    return assignments


def solve_instance(
    inst: Instance,
    progress: ProgressCallback | None = None,
    time_limit: float | None = None,
    solver: str = DEFAULT_BACKEND,
) -> Result:
    """Solve an already-validated instance.

    :param time_limit: seconds, applied to each solve stage. Without one a hard
        instance can run indefinitely, which is not something an HTTP service
        can offer. Stopping early yields ``status="feasible"`` rather than an
        error, provided a solution was found.
    :param solver: which backend to use; see :data:`scheduler.backends.BACKENDS`.
    """
    if time_limit is not None and time_limit <= 0:
        raise ValueError("time_limit must be positive")

    reporter = Progress(progress)
    reporter(inst.summary())

    built = build(inst, reporter)

    backend = open_backend(solver, threads=THREADS, seed=SEED)
    try:
        with reporter.step("solving", f"loading into {backend.name}"):
            backend.load(built.program)

        staged = _StagedSolve(backend, reporter, time_limit)
        objective = staged.run(
            built.objectives,
            room_seed=lambda values: seed_physical_rooms(built, values),
        )

        with reporter.step("exporting", "reading solution") as done:
            assignments = _extract(built, staged.values)
            done(f"{len(assignments):,} assignments")
    finally:
        backend.close()

    checks: tuple[tuple[str, Callable[[Assignment], bool]], ...] = (
        ("without a named professor", lambda a: a.professor_id is None),
        ("without a timeslot", lambda a: a.timeslot_id is None),
        ("off campus", lambda a: a.classroom_id is None),
    )
    for label, is_fallback in checks:
        count = sum(1 for a in assignments if is_fallback(a))
        if count:
            reporter(f"warning: {count} assignments {label}")

    return Result(
        status="optimal" if all(stage.proven for stage in staged.stages) else "feasible",
        objective=objective,
        assignments=assignments,
        solver=backend.name,
        stages=staged.stages,
    )


def solve(
    payload: Mapping[str, Any],
    progress: ProgressCallback | None = None,
    time_limit: float | None = None,
    solver: str = DEFAULT_BACKEND,
) -> Result:
    """Solve one workload-allocation instance.

    :param payload: one key per ``/OPTIM_data/`` endpoint. See
        :data:`scheduler.config.instance.PAYLOAD_KEYS`.
    :param progress: called as ``(stage, message)`` while the solve runs.
        Defaults to writing to stderr; pass :func:`scheduler.progress.silent`
        for nothing.
    :param time_limit: seconds per solve stage; see :func:`solve_instance`.
    :param solver: which backend to use.
    :raises InvalidInstanceError: the payload is malformed or inconsistent.
    :raises SolveError: a stage found no solution.
    :raises SolverError: the solver itself could not do the work.
    """
    return solve_instance(Instance.from_payload(payload), progress, time_limit, solver)
