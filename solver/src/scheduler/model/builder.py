"""Build the mixed-integer program from a validated scheduling instance.

The formulation is the one written up in ``model/manuscript.tex``. This module
translates it into a solver-agnostic :class:`~scheduler.model.program.Program`; how
that gets solved is :mod:`scheduler.solve` and :mod:`scheduler.backends`.

Two things shape the code here.

*Coefficients are accumulated first, rows emitted second.* Walking the sparse
set of viable assignments and collecting terms per row means a row only exists
if something actually constrains it. Built the other way round — one row per
combination of the index sets — the great majority would come out empty and
vacuous, which on a real instance is tens of thousands of wasted rows.

*Everything is iterated in sorted order.* A MIP solver's answer depends on the
order rows and columns arrive in, and Python randomises string hashing per
process, so iterating a bare set would hand back a different schedule for the
same input on every run.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, NamedTuple

from ..config import (
    BIG_M,
    BLOCK_WEIGHTS,
    LARGE_SECTION,
    OFF_CAMPUS,
    PART_TIMER,
    Instance,
    SectionKey,
    is_placeholder,
    placeholder_for,
)
from ..progress import Progress
from .program import INFINITY, LinearExpr, Program, Sense, VarKind

__all__ = ["AssignmentKey", "BuiltModel", "ObjectiveComponent", "Objectives", "build"]

class AssignmentKey(NamedTuple):
    """The complete identity of an assignment decision variable."""

    professor: str
    course: str
    section: str
    semester: str
    time_of_day: str
    timeslot: str
    classroom: str

#: Coefficients being accumulated for one row, keyed by variable index.
Terms = dict[int, float]


@dataclass(frozen=True, slots=True)
class ObjectiveComponent:
    """One named contribution to the final preference objective."""

    name: str
    expression: LinearExpr
    weight: float
    label: str
    description: str


@dataclass(frozen=True, slots=True)
class Objectives:
    """The expressions the solve stages optimise, in priority order.

    The violation terms stand for things we would rather make hard constraints
    but cannot, because a real instance is often slightly impossible and
    "infeasible" helps nobody. They are minimised and capped first, so the later
    preference optimisation cannot buy comfort by breaking them.
    """

    # violations, minimised and capped first
    teaching_load: LinearExpr
    concurrency: LinearExpr
    placeholder_use: LinearExpr
    off_campus_use: LinearExpr
    part_timer_room_use: LinearExpr

    # soft costs
    time_of_day_spread: LinearExpr
    day_of_week_spread: LinearExpr
    block_violation: LinearExpr
    friday_night: LinearExpr
    room_changes: LinearExpr

    # preference rewards
    course_reward: LinearExpr
    time_reward: LinearExpr
    block_reward: LinearExpr
    pack_day_penalty: LinearExpr

    def remaining_preference_score(self) -> LinearExpr:
        """Positive preference rewards after all penalties have been capped."""
        return self.course_reward + self.time_reward + self.block_reward

    def preference_components(self) -> tuple[ObjectiveComponent, ...]:
        """Return the final objective's named, weighted components."""
        return (
            ObjectiveComponent(
                "time_of_day_spread", self.time_of_day_spread, -10.0,
                "Time-of-day spread", "Difference between the busiest and quietest times of day.",
            ),
            ObjectiveComponent(
                "day_of_week_spread", self.day_of_week_spread, -10.0,
                "Day-of-week spread", "Difference between the busiest and quietest days.",
            ),
            ObjectiveComponent(
                "block_violation", self.block_violation, -3.0,
                "Course block violations", "Assignments using a block a course does not prefer.",
            ),
            ObjectiveComponent(
                "friday_night", self.friday_night, -3.0,
                "Friday-night penalties", "Penalized courses assigned to Friday night.",
            ),
            ObjectiveComponent(
                "room_changes", self.room_changes, -3.0,
                "Room changes", "Additional rooms used by one professor on one day.",
            ),
            ObjectiveComponent(
                "course_reward", self.course_reward, 1.0,
                "Course preference rewards",
                "Points for assigning a professor to a preferred course.",
            ),
            ObjectiveComponent(
                "time_reward", self.time_reward, 1.0,
                "Time preference rewards",
                "Points for assigning a professor to a preferred time of day.",
            ),
            ObjectiveComponent(
                "block_reward", self.block_reward, 1.0,
                "Block preference rewards",
                "Points for assigning a professor to a preferred block.",
            ),
            ObjectiveComponent(
                "pack_day_penalty", self.pack_day_penalty, -1.0,
                "Additional teaching days",
                "Penalty for each extra day on which a professor teaches.",
            ),
        )


