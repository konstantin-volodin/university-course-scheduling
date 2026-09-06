"""Bounded restricted search for a legal full-model incumbent.

Qualification pruning is a search heuristic here, never a change to the declared
feasible region in the final solve.
"""

from __future__ import annotations

import math
from dataclasses import replace

from ..backends import open_backend
from ..config import PART_TIMER
from ..model import BuiltModel, build
from ..model.program import Sense
from ..progress import Progress
from .warm_start import validate_initial_assignments


def restricted_incumbent(
    full: BuiltModel, time_limit: float, solver: str, progress: Progress,
) -> list[float] | None:
    """Spend one finite solver budget on a smaller, load-feasible search.

    Build/load overhead is additional to the solver budget. A missing or
    ineffective restriction, unavailable solution, or nonimproving candidate
    returns ``None``. Invalid candidates raise rather than hiding a model bug.
    """
    from .solver import EXACT, SEED, THREADS, _extract, _placeholder_seed, _schedule_seed

    if not math.isfinite(time_limit) or time_limit <= 0:
        raise ValueError("time_limit must be positive and finite")
    initial = _placeholder_seed(full)
    if not initial or any(
        abs(c * initial[i]) > 1e-6 for i, c in full.objectives.teaching_load.terms.items()
    ):
        return None

    inst = full.instance
    selected = {
        (key.professor, key.course)
        for key, column in full.assign.items()
        if initial[column] > 0.5 and key.professor != PART_TIMER
    }
    qualified = frozenset(
        selected | (set(inst.course_preference) & inst.qualifications)
    )
    if not qualified or qualified == inst.qualifications:
        return None

    with progress.step("building", "restricted incumbent model"):
        restricted = build(replace(inst, qualifications=qualified), progress)
        seed = _schedule_seed(restricted, _extract(full, initial))
    objective = restricted.objectives.concurrency + restricted.objectives.placeholder_use
    backend = open_backend(solver, threads=THREADS, seed=SEED)
    try:
        backend.load(restricted.program)
        backend.add_row(
            "restricted_zero_load_penalty", dict(restricted.objectives.teaching_load.terms),
            Sense.LE, 0.0,
        )
        backend.warm_start(seed)
        with progress.step("solving", "restricted incumbent search"):
            outcome = backend.optimise(
                objective, maximise=False, gap=EXACT, time_limit=time_limit,
            )
        if not outcome.usable:
            return None
        assignments = _extract(restricted, outcome.values)
    finally:
        backend.close()

    validate_initial_assignments(inst, assignments)
    candidate = _schedule_seed(full, assignments)
    timetable = full.objectives.concurrency + full.objectives.placeholder_use
    if sum(c * candidate[i] for i, c in full.objectives.teaching_load.terms.items()) > 1e-6:
        return None
    if sum(c * candidate[i] for i, c in timetable.terms.items()) >= sum(
        c * initial[i] for i, c in timetable.terms.items()
    ) - 1e-6:
        return None
    return candidate
