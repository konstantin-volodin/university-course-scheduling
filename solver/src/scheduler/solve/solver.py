"""The staged solve, and the public :func:`solve` entry point.

The program is solved in stages, one per goal in :data:`STAGES`. Each optimises one objective,
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
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from ..backends import DEFAULT_BACKEND, Backend, SolutionStatus, open_backend
from ..config import OFF_CAMPUS, PART_TIMER, Instance, is_placeholder, placeholder_for
from ..errors import SolveError
from ..model import AssignmentKey, BuiltModel, Objectives, build
from ..model.program import LinearExpr, Program, Row, Sense, VarKind
from ..progress import Progress, ProgressCallback
from .result import Assignment, Result, Stage, StageItem
from .room_seed import seed_physical_rooms

__all__ = ["Assignment", "Result", "Stage", "solve", "solve_instance"]

#: Optimality gap for every stage. Each counts whole things -- sections, rooms,
#: days -- so "within 5%" of the best count is not an answer anyone can use.
EXACT = 0.0

#: The most any stage may search, in seconds. A stage that runs out returns the
#: best schedule found so far and reports that it was not proven best.
MAX_TIME_LIMIT = 60.0

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


@dataclass(frozen=True, slots=True)
class StageSpec:
    """One goal, in priority order, and what one point of it means."""

    key: str
    name: str
    meaning: str
    objective: Callable[[Objectives], LinearExpr]
    maximise: bool = False
    #: Balance is measured in fractional teaching hours; every other goal counts.
    integral: bool = True


#: The goals, highest priority first. Each is optimised, then held as a ceiling
#: while the rest are optimised, so a lower goal never buys points from a higher one.
STAGES: tuple[StageSpec, ...] = (
    StageSpec(
        "overload", "Keep professors within their agreed loads",
        "One section a named professor teaches beyond their agreed load. "
        "Teaching fewer sections than agreed is never allowed.",
        lambda o: o.teaching_load,
    ),
    StageSpec(
        "unscheduled", "Give every section a meeting time",
        "One section left without a meeting time.",
        lambda o: o.placeholder_use,
    ),
    StageSpec(
        "course_clashes", "Respect course timing rules",
        "One broken rule: two sections of a course meeting at once, courses that must "
        "run apart overlapping, or courses that must run together meeting separately.",
        lambda o: o.concurrency,
    ),
    StageSpec(
        "program_clashes", "Let each program's students take every required course",
        "One required course that a program's students cannot fit alongside the others "
        "without a clash, including a course with no scheduled section. The solver picks "
        "the sections that let students take the most required courses.",
        lambda o: o.program_clash,
    ),
    StageSpec(
        "off_campus", "Teach in our own rooms",
        "One section taught off campus.",
        lambda o: o.off_campus_use,
    ),
    StageSpec(
        "part_timer_rooms", "Give our rooms to named professors first",
        "One part-timer section using one of our rooms.",
        lambda o: o.part_timer_room_use,
    ),
    StageSpec(
        "balance", "Spread teaching across the week",
        "For each semester, the gap between the busiest and quietest time of day plus the "
        "gap between the busiest and quietest weekday, in weighted teaching hours.",
        lambda o: o.time_of_day_spread + o.day_of_week_spread,
        integral=False,
    ),
    StageSpec(
        "meeting_length", "Use each course's preferred meeting length",
        "One section meeting in a length its course does not prefer.",
        lambda o: o.block_violation,
    ),
    StageSpec(
        "friday_night", "Keep flagged courses off Friday night",
        "One section of a flagged course on Friday night.",
        lambda o: o.friday_night,
    ),
    StageSpec(
        "room_changes", "Keep each professor in one room per day",
        "One extra room a professor teaches in on the same day.",
        lambda o: o.room_changes,
    ),
    StageSpec(
        "teaching_days", "Pack teaching into fewer days where asked",
        "One day on which a professor who asked for packed days teaches.",
        lambda o: o.pack_day_penalty,
    ),
    StageSpec(
        "preferences", "Match professors' preferences",
        "Preference points earned: course ranks, time-of-day scores, and preferred "
        "meeting lengths. Higher is better.",
        lambda o: o.remaining_preference_score(),
        maximise=True,
    ),
)


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
        self.active_rows = self.program.core_rows

    def _add_row(self, name: str, terms: dict[int, float], sense: Sense, rhs: float) -> None:
        row = Row(name, terms, sense, rhs)
        self.backend.add_rows([row])
        self.active_rows.append(row)

    def _optimise(self, spec: StageSpec, objective: LinearExpr) -> float:
        started = time.perf_counter()
        if self.values:
            self.backend.warm_start(self.values)
        self.progress(
            f"{len(self.stages) + 1}/{len(STAGES)} {spec.name} | starting search", stage="solving"
        )
        outcome = self.backend.optimise(
            objective, maximise=spec.maximise, gap=EXACT, time_limit=self.time_limit
        )
        if not outcome.usable:
            raise SolveError(spec.name, outcome.detail)
        self.values = outcome.values
        self._record(
            Stage(
                name=spec.name, value=outcome.objective,
                seconds=time.perf_counter() - started,
                proven=outcome.status is SolutionStatus.OPTIMAL,
                best_bound=outcome.best_bound, relative_gap=outcome.relative_gap,
                key=spec.key, meaning=spec.meaning, maximise=spec.maximise,
            )
        )
        return outcome.objective

    def _record(self, stage: Stage) -> None:
        self.stages.append(stage)
        status = (
            "bound certified" if stage.optimality_source == "lower_bound"
            else "optimal" if stage.proven else "search stopped"
        )
        bound = "n/a" if stage.best_bound is None else f"{stage.best_bound:g}"
        gap = "n/a" if stage.relative_gap is None else f"{100 * stage.relative_gap:.2f}%"
        self.progress(
            f"{len(self.stages)}/{len(STAGES)} {stage.name} | objective={stage.value:g} "
            f"bound={bound} gap={gap} elapsed={stage.seconds:.2f}s status={status}",
            stage="stage",
        )

    def _minimise_then_cap(self, spec: StageSpec, objective: LinearExpr) -> None:
        """Minimise, then hold the result as a ceiling for every later stage.

        Count objectives use an integer ceiling. Balance contains fractional
        teaching-hour units, so it retains its attained value within tolerance.
        """
        # The incumbent is feasible for the active model. If every objective
        # term is nonnegative and exactly zero, no search can improve it.
        # Use exact zero here: a near-zero float is not a bound certificate.
        if (
            self.values
            and len(self.values) == len(self.program.variables)
            and all(
                coefficient >= 0
                and self.program.variables[index].lower >= 0
                and coefficient * self.values[index] == 0
                for index, coefficient in objective.terms.items()
            )
            # A repaired incumbent is only a hint. Capping at zero from an
            # infeasible point would make the model itself infeasible.
            and _feasible(self.program, self.active_rows, self.values)
        ):
            value = 0.0
            self._record(Stage(
                spec.name, value, 0.0, True, "lower_bound", 0.0, 0.0,
                key=spec.key, meaning=spec.meaning,
            ))
        else:
            value = self._optimise(spec, objective)
        self._add_row(
            f"cap_{spec.key}",
            dict(objective.terms),
            Sense.LE,
            math.ceil(value - 1e-6) if spec.integral else value + 1e-6,
        )

    def run(
        self,
        objectives: Objectives,
        room_seed: Callable[[list[float]], list[float]] | None = None,
        deferred: Sequence[Row] = (),
    ) -> None:
        for spec in STAGES:
            if spec.key == "off_campus" and room_seed is not None:
                self.values = room_seed(self.values)
            # The preference rows come in only now. None of them can rule out a
            # solution -- each one just pins a variable a later goal reads -- so
            # carrying them through the stages above would have doubled the
            # matrix those stages search for no gain at all.
            if spec.key == "balance" and deferred:
                with self.progress.step("solving", "adding preference rows") as done:
                    self.backend.add_rows(deferred)
                    self.active_rows.extend(deferred)
                    self.values = _repair(self.program, self.values, deferred)
                    done(f"{len(deferred):,} rows")
            # The goals before this one do not read room-use auxiliaries, so an
            # incumbent may leave them at arbitrary feasible values. Rebuild them
            # so the actual room count is offered instead of rediscovered.
            if spec.key == "room_changes" and deferred:
                self.values = _repair(
                    self.program,
                    self.values,
                    deferred,
                    reset_prefixes=("uses_room[", "uses_physical_room_day["),
                )
            objective = spec.objective(objectives)
            if spec.maximise:
                self._optimise(spec, objective)
            else:
                self._minimise_then_cap(spec, objective)


def _satisfied(row: Row, lhs: float) -> bool:
    if row.sense is Sense.LE:
        return lhs <= row.rhs + 1e-6
    if row.sense is Sense.GE:
        return lhs >= row.rhs - 1e-6
    return abs(lhs - row.rhs) <= 1e-6


def _feasible(program: Program, rows: Sequence[Row], values: list[float]) -> bool:
    """Whether a point meets every bound, integrality requirement and row."""
    for variable, value in zip(program.variables, values, strict=True):
        if not variable.lower - 1e-6 <= value <= variable.upper + 1e-6:
            return False
        if variable.kind is not VarKind.CONTINUOUS and abs(value - round(value)) > 1e-6:
            return False
    return all(
        _satisfied(row, sum(c * values[i] for i, c in row.terms.items())) for row in rows
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


_DESCRIPTIONS = {
    "teaching_load_violation": "{0} teaches beyond their agreed load",
    "concurrency_self_violation": "Two sections of {0} meet at {2} ({1})",
    "concurrency_apart_violation": "{0} and {1} both meet at {3} ({2}) but must run apart",
    "concurrency_apart_overlap_violation":
        "{0} at {3} overlaps {1} at {4} ({2}) but they must run apart",
    "concurrency_together_violation":
        "{0} and {1} do not both meet at {3} ({2}) but must run together",
    "program_missing_violation":
        "{0} ({1}): students cannot fit {2} in without a clash or a scheduled section",
    "time_of_day_max": "Busiest time of day ({0})",
    "time_of_day_min": "Quietest time of day ({0})",
    "day_of_week_max": "Busiest weekday ({0})",
    "day_of_week_min": "Quietest weekday ({0})",
    "friday_night_violation": "{0} meets on Friday night",
    "teaches_day": "{0} teaches on {2} ({1})",
}


_WEEK = {day: index for index, day in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))}


def _describe_assignment(inst: Instance, key: AssignmentKey) -> str:
    who = "a part-timer" if key.professor == PART_TIMER else key.professor
    when = "no meeting time" if is_placeholder(key.timeslot) else key.timeslot
    pattern = inst.meeting_patterns.get(key.timeslot)
    if pattern is not None:
        # Generated bundle ids are hashes; say when it actually meets.
        when = ", ".join(
            f"{m.day} {m.start_minutes // 60:02d}:{m.start_minutes % 60:02d} "
            f"({m.duration_minutes} min)"
            for m in sorted(pattern.meetings, key=lambda m: (_WEEK.get(m.day, 7), m.start_minutes))
        )
    where = "off campus" if key.classroom == OFF_CAMPUS else f"room {key.classroom}"
    return f"{key.course} section {key.section} ({key.semester}): {who}, {when}, {where}"


def _stage_items(
    built: BuiltModel, objective: LinearExpr, values: list[float]
) -> list[StageItem]:
    """What adds to one goal's score in the final schedule, in plain words."""
    assignment_of = {variable: key for key, variable in built.assign.items()}
    items: dict[str, float] = defaultdict(float)
    for index, coefficient in objective.terms.items():
        amount = coefficient * values[index]
        if abs(values[index]) <= TOLERANCE:
            continue
        name = built.program.variables[index].name
        prefix, _, rest = name.partition("[")
        parts = rest.removesuffix("]").split(",")
        if index in assignment_of:
            description = _describe_assignment(built.instance, assignment_of[index])
        elif prefix in ("uses_room", "uses_physical_room_day"):
            # Rooms used on a day, minus one: report the day, not the terms.
            description = f"{parts[0]} changes rooms on {parts[2]} ({parts[1]})"
        else:
            template = _DESCRIPTIONS.get(prefix)
            description = template.format(*parts) if template else name
        items[description] += amount
    return sorted(
        (StageItem(description, amount) for description, amount in items.items()
         if abs(amount) > TOLERANCE),
        key=lambda item: (-abs(item.amount), item.description),
    )


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