@dataclass(frozen=True, slots=True)
class BuiltModel:
    program: Program
    assign: dict[AssignmentKey, int]
    objectives: Objectives
    instance: Instance


@dataclass(frozen=True, slots=True)
class _Index:
    """Sorted sequences and reverse lookups, computed once.

    Every field replaces either a repeated ``sorted()`` call in a loop or a
    linear scan over a membership set.
    """

    professors: list[str]
    real_professors: list[str]
    courses: list[str]
    semesters: list[str]
    rooms: list[str]
    real_slots: list[str]
    days: list[str]
    times_of_day: list[str]
    blocks: list[str]

    slots_at: dict[str, list[str]]        # time of day -> real timeslots
    days_of: dict[str, list[str]]         # timeslot -> days of week
    times_of: dict[str, list[str]]        # timeslot -> times of day
    day_weight_of: dict[str, float]       # timeslot -> share of a day consumed
    overlap_pairs_of: dict[str, list[tuple[str, str]]]
    blocks_of: dict[str, list[str]]       # timeslot -> block types
    pairs_touching: dict[tuple[str, str], list[tuple[str, str, str]]]

    @classmethod
    def of(cls, inst: Instance) -> _Index:
        slots_at: dict[str, list[str]] = defaultdict(list)
        times_of: dict[str, list[str]] = defaultdict(list)
        for slot, time_of_day in sorted(inst.timeslot_time_of_day):
            times_of[slot].append(time_of_day)
            if not is_placeholder(slot):
                slots_at[time_of_day].append(slot)

        days_of: dict[str, list[str]] = defaultdict(list)
        for slot, day in sorted(inst.timeslot_day):
            days_of[slot].append(day)

        blocks_of: dict[str, list[str]] = defaultdict(list)
        day_weight_of: dict[str, float] = defaultdict(float)
        for slot, block in sorted(inst.timeslot_block):
            blocks_of[slot].append(block)
            # Summed rather than picked, so a slot mapped to several block types
            # still contributes all of them.
            day_weight_of[slot] += BLOCK_WEIGHTS[block]

        overlap_pairs_of: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for overlap_pair in sorted(inst.overlapping_timeslots):
            first, second = overlap_pair
            overlap_pairs_of[first].append(overlap_pair)
            overlap_pairs_of[second].append(overlap_pair)

        # Which concurrency pairs a (course, semester) takes part in, either side.
        pairs_touching: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
        for pairs in (inst.must_run_together, inst.must_not_overlap):
            for concurrency_pair in sorted(pairs):
                first, second, semester = concurrency_pair
                pairs_touching[(first, semester)].append(concurrency_pair)
                if second != first:
                    pairs_touching[(second, semester)].append(concurrency_pair)

        return cls(
            professors=sorted(inst.professors),
            real_professors=sorted(inst.real_professors),
            courses=sorted(inst.courses),
            semesters=sorted(inst.semesters),
            rooms=sorted(inst.classrooms),
            real_slots=sorted(inst.real_timeslots),
            days=sorted(inst.days_of_week),
            times_of_day=sorted(inst.times_of_day),
            blocks=sorted(inst.block_types),
            slots_at=dict(slots_at),
            days_of=dict(days_of),
            times_of=dict(times_of),
            day_weight_of=dict(day_weight_of),
            overlap_pairs_of=dict(overlap_pairs_of),
            blocks_of=dict(blocks_of),
            pairs_touching=dict(pairs_touching),
        )


