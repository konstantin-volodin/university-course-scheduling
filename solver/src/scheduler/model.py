"""Builds the mixed-integer program from an :class:`~scheduler.instance.Instance`.

The formulation is the one written up in ``model/manuscript.tex``. This module
translates it into a solver-agnostic :class:`~scheduler.program.Program`; how
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
from itertools import product
from typing import Any

from .instance import (
    BIG_M,
    BLOCK_WEIGHTS,
    LARGE_SECTION,
    MIN_ROOM_FILL,
    OFF_CAMPUS,
    PART_TIMER,
    Instance,
    is_placeholder,
    placeholder_for,
)
from .program import INFINITY, LinearExpr, Program, Sense, VarKind
from .progress import Progress

__all__ = ["AssignmentKey", "BuiltModel", "Objectives", "build"]

#: A decision variable's identity: who teaches what, when, where.
#: (professor, course, section, semester, time of day, timeslot, classroom)
#:
#: Time of day remains explicit even though a real timeslot normally implies it.
#: Placeholder slots and malformed legacy payloads make that implication unsafe,
#: while :class:`SectionKey` promises that time of day is part of section identity.
AssignmentKey = tuple[str, str, str, str, str, str, str]

#: Coefficients being accumulated for one row, keyed by variable index.
Terms = dict[int, float]


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

    # soft costs
    time_of_day_spread: LinearExpr
    day_of_week_spread: LinearExpr
    block_violation: LinearExpr
    friday_night: LinearExpr

    # preference rewards
    course_reward: LinearExpr
    time_reward: LinearExpr
    block_reward: LinearExpr
    pack_day_penalty: LinearExpr

    def preference_score(self) -> LinearExpr:
        """The final objective: preferences, inside everything already capped.

        These weights only trade preferences against each other. Nothing here
        can buy its way out of a violation, because those are frozen by now.
        """
        score = LinearExpr()
        score.extend(self.time_of_day_spread, -10.0)
        score.extend(self.day_of_week_spread, -10.0)
        score.extend(self.block_violation, -3.0)
        score.extend(self.friday_night, -3.0)
        score.extend(self.course_reward, 1.0)
        score.extend(self.time_reward, 1.0)
        score.extend(self.block_reward, 1.0)
        score.extend(self.pack_day_penalty, -1.0)
        return score


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
    partners_of: dict[str, list[str]]     # timeslot -> overlapping timeslots
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

        partners_of: dict[str, list[str]] = defaultdict(list)
        for slot, other in sorted(inst.overlapping_timeslots):
            partners_of[slot].append(other)

        # Which concurrency pairs a (course, semester) takes part in, either side.
        pairs_touching: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
        for pairs in (inst.must_run_together, inst.must_not_overlap):
            for pair in sorted(pairs):
                first, second, semester = pair
                pairs_touching[(first, semester)].append(pair)
                if second != first:
                    pairs_touching[(second, semester)].append(pair)

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
            partners_of=dict(partners_of),
            blocks_of=dict(blocks_of),
            pairs_touching=dict(pairs_touching),
        )


def _viable_assignments(inst: Instance, index: _Index) -> list[AssignmentKey]:
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

        for professor, room in product(index.professors, index.rooms):
            part_timer = professor == PART_TIMER

            if not part_timer:
                if (professor, course) not in inst.qualifications:
                    continue
                if at_night and professor not in inst.can_teach_night:
                    continue

            if room == OFF_CAMPUS:
                # Only part-timers go off campus, unless the professor agreed.
                if not part_timer and professor not in inst.can_teach_off_campus:
                    continue
            else:
                # A real room must fit the section, and not be left mostly empty.
                capacity = inst.classroom_capacity[room]
                if heads > capacity or heads < MIN_ROOM_FILL * capacity:
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
                    (professor, course, section, semester, time_of_day, slot, room)
                )

            # The escape hatch: every combination can fall back to a placeholder
            # slot, so an over-subscribed instance degrades instead of coming
            # back infeasible.
            viable.append(
                (
                    professor,
                    course,
                    section,
                    semester,
                    time_of_day,
                    placeholder_for(time_of_day),
                    room,
                )
            )

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
                f"{name}[{_label(key)}]", terms_by_key.get(key, {}), sense, bound
            )

    def _slack(self, name: str, key: Any) -> int:
        return self.program.add_variable(f"{name}[{_label(key)}]")

    # -- variables ------------------------------------------------------- #

    def add_assignment_variables(self, viable: list[AssignmentKey]) -> None:
        for key in viable:
            professor, _, _, _, _, slot, room = key
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

    def add_professor_constraints(self) -> tuple[LinearExpr, LinearExpr]:
        """Returns the teaching-load violation and pack-day penalty expressions."""
        inst, ix = self.inst, self.ix

        one_at_a_time: dict[tuple[str, str, str], Terms] = defaultdict(dict)
        load: dict[str, Terms] = defaultdict(dict)
        teaches: dict[tuple[str, str, str], Terms] = defaultdict(dict)

        for key, variable in self.assign.items():
            professor, _, _, semester, _, slot, _ = key
            if professor == PART_TIMER:
                continue
            load[professor][variable] = 1.0
            if not is_placeholder(slot):
                one_at_a_time[(professor, semester, slot)][variable] = 1.0
            for day in ix.days_of.get(slot, ()):
                teaches[(professor, semester, day)][variable] = 1.0

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
        for day_key in sorted(teaches, key=_label):
            professor, _, _ = day_key
            indicator = self.program.add_variable(
                f"teaches_day[{_label(day_key)}]", upper=1.0, kind=VarKind.BINARY
            )
            teaches[day_key][indicator] = -float(BIG_M)
            # Every day counts the same: the weight is the professor's own
            # preference, never the size of the day. (Resolved 2026-08-26.)
            pack_penalty.add(indicator, float(inst.pack_day_preference[professor]))
        self._emit("professor_teaches_day", teaches, Sense.LE, 0.0)

        self._add_overlap_rows("professor_no_overlap", owner=lambda key: key[0], skip=PART_TIMER)
        return load_violation, pack_penalty

    def _add_overlap_rows(
        self, name: str, owner: Callable[[AssignmentKey], str], skip: str
    ) -> None:
        """Stop one professor, or one room, being claimed by two overlapping slots."""
        rows: dict[tuple[str, str, str, str], Terms] = defaultdict(dict)
        for key, variable in self.assign.items():
            professor, course, section, semester, time_of_day, slot, room = key
            held_by = owner(key)
            if held_by == skip:
                continue
            for other in self.ix.partners_of.get(slot, ()):
                twin = (
                    professor,
                    course,
                    section,
                    semester,
                    time_of_day,
                    other,
                    room,
                )
                twin_variable = self.assign.get(twin)
                if twin_variable is not None:
                    row = rows[(held_by, semester, slot, other)]
                    row[variable] = 1.0
                    row[twin_variable] = 1.0
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
                _, _, _, semester, _, slot, _ = key
                weight = 1.0 if weight_of is None else weight_of.get(slot, 0.0)
                if not weight:
                    continue
                for bucket in buckets_of.get(slot, ()):
                    upper[(semester, bucket)][variable] = weight
                    lower[(semester, bucket)][variable] = weight

            spread = LinearExpr()
            for semester in ix.semesters:
                high = self.program.add_variable(f"{label}_max[{semester}]")
                low = self.program.add_variable(f"{label}_min[{semester}]")
                spread.add(high, 1.0).add(low, -1.0)
                for bucket in buckets:
                    upper[(semester, bucket)][high] = -1.0
                    lower[(semester, bucket)][low] = -1.0

            self._emit(f"{label}_max", upper, Sense.LE, 0.0, always=keys)
            self._emit(f"{label}_min", lower, Sense.GE, 0.0, always=keys)
            spreads.append(spread)

        return spreads[0], spreads[1]

    def add_classroom_constraints(self) -> None:
        rows: dict[tuple[str, str, str], Terms] = defaultdict(dict)
        for key, variable in self.assign.items():
            _, _, _, semester, _, slot, room = key
            if room != OFF_CAMPUS and not is_placeholder(slot):
                rows[(room, semester, slot)][variable] = 1.0
        self._emit("classroom_once", rows, Sense.LE, 1.0)
        self._add_overlap_rows("classroom_no_overlap", owner=lambda key: key[6], skip=OFF_CAMPUS)

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
            _, course, section, semester, time_of_day, slot, _ = key
            taught[(course, section, semester, time_of_day)][variable] = 1.0
            preferred = preferred_blocks.get(course)
            if preferred and preferred.isdisjoint(ix.blocks_of.get(slot, ())):
                block_penalty.add(variable)
            if (
                course in inst.friday_night_penalty
                and "Fri" in ix.days_of.get(slot, ())
                and "Night" in ix.times_of.get(slot, ())
            ):
                fridays[course][variable] = 1.0

        # Every section is taught exactly once. The only row with no slack: the
        # fallbacks exist so it can always be satisfied. `always` matters here —
        # a section with no viable assignment has to fail loudly.
        self._emit(
            "section_taught_once", taught, Sense.EQ, 1.0, always=inst.section_keys
        )

        friday_penalty = LinearExpr()
        for course in sorted(fridays, key=_label):
            slack = self._slack("friday_night_violation", course)
            fridays[course][slack] = -1.0
            friday_penalty.add(slack, 1.0)
        self._emit("course_friday_night", fridays, Sense.EQ, 0.0)

        return block_penalty, friday_penalty

    def add_concurrency_constraints(self) -> LinearExpr:
        """Sections of related courses should not collide in time."""
        inst, ix = self.inst, self.ix

        against_self: dict[tuple[str, str, str], Terms] = defaultdict(dict)
        together: dict[tuple[str, str, str, str], Terms] = defaultdict(dict)
        apart: dict[tuple[str, str, str, str], Terms] = defaultdict(dict)

        for key, variable in self.assign.items():
            professor, course, _, semester, _, slot, _ = key
            if professor == PART_TIMER or is_placeholder(slot):
                continue
            against_self[(course, semester, slot)][variable] = 1.0
            for pair in ix.pairs_touching.get((course, semester), ()):
                if pair in inst.must_run_together:
                    first, _, _ = pair
                    together[(*pair, slot)][variable] = 1.0 if course == first else -1.0
                else:
                    apart[(*pair, slot)][variable] = 1.0

        violation = LinearExpr()
        groups: tuple[tuple[str, dict[Any, Terms], Sense, float], ...] = (
            ("concurrency_self", against_self, Sense.LE, 1.0),
            ("concurrency_apart", apart, Sense.LE, 1.0),
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
            professor, course, _, semester, _, slot, _ = key

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

    def fallback_terms(self) -> tuple[LinearExpr, LinearExpr]:
        placeholder_use, off_campus_use = LinearExpr(), LinearExpr()
        for key, variable in self.assign.items():
            if is_placeholder(key[5]):
                placeholder_use.add(variable, 1.0)
            if key[6] == OFF_CAMPUS:
                off_campus_use.add(variable, 1.0)
        return placeholder_use, off_campus_use




def _label(key: Any) -> str:
    return ",".join(str(part) for part in key) if isinstance(key, tuple) else str(key)


def build(inst: Instance, progress: Progress) -> BuiltModel:
    """Translate an instance into a solver-agnostic program."""
    index = _Index.of(inst)
    builder = _Builder(inst, index)

    with progress.step("building", "enumerating viable assignments") as done:
        viable = _viable_assignments(inst, index)
        builder.add_assignment_variables(viable)
        done(f"{len(viable):,} assignments")

    with progress.step("building", "professor constraints"):
        teaching_load, pack_day_penalty = builder.add_professor_constraints()
    with progress.step("building", "balance constraints"):
        time_spread, day_spread = builder.add_balance_constraints()
    with progress.step("building", "classroom constraints"):
        builder.add_classroom_constraints()
    with progress.step("building", "course constraints"):
        block_violation, friday_night = builder.add_course_constraints()
    with progress.step("building", "concurrency constraints"):
        concurrency = builder.add_concurrency_constraints()

    with progress.step("building", "objective terms") as done:
        course_reward, time_reward, block_reward = builder.preference_terms()
        placeholder_use, off_campus_use = builder.fallback_terms()
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
        time_of_day_spread=time_spread,
        day_of_week_spread=day_spread,
        block_violation=block_violation,
        friday_night=friday_night,
        course_reward=course_reward,
        time_reward=time_reward,
        block_reward=block_reward,
        pack_day_penalty=pack_day_penalty,
    )
    return BuiltModel(program=program, assign=builder.assign, objectives=objectives, instance=inst)