def solve_instance(
    inst: Instance,
    progress: ProgressCallback | None = None,
    time_limit: float = MAX_TIME_LIMIT,
    solver: str = DEFAULT_BACKEND,
) -> Result:
    """Solve an already-validated instance.

    :param time_limit: seconds each stage may search, at most
        :data:`MAX_TIME_LIMIT`. Stopping early yields ``status="feasible"``
        rather than an error, provided a solution was found.
    :param solver: which backend to use; see :data:`scheduler.backends.BACKENDS`.
    """
    if not math.isfinite(time_limit) or not 0 < time_limit <= MAX_TIME_LIMIT:
        raise ValueError(
            f"time_limit must be more than 0 and at most {MAX_TIME_LIMIT:g} seconds per stage"
        )

    reporter = Progress(progress)
    reporter(inst.summary())

    # Preferences rank legal assignments; they do not revoke qualifications.
    # Even a load-feasible subset can exclude the only conflict-free timetable.
    built = build(inst, reporter)

    backend = open_backend(solver, threads=THREADS, seed=SEED)
    try:
        with reporter.step("solving", f"loading into {backend.name}"):
            backend.load(built.program)

        staged = _StagedSolve(backend, reporter, time_limit, built.program)
        seed = _placeholder_seed(built)
        # The seed places sections only; settle the rows that define a count
        # from them (a program course with nothing to pick) so it stays feasible.
        staged.values = _repair(
            built.program, seed,
            [row for row in built.program.core_rows if row.defines is not None],
        )
        staged.run(
            built.objectives,
            room_seed=lambda values: seed_physical_rooms(built, values),
            deferred=built.program.deferred_rows,
        )

        with reporter.step("exporting", "reading solution") as done:
            assignments = _extract(built, staged.values)
            done(f"{len(assignments):,} assignments")
    finally:
        backend.close()

    stages = []
    for spec, stage in zip(STAGES, staged.stages, strict=True):
        objective = spec.objective(built.objectives)
        final = sum(c * staged.values[i] for i, c in objective.terms.items())
        items = _stage_items(built, objective, staged.values)
        stages.append(replace(stage, final=final, items=items))
    return Result(
        status="optimal" if all(stage.proven for stage in stages) else "feasible",
        assignments=assignments,
        solver=backend.name,
        stages=stages,
    )


def solve(
    payload: Mapping[str, Any],
    progress: ProgressCallback | None = None,
    time_limit: float = MAX_TIME_LIMIT,
    solver: str = DEFAULT_BACKEND,
) -> Result:
    """Solve one workload-allocation instance.

    :param payload: normalized data returned by the YAML loader. See
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