def _viable_assignments(
    inst: Instance, index: _Index, progress: Progress | None = None
) -> list[AssignmentKey]:
    """Enumerate the assignments worth giving a variable to.

    The full product of professor x section x room x timeslot is enormous and
    almost all nonsense. Filtering here rather than with constraints is what
    keeps the model tractable, so each rule below removes a whole slice of it.
    """
    viable: list[AssignmentKey] = []

    for section_key in sorted(inst.section_keys):
        course, section, semester, time_of_day = section_key
        heads = inst.attendance[section_key]
        candidate_slots = index.slots_at.get(time_of_day, ())
        at_night = time_of_day == "Night"

        for professor in index.professors:
            part_timer = professor == PART_TIMER

            if not part_timer:
                if (professor, course) not in inst.qualifications:
                    continue
                if at_night and professor not in inst.can_teach_night:
                    continue

            # The escape hatch: every professor can fall back to a placeholder
            # slot, so an over-subscribed instance degrades instead of coming
            # back infeasible. A section that never meets occupies no room, so
            # this is one variable, not one per room the section will not use --
            # those extras were identical in meaning and differed only by a
            # label, which is precisely the symmetry branch and bound cannot
            # see through.
            viable.append(
                AssignmentKey(
                    professor,
                    course,
                    section,
                    semester,
                    time_of_day,
                    placeholder_for(time_of_day),
                    OFF_CAMPUS,
                )
            )

            for room in index.rooms:
                if room == OFF_CAMPUS:
                    # Only part-timers go off campus, unless the professor agreed.
                    if not part_timer and professor not in inst.can_teach_off_campus:
                        continue
                else:
                    # A real room must fit the section, and not be left mostly empty.
                    capacity = inst.classroom_capacity[room]
                    if heads > capacity or heads < inst.minimum_room_fill * capacity:
                        continue

                for slot in candidate_slots:
                    # A big section needing a 3-hour block has to run at night.
                    if (
                        heads > LARGE_SECTION
                        and "3.0" in index.blocks_of.get(slot, ())
                        and "Night" not in index.times_of.get(slot, ())
                    ):
                        continue
                    viable.append(
                        AssignmentKey(
                            professor, course, section, semester, time_of_day, slot, room
                        )
                    )
                if progress is not None and len(viable) % 25_000 == 0:
                    progress.update(f"{len(viable):,} assignments")

    return sorted(viable)


