"""The staged solve, and the public :func:`solve` entry point.

The program is solved in ten stages. Each stage optimises one objective,
then freezes the result as a row before the next stage runs. That keeps the
ordering honest: a later stage can improve preferences only within the
objective ceilings reached by earlier stages. A time-limited stage may leave
an unproven ceiling; later stages do not establish that it was necessary.

Solving straight for a weighted sum of everything would let the solver buy a
better preference score by breaking a teaching load, at whatever exchange rate
the weights happened to imply. Nobody can pick those weights defensibly, so we
don't ask them to.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from ..backends import DEFAULT_BACKEND, Backend, SolutionStatus, open_backend
from ..config import OFF_CAMPUS, PART_TIMER, Instance, is_placeholder, placeholder_for
from ..errors import SolveError
from ..model import AssignmentKey, BuiltModel, Objectives, build
from ..model.program import LinearExpr, Program, Row, Sense, VarKind
from ..progress import Progress, ProgressCallback
from .result import Assignment, ObjectiveBreakdown, ObjectiveTerm, Result, Stage
from .room_seed import seed_physical_rooms
from .warm_start import validate_initial_assignments

__all__ = ["Assignment", "Result", "Stage", "solve", "solve_instance"]

#: Optimality gap for the violation stages. These count whole violations, so
#: the answer must be exact — "within 5%" of two violations is meaningless.
EXACT = 0.0

#: Optimality gap for the preference stages, where the last few percent costs
#: far more time than it is worth.
GOOD_ENOUGH = 0.05

#: Fixed so repeated runs of the same instance return the same schedule. Any
#: parallel MIP solver is only deterministic at a fixed thread count.
# HiGHS' parallel MIP path can return ``Not Set`` on the large default-qualified
# instance even when its single-threaded path solves the same model immediately.
# A deterministic single-threaded run is preferable to reporting a false
# no-solution result; the instance is still bounded by the caller's time limit.
THREADS = 1
SEED = 0

#: Solver values are floating point; anything below this is a zero that drifted.
TOLERANCE = 0.01


class _StagedSolve:
    """Runs the stages, carrying the winning solution forward."""

    def __init__(
        self,
        backend: Backend,
        progress: Progress,
        time_limit: float | None,
        program: Program | None = None,
    ) -> None:
        self.backend = backend
        self.program = program if program is not None else Program()
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

    def _minimise_then_cap(
        self, name: str, objective: LinearExpr, gap: float, *, integral: bool = True,
    ) -> None:
        """Minimise, then hold the result as a ceiling for every later stage.

        Count objectives use an integer ceiling. Balance contains fractional
        teaching-hour units, so it retains its attained value within tolerance.
        """
        value = self._optimise(name, objective, maximise=False, gap=gap)
        self.backend.add_rows([Row(
            f"cap_{name.replace(' ', '_')}",
            dict(objective.terms),
            Sense.LE,
            math.ceil(value - 1e-6) if integral else value + 1e-6,
        )])

    def run(
        self,
        objectives: Objectives,
        room_seed: Callable[[list[float]], list[float]] | None = None,
        deferred: Sequence[Row] = (),
    ) -> float:
        initial = list(self.values)
        self._minimise_then_cap(
            "assign named professors to required sections",
            objectives.teaching_load,
            EXACT,
        )
        # Load minimisation is indifferent to whether sections have timeslots.
        # Preserve a better timetable hint when it still meets the new load cap;
        # never sacrifice the higher-priority objective to keep that timetable.
        timetable = objectives.concurrency + objectives.placeholder_use
        if initial:
            initial_load = sum(c * initial[i] for i, c in objectives.teaching_load.terms.items())
            load_cap = math.ceil(self.stages[-1].value - 1e-6)
            initial_timetable = sum(c * initial[i] for i, c in timetable.terms.items())
            current_timetable = sum(c * self.values[i] for i, c in timetable.terms.items())
            if initial_load <= load_cap + 1e-6 and initial_timetable < current_timetable - 1e-6:
                self.values = initial
        self._minimise_then_cap(
            "minimise timetable conflicts and unscheduled sections",
            timetable,
            EXACT,
        )
        if room_seed is not None:
            self.values = room_seed(self.values)
        self._minimise_then_cap(
            "minimise off-campus teaching", objectives.off_campus_use, GOOD_ENOUGH
        )
        self._minimise_then_cap(
            "minimise part-timer use of physical rooms",
            objectives.part_timer_room_use,
            EXACT,
        )
        # The preference rows come in only now. None of them can rule out a
        # solution -- each one just pins a variable the preference objective
        # reads -- so carrying them through the violation stages above would
        # have doubled the matrix those stages search for no gain at all.
        if deferred:
            with self.progress.step("solving", "adding preference rows") as done:
                self.backend.add_rows(deferred)
                self.values = _repair(self.program, self.values, deferred)
                done(f"{len(deferred):,} rows")

        # Balance is deliberately its own stage. Once capped, the model has a
        # smaller and clearer remaining objective: all other preferences can
        # trade against each other without undoing the best distribution.
        self._minimise_then_cap(
            "optimise time-of-day and day-of-week balance",
            objectives.time_of_day_spread + objectives.day_of_week_spread,
            EXACT,
            integral=False,
        )
        self._minimise_then_cap(
            "minimise course block violations", objectives.block_violation, EXACT
        )
        self._minimise_then_cap(
            "minimise Friday-night penalties", objectives.friday_night, EXACT
        )
        # The preceding objectives do not read room-use auxiliaries, so a MIP
        # incumbent may leave them at arbitrary feasible values. Reconstruct
        # every deferred definition before this stage to offer the actual room
        # count as the incumbent instead of asking the solver to rediscover it.
        if deferred:
            self.values = _repair(
                self.program,
                self.values,
                deferred,
                reset_prefixes=("uses_room[", "uses_physical_room_day["),
            )
        self._minimise_then_cap(
            "minimise room changes", objectives.room_changes, GOOD_ENOUGH
        )
        self._minimise_then_cap(
            "minimise additional teaching days", objectives.pack_day_penalty, EXACT
        )
        self._optimise(
            "maximise course, time, and block preference rewards",
            objectives.remaining_preference_score(),
            True,
            GOOD_ENOUGH,
        )
        return sum(
            component.weight
            * sum(
                coefficient * self.values[index]
                for index, coefficient in component.expression.terms.items()
            )
            for component in objectives.preference_components()
        )


def _repair(
    program: Program,
    values: list[float],
    rows: Sequence[Row],
    *,
    reset_prefixes: tuple[str, ...] = (),
) -> list[float]:
    """Give the deferred rows' variables the values those rows demand.

    The violation stages run without these rows, so the solver never had a
    reason to set the variables they define and hands them back at zero. Fed
    straight into the preference stage that point is infeasible, the warm start
    is rejected, and a model this size then finds nothing at all inside its time
    limit -- which reads as an impossible instance and is nothing of the kind.

    Every deferred row pins exactly one variable in terms of assignments already
    decided, and the rows come in the order those definitions were built, so one
    pass settles all of them. Each variable is moved the least the row allows,
    which keeps the rest of the solution exactly as it was found.
    """
    if not values:
        return values
    repaired = list(values)
    if reset_prefixes:
        for row in rows:
            if (
                row.defines is not None
                and program.variables[row.defines].name.startswith(reset_prefixes)
            ):
                repaired[row.defines] = program.variables[row.defines].lower
    for row in rows:
        target = row.defines
        if target is None:
            continue
        coefficient = row.terms.get(target)
        if not coefficient:
            continue
        rest = sum(
            factor * repaired[index]
            for index, factor in row.terms.items()
            if index != target
        )
        needed = (row.rhs - rest) / coefficient
        variable = program.variables[target]
        integral = variable.kind in (VarKind.INTEGER, VarKind.BINARY)
        if row.sense is Sense.EQ:
            value = math.ceil(needed - 1e-9) if integral else needed
        elif (row.sense is Sense.LE) == (coefficient > 0):
            # The row caps this variable; only lower it if it sits above.
            value = min(repaired[target], math.floor(needed + 1e-9) if integral else needed)
        else:
            value = max(repaired[target], math.ceil(needed - 1e-9) if integral else needed)
        repaired[target] = min(max(value, variable.lower), variable.upper)
    return repaired


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


def _preference_breakdown(
    objectives: Objectives, values: list[float], variable_names: Sequence[str]
) -> list[ObjectiveBreakdown]:
    """Evaluate each named component, retaining its active terms for audit."""
    breakdown = []
    for component in objectives.preference_components():
        terms = [
            ObjectiveTerm(
                variable=variable_names[index],
                coefficient=coefficient,
                value=values[index],
                contribution=coefficient * values[index],
            )
            for index, coefficient in sorted(component.expression.terms.items())
            if abs(values[index]) > TOLERANCE
        ]
        # Keep the scalar exact even though the audit list omits numerical
        # noise and inactive terms.
        raw_value = sum(
            coefficient * values[index]
            for index, coefficient in component.expression.terms.items()
        )
        breakdown.append(
            ObjectiveBreakdown(
                name=component.name,
                label=component.label,
                description=component.description,
                raw_value=raw_value,
                weight=component.weight,
                contribution=component.weight * raw_value,
                terms=terms,
            )
        )
    return breakdown


def _placeholder_seed(built: BuiltModel) -> list[float]:
    """Build an integral, all-placeholder incumbent for the first stage.

    A warm start needs an integral assignment across declared qualifications; otherwise
    HiGHS may spend the whole first stage searching for its first incumbent.
    Placeholder slots make this matching independent of rooms and timetable
    clashes; those are deliberately handled by later stages.
    """
    inst = built.instance
    sections = sorted(inst.section_keys)
    owner: dict[tuple[str, str, str, str], str] = {}

    def take(professor: str, seen: set[tuple[str, str, str, str]]) -> bool:
        candidates = (
            key for key in sections
            if key not in seen
            and (professor, key[0]) in inst.qualifications
            and AssignmentKey(
                professor, key[0], key[1], key[2], key[3], placeholder_for(key[3]), OFF_CAMPUS
            ) in built.assign
        )
        for key in candidates:
            seen.add(key)
            previous = owner.get(key)
            if previous is None or take(previous, seen):
                owner[key] = professor
                return True
        return False

    for professor in sorted(inst.real_professors):
        for _ in range(inst.teaching_load[professor]):
            if not take(professor, set()):
                return []

    values = [0.0] * len(built.program.variables)
    for key in sections:
        professor = owner.get(key, PART_TIMER)
        assignment = AssignmentKey(
            professor, key[0], key[1], key[2], key[3], placeholder_for(key[3]), OFF_CAMPUS
        )
        variable = built.assign.get(assignment)
        if variable is None:
            return []
        values[variable] = 1.0
    return values


def _schedule_seed(built: BuiltModel, assignments: Sequence[Assignment]) -> list[float]:
    """Reconstruct core slacks for a validated external schedule."""
    values = [variable.lower for variable in built.program.variables]
    for assignment in assignments:
        key = AssignmentKey(
            PART_TIMER if assignment.professor_id is None else assignment.professor_id,
            assignment.course_id,
            str(assignment.section_id),
            assignment.semester_id,
            assignment.time_of_day_id,
            (placeholder_for(assignment.time_of_day_id)
             if assignment.timeslot_id is None else assignment.timeslot_id),
            OFF_CAMPUS if assignment.classroom_id is None else assignment.classroom_id,
        )
        if key not in built.assign:
            raise SolveError("warm start", f"assignment is not eligible: {key}")
        values[built.assign[key]] = 1.0

    assignment_columns = set(built.assign.values())
    definitions = []
    for row in built.program.core_rows:
        auxiliary = row.terms.keys() - assignment_columns
        if len(auxiliary) == 1:
            definitions.append(replace(row, defines=next(iter(auxiliary))))
    values = _repair(built.program, values, definitions)
    for row in built.program.core_rows:
        lhs = sum(coefficient * values[index] for index, coefficient in row.terms.items())
        if (
            (row.sense is Sense.LE and lhs > row.rhs + 1e-6)
            or (row.sense is Sense.GE and lhs < row.rhs - 1e-6)
            or (row.sense is Sense.EQ and abs(lhs - row.rhs) > 1e-6)
        ):
            raise SolveError("warm start", f"cannot satisfy core row {row.name}")
    return values


def solve_instance(
    inst: Instance,
    progress: ProgressCallback | None = None,
    time_limit: float | None = None,
    solver: str = DEFAULT_BACKEND,
    *,
    initial_assignments: Sequence[Assignment] | None = None,
) -> Result:
    """Solve an already-validated instance.

    :param time_limit: seconds, applied to each solve stage. Cold initialization
        adds a preliminary budget of at most ten seconds, capped by this limit.
        Model construction and backend overhead are additional. Without one a hard
        instance can run indefinitely, which is not something an HTTP service
        can offer. Stopping early yields ``status="feasible"`` rather than an
        error, provided a solution was found.
    :param solver: which backend to use; see :data:`scheduler.backends.BACKENDS`.
    :param initial_assignments: optional complete, legal schedule used as an
        incumbent, never as fixed assignments or a restriction of the model.
    """
    if time_limit is not None and (not math.isfinite(time_limit) or time_limit <= 0):
        raise ValueError("time_limit must be positive and finite")

    reporter = Progress(progress)
    reporter(inst.summary())
    if initial_assignments is not None:
        validate_initial_assignments(inst, initial_assignments)

    # Preferences rank legal assignments; they do not revoke qualifications.
    # Even a load-feasible subset can exclude the only conflict-free timetable.
    built = build(inst, reporter)
    with reporter.step("building", "preparing initial schedule"):
        initial = (
            _placeholder_seed(built) if initial_assignments is None
            else _schedule_seed(built, initial_assignments)
        )

    if initial_assignments is None:
        from .cold_start import restricted_incumbent

        candidate = restricted_incumbent(
            built, min(time_limit, 10.0) if time_limit is not None else 10.0,
            solver, reporter,
        )
        if candidate is not None:
            initial = candidate
            reporter("using validated restricted-search timetable as the initial schedule")
        else:
            reporter("restricted search supplied no better seed; using the placeholder fallback")

    backend = open_backend(solver, threads=THREADS, seed=SEED)
    try:
        with reporter.step("solving", f"loading into {backend.name}"):
            backend.load(built.program)

        staged = _StagedSolve(backend, reporter, time_limit, built.program)
        staged.values = initial
        objective = staged.run(
            built.objectives,
            room_seed=lambda values: seed_physical_rooms(built, values),
            deferred=built.program.deferred_rows,
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
        preference_breakdown=_preference_breakdown(
            built.objectives, staged.values, [variable.name for variable in built.program.variables]
        ),
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