class _Builder:
    """Accumulates coefficients, then emits rows."""

    def __init__(self, inst: Instance, index: _Index) -> None:
        self.inst = inst
        self.ix = index
        self.program = Program()
        self.assign: dict[AssignmentKey, int] = {}

    # -- emitting -------------------------------------------------------- #

    def _emit(
        self,
        name: str,
        terms_by_key: Mapping[Any, Terms],
        sense: Sense,
        rhs: float | Mapping[Any, float] = 0.0,
        always: Iterable[Any] = (),
        deferred: bool = False,
        defines: Mapping[Any, int] | None = None,
    ) -> None:
        """Emit one row per key, in sorted order.

        Keys with no accumulated terms are skipped unless named in ``always``:
        such a row is vacuous and would only grow the model. The exceptions are
        rows whose emptiness is itself meaningful — a section nobody can teach,
        or a professor with no way to reach their load, must still produce an
        unsatisfiable row and be reported as infeasible.
        """
        for key in sorted(set(terms_by_key) | set(always), key=_label):
            bound = rhs[key] if isinstance(rhs, Mapping) else rhs
            self.program.add_row(
                f"{name}[{_label(key)}]",
                terms_by_key.get(key, {}),
                sense,
                bound,
                deferred=deferred,
                defines=None if defines is None else defines.get(key),
            )

    def _slack(self, name: str, key: Any) -> int:
        return self.program.add_variable(f"{name}[{_label(key)}]")

    # -- variables ------------------------------------------------------- #

    def add_assignment_variables(self, viable: list[AssignmentKey]) -> None:
        for key in viable:
            professor, slot, room = key.professor, key.timeslot, key.classroom
            # A named professor, in a real room, at a real time teaches a
            # section once or not at all. The fallbacks are counters, not
            # switches: many sections can pile onto "a part-timer", "off
            # campus", or "no slot yet".
            capped = professor != PART_TIMER and room != OFF_CAMPUS and not is_placeholder(slot)
            self.assign[key] = self.program.add_variable(
                f"assign[{_label(key)}]",
                upper=1.0 if capped else INFINITY,
                kind=VarKind.INTEGER,
            )

    # -- constraints ----------------------------------------------------- #

    def add_professor_constraints(self) -> tuple[LinearExpr, LinearExpr, LinearExpr]:
        """Returns teaching-load violation, pack-day penalty, and room spread."""
        inst, ix = self.inst, self.ix

        # Each section is taught exactly once, so a row counting assignment
        # variables can never exceed the number of distinct sections it touches.
        # That is the tight big-M; the constant is only the last-resort ceiling.
        sections_of = {
            variable: (key.course, key.section, key.semester, key.time_of_day)
            for key, variable in self.assign.items()
        }

        one_at_a_time: dict[tuple[str, str, str], Terms] = defaultdict(dict)
        load: dict[str, Terms] = defaultdict(dict)
        teaches: dict[tuple[str, str, str], Terms] = defaultdict(dict)
        uses_room: dict[tuple[str, str, str, str], Terms] = defaultdict(dict)

        for key, variable in self.assign.items():
            professor, semester, slot = key.professor, key.semester, key.timeslot
            if professor == PART_TIMER:
                continue
            load[professor][variable] = 1.0
            if not is_placeholder(slot):
                one_at_a_time[(professor, semester, slot)][variable] = 1.0
            for day in ix.days_of.get(slot, ()):
                teaches[(professor, semester, day)][variable] = 1.0
                if key.classroom != OFF_CAMPUS:
                    uses_room[(professor, semester, day, key.classroom)][variable] = 1.0

        self._emit("professor_one_at_a_time", one_at_a_time, Sense.LE, 1.0)

        # Everyone teaches their agreed load. The slack only permits teaching
        # *more* than agreed, never less — which is why asking for more
        # teachings in total than there are sections comes back infeasible.
        load_violation = LinearExpr()
        for professor in ix.real_professors:
            slack = self._slack("teaching_load_violation", professor)
            load[professor][slack] = -1.0
            load_violation.add(slack, 1.0)
        self._emit(
            "professor_teaching_load",
            load,
            Sense.EQ,
            {p: float(inst.teaching_load[p]) for p in ix.real_professors},
            always=ix.real_professors,
        )

        # Light up "taught something that day", then charge for it.
        pack_penalty = LinearExpr()
        teaches_indicator: dict[tuple[str, str, str], int] = {}
        for day_key in sorted(teaches, key=_label):
            professor, _, _ = day_key
            indicator = self.program.add_variable(
                f"teaches_day[{_label(day_key)}]", upper=1.0, kind=VarKind.BINARY
            )
            teaches[day_key][indicator] = -_big_m(teaches[day_key], sections_of)
            teaches_indicator[day_key] = indicator
            # Every day counts the same: the weight is the professor's own
            # preference, never the size of the day. (Resolved 2026-08-26.)
            pack_penalty.add(indicator, float(inst.pack_day_preference[professor]))
        self._emit(
            "professor_teaches_day", teaches, Sense.LE, 0.0,
            deferred=True, defines=teaches_indicator,
        )

        # Light up "used this room that day", then charge for every room past
        # the first: room-hopping between classes is pure discomfort.
        uses_indicator: dict[tuple[str, str, str, str], int] = {}
        for room_key in sorted(uses_room, key=_label):
            indicator = self.program.add_variable(
                f"uses_room[{_label(room_key)}]", upper=1.0, kind=VarKind.BINARY
            )
            uses_room[room_key][indicator] = -_big_m(uses_room[room_key], sections_of)
            uses_indicator[room_key] = indicator
        self._emit(
            "professor_uses_room", uses_room, Sense.LE, 0.0,
            deferred=True, defines=uses_indicator,
        )

        # Exact room changes need no slack variable: on a teaching day the
        # number of changes is physical rooms used minus one. A separate
        # physical-day indicator matters when someone teaches only off campus.
        physical_day_active: dict[tuple[str, str, str], Terms] = defaultdict(dict)
        for room_key, indicator in uses_indicator.items():
            professor, semester, day, _ = room_key
            physical_day_active[(professor, semester, day)][indicator] = -1.0
        physical_day_indicator: dict[tuple[str, str, str], int] = {}
        physical_day_forced: dict[tuple[str, str, str], Terms] = {}
        for day_key in sorted(physical_day_active, key=_label):
            room_indicators = {
                room_indicator: -coefficient
                for room_indicator, coefficient in physical_day_active[day_key].items()
            }
            indicator = self.program.add_variable(
                f"uses_physical_room_day[{_label(day_key)}]",
                upper=1.0,
                kind=VarKind.BINARY,
            )
            physical_day_active[day_key][indicator] = 1.0
            physical_day_forced[day_key] = room_indicators | {
                indicator: -float(len(room_indicators))
            }
            physical_day_indicator[day_key] = indicator
        self._emit(
            "professor_uses_physical_day_forced", physical_day_forced, Sense.LE, 0.0,
            deferred=True, defines=physical_day_indicator,
        )
        self._emit(
            "professor_uses_physical_day", physical_day_active, Sense.LE, 0.0,
            deferred=True,
        )

        room_changes = LinearExpr()
        for indicator in uses_indicator.values():
            room_changes.add(indicator, 1.0)
        for indicator in physical_day_indicator.values():
            room_changes.add(indicator, -1.0)

        self._add_overlap_rows(
            "professor_no_overlap", owner=lambda key: key.professor, skip=PART_TIMER
        )
        return load_violation, pack_penalty, room_changes

    def _add_overlap_rows(
        self, name: str, owner: Callable[[AssignmentKey], str], skip: str
    ) -> None:
        """Stop one professor, or one room, being claimed by two overlapping slots."""
        rows: dict[tuple[str, str, str, str], Terms] = defaultdict(dict)
        for key, variable in self.assign.items():
            semester, slot = key.semester, key.timeslot
            held_by = owner(key)
            if held_by == skip:
                continue
            for first, second in self.ix.overlap_pairs_of.get(slot, ()):
                rows[(held_by, semester, first, second)][variable] = 1.0
        self._emit(name, rows, Sense.LE, 1.0)

    def add_balance_constraints(self) -> tuple[LinearExpr, LinearExpr]:
        """Spread teaching evenly across times of day, and across weekdays.

        Every bucket is pinned between a max and a min variable, and the
        objective pays for the gap. Unlike everywhere else these rows are
        emitted even when empty: a time of day nobody teaches genuinely drags
        the minimum to zero, and that widened spread is signal, not noise.
        """
        ix = self.ix
        spreads: list[LinearExpr] = []

        groups: tuple[tuple[str, list[str], dict[str, list[str]], dict[str, float] | None], ...] = (
            ("time_of_day", ix.times_of_day, ix.times_of, None),
            ("day_of_week", ix.days, ix.days_of, ix.day_weight_of),
        )
        for label, buckets, buckets_of, weight_of in groups:
            keys = [(semester, bucket) for semester in ix.semesters for bucket in buckets]
            upper: dict[tuple[str, str], Terms] = {key: {} for key in keys}
            lower: dict[tuple[str, str], Terms] = {key: {} for key in keys}

            for key, variable in self.assign.items():
                semester, slot = key.semester, key.timeslot
                weight = 1.0 if weight_of is None else weight_of.get(slot, 0.0)
                if not weight:
                    continue
                for bucket in buckets_of.get(slot, ()):
                    upper[(semester, bucket)][variable] = weight
                    lower[(semester, bucket)][variable] = weight

            spread = LinearExpr()
            defines_high: dict[tuple[str, str], int] = {}
            defines_low: dict[tuple[str, str], int] = {}
            for semester in ix.semesters:
                bound = max(
                    (sum(upper[(semester, bucket)].values()) for bucket in buckets),
                    default=0.0,
                )
                high = self.program.add_variable(f"{label}_max[{semester}]", upper=bound)
                low = self.program.add_variable(f"{label}_min[{semester}]", upper=bound)
                spread.add(high, 1.0).add(low, -1.0)
                for bucket in buckets:
                    upper[(semester, bucket)][high] = -1.0
                    lower[(semester, bucket)][low] = -1.0
                    defines_high[(semester, bucket)] = high
                    defines_low[(semester, bucket)] = low

            self._emit(
                f"{label}_max", upper, Sense.LE, 0.0,
                always=keys, deferred=True, defines=defines_high,
            )
            self._emit(
                f"{label}_min", lower, Sense.GE, 0.0,
                always=keys, deferred=True, defines=defines_low,
            )
            spreads.append(spread)

        return spreads[0], spreads[1]

    def add_classroom_constraints(self) -> None:
        rows: dict[tuple[str, str, str], Terms] = defaultdict(dict)
        for key, variable in self.assign.items():
            semester, slot, room = key.semester, key.timeslot, key.classroom
            if room != OFF_CAMPUS and not is_placeholder(slot):
                rows[(room, semester, slot)][variable] = 1.0
        self._emit("classroom_once", rows, Sense.LE, 1.0)
        self._add_overlap_rows(
            "classroom_no_overlap", owner=lambda key: key.classroom, skip=OFF_CAMPUS
        )

    def add_course_constraints(self) -> tuple[LinearExpr, LinearExpr]:
        """Returns the block-preference and Friday-night penalty expressions."""
        inst, ix = self.inst, self.ix

        taught: dict[tuple[str, str, str, str], Terms] = defaultdict(dict)
        fridays: dict[str, Terms] = defaultdict(dict)

        preferred_blocks: dict[str, set[str]] = defaultdict(set)
        for course, block in inst.course_block_preference:
            preferred_blocks[course].add(block)

        block_penalty = LinearExpr()

        for key, variable in self.assign.items():
            course = key.course
            section_key = (course, key.section, key.semester, key.time_of_day)
            taught[section_key][variable] = 1.0
            preferred = preferred_blocks.get(course)
            if preferred and preferred.isdisjoint(ix.blocks_of.get(key.timeslot, ())):
                block_penalty.add(variable)
            if (
                course in inst.friday_night_penalty
                and "Fri" in ix.days_of.get(key.timeslot, ())
                and "Night" in ix.times_of.get(key.timeslot, ())
            ):
                fridays[course][variable] = 1.0

        # Every section is taught exactly once. The only row with no slack: the
        # fallbacks exist so it can always be satisfied. `always` matters here —
        # a section with no viable assignment has to fail loudly.
        self._emit(
            "section_taught_once", taught, Sense.EQ, 1.0, always=inst.section_keys
        )

        friday_penalty = LinearExpr()
        friday_slack: dict[str, int] = {}
        for course in sorted(fridays, key=_label):
            slack = self._slack("friday_night_violation", course)
            fridays[course][slack] = -1.0
            friday_slack[course] = slack
            friday_penalty.add(slack, 1.0)
        self._emit(
            "course_friday_night", fridays, Sense.EQ, 0.0,
            deferred=True, defines=friday_slack,
        )

        return block_penalty, friday_penalty

    def add_concurrency_constraints(self) -> LinearExpr:
        """Sections of related courses should not collide in time."""
        inst, ix = self.inst, self.ix

        against_self: dict[tuple[str, str, str], Terms] = defaultdict(dict)
        together: dict[tuple[str, str, str, str], Terms] = defaultdict(dict)
        apart: dict[tuple[str, str, str, str], Terms] = defaultdict(dict)
        apart_overlap: dict[tuple[str, str, str, str, str], Terms] = defaultdict(dict)

        for key, variable in self.assign.items():
            professor = key.professor
            course, semester, slot = key.course, key.semester, key.timeslot
            if professor == PART_TIMER or is_placeholder(slot):
                continue
            against_self[(course, semester, slot)][variable] = 1.0
            for pair in ix.pairs_touching.get((course, semester), ()):
                if pair in inst.must_run_together:
                    first, _, _ = pair
                    together[(*pair, slot)][variable] = 1.0 if course == first else -1.0
                else:
                    apart[(*pair, slot)][variable] = 1.0
                    first, second, _ = pair
                    if first == second:
                        continue
                    # Keep the two courses on opposite ends of an overlap edge.
                    # Combining both courses at both ends would also penalise
                    # sections of just one course, changing the self rule.
                    for left, right in ix.overlap_pairs_of.get(slot, ()):
                        other = right if slot == left else left
                        if other == slot or is_placeholder(other):
                            continue
                        slots = (slot, other) if course == first else (other, slot)
                        apart_overlap[(*pair, *slots)][variable] = 1.0

        violation = LinearExpr()
        groups: tuple[tuple[str, dict[Any, Terms], Sense, float], ...] = (
            ("concurrency_self", against_self, Sense.LE, 1.0),
            ("concurrency_apart", apart, Sense.LE, 1.0),
            ("concurrency_apart_overlap", apart_overlap, Sense.LE, 1.0),
        )
        for name, rows, sense, rhs in groups:
            for row_key in sorted(rows, key=_label):
                slack = self._slack(f"{name}_violation", row_key)
                rows[row_key][slack] = -1.0
                violation.add(slack, 1.0)
            self._emit(name, rows, sense, rhs)

        together_upper: dict[tuple[str, str, str, str], Terms] = {}
        together_lower: dict[tuple[str, str, str, str], Terms] = {}
        for row_key, difference in sorted(together.items()):
            slack = self._slack("concurrency_together_violation", row_key)
            together_upper[row_key] = {**difference, slack: -1.0}
            together_lower[row_key] = {
                variable: -coefficient for variable, coefficient in difference.items()
            }
            together_lower[row_key][slack] = -1.0
            violation.add(slack)
        self._emit("concurrency_together_upper", together_upper, Sense.LE)
        self._emit("concurrency_together_lower", together_lower, Sense.LE)

        return violation

    # -- objective terms -------------------------------------------------- #

    def preference_terms(self) -> tuple[LinearExpr, LinearExpr, LinearExpr]:
        inst, ix = self.inst, self.ix
        course_reward, time_reward, block_reward = LinearExpr(), LinearExpr(), LinearExpr()

        for key, variable in self.assign.items():
            professor = key.professor
            course, semester, slot = key.course, key.semester, key.timeslot

            weight = inst.course_preference.get((professor, course))
            if weight:
                course_reward.add(variable, weight)

            for time_of_day in ix.times_of.get(slot, ()):
                preferred = inst.time_preference.get((professor, semester, time_of_day))
                if preferred:
                    time_reward.add(variable, preferred)

            for block in ix.blocks_of.get(slot, ()):
                if (professor, block) in inst.block_preference:
                    block_reward.add(variable, 1.0)

        return course_reward, time_reward, block_reward

    def fallback_terms(self) -> tuple[LinearExpr, LinearExpr, LinearExpr]:
        """The two escape hatches, counted separately.

        A section on a placeholder slot never meets, so it is not being taught
        off campus -- it is not being taught at all. Counting it in both charged
        the same failure twice, once in the stage that caps unscheduled sections
        and again in the stage that minimises off-campus teaching.
        """
        placeholder_use, off_campus_use = LinearExpr(), LinearExpr()
        part_timer_room_use = LinearExpr()
        for key, variable in self.assign.items():
            if is_placeholder(key.timeslot):
                placeholder_use.add(variable, 1.0)
            elif key.classroom == OFF_CAMPUS:
                off_campus_use.add(variable, 1.0)
            elif key.professor == PART_TIMER:
                # Physical rooms are scarce. If the total room use is tied,
                # give them to named faculty before the fallback professor.
                part_timer_room_use.add(variable, 1.0)
        return placeholder_use, off_campus_use, part_timer_room_use




def _big_m(terms: Terms, sections_of: Mapping[int, SectionKey]) -> float:
    """The tightest valid ceiling for an indicator row over assignment variables.

    Every section is taught exactly once, so however many variables a row
    counts, the sum cannot pass the number of distinct sections among them. The
    constant :data:`~scheduler.config.BIG_M` stays as the ceiling for anything
    that somehow counts more, which keeps the row valid in every case.
    """
    sections = {sections_of[variable] for variable in terms if variable in sections_of}
    return float(min(len(sections) or BIG_M, BIG_M))


def _label(key: Any) -> str:
    return ",".join(str(part) for part in key) if isinstance(key, tuple) else str(key)


def _maximal_slot_cliques(
    slots: Iterable[str], overlap_pairs_of: Mapping[str, Iterable[tuple[str, str]]]
) -> list[tuple[str, ...]]:
    """Return maximal sets of pairwise-overlapping real timeslots."""
    vertices = set(slots)
    adjacent = {slot: set[str]() for slot in vertices}
    for pairs in overlap_pairs_of.values():
        for first, second in pairs:
            # Clique enumeration requires a graph without self-edges.
            if first != second and first in vertices and second in vertices:
                adjacent[first].add(second)
                adjacent[second].add(first)

    cliques: list[tuple[str, ...]] = []

    def visit(chosen: set[str], candidates: set[str], excluded: set[str]) -> None:
        if not candidates and not excluded:
            cliques.append(tuple(sorted(chosen)))
            return
        pivot_pool = candidates | excluded
        pivot = max(
            pivot_pool,
            key=lambda slot: (len(candidates & adjacent[slot]), slot),
            default=None,
        )
        remaining = candidates - (adjacent[pivot] if pivot is not None else set())
        for slot in sorted(remaining):
            visit(
                chosen | {slot},
                candidates & adjacent[slot],
                excluded & adjacent[slot],
            )
            candidates.remove(slot)
            excluded.add(slot)

    visit(set(), set(vertices), set())
    return sorted(cliques)


def build(inst: Instance, progress: Progress) -> BuiltModel:
    """Translate an instance into a solver-agnostic program."""
    index = _Index.of(inst)
    builder = _Builder(inst, index)

    with progress.step("building", "enumerating viable assignments") as done:
        viable = _viable_assignments(inst, index, progress)
        builder.add_assignment_variables(viable)
        done(f"{len(viable):,} assignments")

    before_rows = len(builder.program.rows)
    with progress.step("building", "professor constraints") as done:
        teaching_load, pack_day_penalty, room_changes = builder.add_professor_constraints()
        done(f"{len(builder.program.rows) - before_rows:,} rows")
    before_rows = len(builder.program.rows)
    with progress.step("building", "balance constraints") as done:
        time_spread, day_spread = builder.add_balance_constraints()
        done(f"{len(builder.program.rows) - before_rows:,} rows")
    before_rows = len(builder.program.rows)
    with progress.step("building", "classroom constraints") as done:
        builder.add_classroom_constraints()
        done(f"{len(builder.program.rows) - before_rows:,} rows")
    before_rows = len(builder.program.rows)
    with progress.step("building", "course constraints") as done:
        block_violation, friday_night = builder.add_course_constraints()
        done(f"{len(builder.program.rows) - before_rows:,} rows")
    before_rows = len(builder.program.rows)
    with progress.step("building", "concurrency constraints") as done:
        concurrency = builder.add_concurrency_constraints()
        done(f"{len(builder.program.rows) - before_rows:,} rows")

    with progress.step("building", "objective terms") as done:
        course_reward, time_reward, block_reward = builder.preference_terms()
        placeholder_use, off_campus_use, part_timer_room_use = builder.fallback_terms()
        program = builder.program
        done(
            f"{len(program.variables):,} variables, {len(program.rows):,} rows, "
            f"{program.nonzeros:,} nonzeros"
        )

    objectives = Objectives(
        teaching_load=teaching_load,
        concurrency=concurrency,
        placeholder_use=placeholder_use,
        off_campus_use=off_campus_use,
        part_timer_room_use=part_timer_room_use,
        time_of_day_spread=time_spread,
        day_of_week_spread=day_spread,
        block_violation=block_violation,
        friday_night=friday_night,
        room_changes=room_changes,
        course_reward=course_reward,
        time_reward=time_reward,
        block_reward=block_reward,
        pack_day_penalty=pack_day_penalty,
    )
    return BuiltModel(program=program, assign=builder.assign, objectives=objectives, instance=inst)
