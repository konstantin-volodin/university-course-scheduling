"""The input contract: raw JSON payload in, validated :class:`Instance` out.

The payload is keyed by endpoint name — one key per ``/OPTIM_data/`` endpoint,
holding exactly what that endpoint returns. Keeping the wire format identical to
what the backend already serves means no translation layer has to exist on
either side.

Everything defensive lives here. Once you hold an :class:`Instance`, the model
builder can index into it without guarding, because the references have already
been checked.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from .errors import InvalidInstanceError

__all__ = [
    "OFF_CAMPUS",
    "PART_TIMER",
    "PAYLOAD_KEYS",
    "PLACEHOLDER_PREFIX",
    "Instance",
    "SectionKey",
    "is_placeholder",
    "placeholder_for",
]

#: A section is identified by this 4-tuple everywhere: course, section,
#: semester, time of day.
SectionKey = tuple[str, str, str, str]

#: Reserved id for "no named professor" — the fallback that keeps an
#: unassignable section from making the whole model infeasible.
PART_TIMER: Final = "part-timer"

#: Reserved id for "not one of our rooms".
OFF_CAMPUS: Final = "other"

#: Reserved timeslot prefix for "scheduled, but no real slot was available".
PLACEHOLDER_PREFIX: Final = "placeholder_"

RESERVED_IDS: Final = frozenset({PART_TIMER, OFF_CAMPUS})

#: Weight of each block type when measuring how loaded a day is.
BLOCK_WEIGHTS: Final[Mapping[str, float]] = {"1.5": 0.5, "3.0": 1.0}

#: Attendance above this must be scheduled at night if it needs a 3-hour block.
LARGE_SECTION: Final = 75

#: A room may not be filled below this fraction of its capacity.
MIN_ROOM_FILL: Final = 0.8

#: Big-M for the "did this professor teach at all that day" indicator.
BIG_M: Final = 1000


def placeholder_for(time_of_day: str) -> str:
    return f"{PLACEHOLDER_PREFIX}{time_of_day}"


def is_placeholder(timeslot: str) -> bool:
    return timeslot.startswith(PLACEHOLDER_PREFIX)


#: Every payload key read, in the order they are documented. One per endpoint.
PAYLOAD_KEYS: Final[tuple[str, ...]] = (
    # sets
    "professor_set",
    "course_set",
    "section_set",
    "classroom_set",
    "semester_set",
    "timeslot_set",
    "time_of_day_set",
    "day_of_week_set",
    "block_type_set",
    # subsets
    "section_subset",
    "timeslot_dow_subset",
    "timeslot_tod_subset",
    "timeslot_block_subset",
    # parameters
    "timeslot_concurrency",
    "professor_teaching",
    "professor_qualification",
    "professor_can_teach_night",
    "professor_can_teach_out_DMS",
    "professor_course_pref",
    "professor_time_pref",
    "professor_block_pref",
    "professor_pack_day_pref",
    "classroom_cap",
    "section_attendance",
    "course_concurrency_t",
    "course_concurrency_nt",
    "course_friday_penalty",
    "course_block_pref",
)


# --------------------------------------------------------------------------- #
# payload shape helpers
# --------------------------------------------------------------------------- #

def _require_list(payload: Mapping[str, Any], key: str, problems: list[str]) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        problems.append(f"{key}: expected a list, got {type(value).__name__}")
        return []
    return value


def _ids(payload: Mapping[str, Any], key: str, problems: list[str]) -> frozenset[str]:
    """``["a", "b"]`` -> ``{"a", "b"}``."""
    out: set[str] = set()
    for i, item in enumerate(_require_list(payload, key, problems)):
        if not isinstance(item, str):
            problems.append(f"{key}[{i}]: expected a string id, got {item!r}")
            continue
        out.add(item)
    return frozenset(out)


def _tuples(
    payload: Mapping[str, Any], key: str, width: int, problems: list[str]
) -> frozenset[Any]:
    """``[["a", "b"], ...]`` -> ``{("a", "b"), ...}``.

    Returns ``frozenset[Any]`` because the tuple width is only known at the call
    site; each caller annotates the exact shape it asked for.
    """
    out: set[tuple[str, ...]] = set()
    for i, item in enumerate(_require_list(payload, key, problems)):
        if not isinstance(item, Sequence) or isinstance(item, str) or len(item) != width:
            problems.append(f"{key}[{i}]: expected {width} values, got {item!r}")
            continue
        out.add(tuple(str(v) for v in item))
    return frozenset(out)


def _merged_mapping(
    payload: Mapping[str, Any], key: str, problems: list[str]
) -> dict[str, Any]:
    """``[{"a": 1}, {"b": 2}]`` -> ``{"a": 1, "b": 2}``.

    The endpoints emit one single-entry object per row rather than one object.
    """
    out: dict[str, Any] = {}
    for i, item in enumerate(_require_list(payload, key, problems)):
        if not isinstance(item, Mapping):
            problems.append(f"{key}[{i}]: expected an object, got {item!r}")
            continue
        for name, value in item.items():
            out[str(name)] = value
    return out


def _keyed_values(
    payload: Mapping[str, Any], key: str, width: int, problems: list[str]
) -> dict[Any, float]:
    """``[{"key": [...], "value": n}, ...]`` -> ``{(...): n}``."""
    out: dict[tuple[str, ...], float] = {}
    for i, item in enumerate(_require_list(payload, key, problems)):
        if not isinstance(item, Mapping) or "key" not in item or "value" not in item:
            problems.append(f"{key}[{i}]: expected {{'key': [...], 'value': n}}, got {item!r}")
            continue
        raw_key = item["key"]
        if not isinstance(raw_key, Sequence) or isinstance(raw_key, str) or len(raw_key) != width:
            problems.append(f"{key}[{i}].key: expected {width} values, got {raw_key!r}")
            continue
        try:
            out[tuple(str(v) for v in raw_key)] = float(item["value"])
        except (TypeError, ValueError):
            problems.append(f"{key}[{i}].value: expected a number, got {item['value']!r}")
    return out


def _flagged(payload: Mapping[str, Any], key: str, problems: list[str]) -> frozenset[str]:
    """``[["a", true], ["b", false]]`` -> ``{"a"}``."""
    out: set[str] = set()
    for i, item in enumerate(_require_list(payload, key, problems)):
        if not isinstance(item, Sequence) or isinstance(item, str) or len(item) != 2:
            problems.append(f"{key}[{i}]: expected [id, bool], got {item!r}")
            continue
        if bool(item[1]):
            out.add(str(item[0]))
    return frozenset(out)


def _int_mapping(
    payload: Mapping[str, Any], key: str, problems: list[str]
) -> dict[str, int]:
    """``[["a", 2], ...]`` -> ``{"a": 2}``."""
    out: dict[str, int] = {}
    for i, item in enumerate(_require_list(payload, key, problems)):
        if not isinstance(item, Sequence) or isinstance(item, str) or len(item) != 2:
            problems.append(f"{key}[{i}]: expected [id, number], got {item!r}")
            continue
        try:
            out[str(item[0])] = int(item[1])
        except (TypeError, ValueError):
            problems.append(f"{key}[{i}]: expected a number, got {item[1]!r}")
    return out


# --------------------------------------------------------------------------- #
# the instance
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class Instance:
    """A validated, solve-ready problem.

    Sets already include the reserved fallbacks: ``professors`` contains
    :data:`PART_TIMER`, ``classrooms`` contains :data:`OFF_CAMPUS`, and
    ``timeslots`` contains one placeholder per time of day. Build one with
    :meth:`from_payload`, never by hand — the constructor does not validate.
    """

    # sets
    professors: frozenset[str]
    courses: frozenset[str]
    sections: frozenset[str]
    classrooms: frozenset[str]
    semesters: frozenset[str]
    timeslots: frozenset[str]
    times_of_day: frozenset[str]
    days_of_week: frozenset[str]
    block_types: frozenset[str]

    # subsets: which combinations exist at all
    section_keys: frozenset[SectionKey]
    timeslot_day: frozenset[tuple[str, str]]
    timeslot_time_of_day: frozenset[tuple[str, str]]
    timeslot_block: frozenset[tuple[str, str]]
    overlapping_timeslots: frozenset[tuple[str, str]]

    # professors
    teaching_load: Mapping[str, int]
    qualifications: frozenset[tuple[str, str]]
    can_teach_night: frozenset[str]
    can_teach_off_campus: frozenset[str]
    course_preference: Mapping[tuple[str, str], float]
    time_preference: Mapping[tuple[str, str, str], float]
    block_preference: frozenset[tuple[str, str]]
    pack_day_preference: Mapping[str, int]

    # rooms and sections
    classroom_capacity: Mapping[str, int]
    attendance: Mapping[SectionKey, int]
    must_run_together: frozenset[tuple[str, str, str]]
    must_not_overlap: frozenset[tuple[str, str, str]]
    friday_night_penalty: frozenset[str]
    course_block_preference: frozenset[tuple[str, str]]

    @property
    def real_professors(self) -> frozenset[str]:
        """Professors excluding the part-timer fallback."""
        return self.professors - {PART_TIMER}

    @property
    def real_classrooms(self) -> frozenset[str]:
        """Rooms we actually control, excluding the off-campus fallback."""
        return self.classrooms - {OFF_CAMPUS}

    @property
    def real_timeslots(self) -> frozenset[str]:
        """Timeslots excluding the placeholders."""
        return frozenset(t for t in self.timeslots if not is_placeholder(t))

    def summary(self) -> str:
        def count(n: int, noun: str, plural: str = "s") -> str:
            return f"{n:,} {noun}{'' if n == 1 else plural}"

        return ", ".join((
            count(len(self.real_professors), "professor"),
            count(len(self.courses), "course"),
            count(len(self.sections), "section"),
            count(len(self.real_classrooms), "room"),
            count(len(self.real_timeslots), "timeslot"),
            count(len(self.semesters), "semester"),
        ))

    # ----------------------------------------------------------------- #

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Instance:
        """Parse and validate a payload.

        :raises InvalidInstanceError: listing every problem found.
        """
        if not isinstance(payload, Mapping):
            raise InvalidInstanceError([f"payload must be an object, got {type(payload).__name__}"])

        missing = [key for key in PAYLOAD_KEYS if key not in payload]
        if missing:
            raise InvalidInstanceError([f"missing required key: {key}" for key in missing])

        problems: list[str] = []

        professors = _ids(payload, "professor_set", problems)
        courses = _ids(payload, "course_set", problems)
        sections = _ids(payload, "section_set", problems)
        classrooms = _ids(payload, "classroom_set", problems)
        semesters = _ids(payload, "semester_set", problems)
        timeslots = _ids(payload, "timeslot_set", problems)
        times_of_day = _ids(payload, "time_of_day_set", problems)
        days_of_week = _ids(payload, "day_of_week_set", problems)
        block_types = _ids(payload, "block_type_set", problems)

        for name, given in (
            ("professor_set", professors),
            ("classroom_set", classrooms),
            ("timeslot_set", timeslots),
        ):
            clashes = sorted(given & RESERVED_IDS) + sorted(
                t for t in given if is_placeholder(t)
            )
            for clash in clashes:
                problems.append(f"{name}: {clash!r} is reserved by the solver and cannot be an id")

        section_keys = frozenset(
            k for k in _tuples(payload, "section_subset", 4, problems) if len(k) == 4
        )
        timeslot_day = _tuples(payload, "timeslot_dow_subset", 2, problems)
        timeslot_time_of_day = _tuples(payload, "timeslot_tod_subset", 2, problems)
        timeslot_block = _tuples(payload, "timeslot_block_subset", 2, problems)

        # Two shapes reach us: {"timeslot_1": a, "timeslot_2": b} from the
        # Django endpoint, and [a, b] from a config file or a hand-written
        # instance. Anything else is reported rather than dropped — silently
        # discarding a clash yields a schedule that double-books a room and
        # looks perfectly successful.
        overlapping_rows: list[tuple[str, str]] = []
        for index, row in enumerate(_require_list(payload, "timeslot_concurrency", problems)):
            if isinstance(row, Mapping):
                values = list(row.values())
            elif isinstance(row, Sequence) and not isinstance(row, str):
                values = list(row)
            else:
                problems.append(
                    f"timeslot_concurrency[{index}]: expected two timeslot ids, got {row!r}"
                )
                continue
            if len(values) != 2:
                problems.append(
                    f"timeslot_concurrency[{index}]: expected two timeslot ids, got {row!r}"
                )
                continue
            overlapping_rows.append((str(values[0]), str(values[1])))
        overlapping: frozenset[Any] = frozenset(overlapping_rows)

        teaching_load_raw = _merged_mapping(payload, "professor_teaching", problems)
        teaching_load: dict[str, int] = {}
        for name, value in teaching_load_raw.items():
            try:
                teaching_load[name] = int(value)
            except (TypeError, ValueError):
                problems.append(f"professor_teaching[{name!r}]: expected a number, got {value!r}")

        qualifications = _tuples(payload, "professor_qualification", 2, problems)
        can_teach_night = _flagged(payload, "professor_can_teach_night", problems)
        can_teach_off_campus = _flagged(payload, "professor_can_teach_out_DMS", problems)
        course_preference = _keyed_values(payload, "professor_course_pref", 2, problems)
        time_preference = _keyed_values(payload, "professor_time_pref", 3, problems)
        block_preference = _tuples(payload, "professor_block_pref", 2, problems)
        pack_day_preference = _int_mapping(payload, "professor_pack_day_pref", problems)

        capacity_raw = _merged_mapping(payload, "classroom_cap", problems)
        classroom_capacity: dict[str, int] = {}
        for name, value in capacity_raw.items():
            try:
                classroom_capacity[name] = int(value)
            except (TypeError, ValueError):
                problems.append(f"classroom_cap[{name!r}]: expected a number, got {value!r}")

        attendance = {
            key: int(value)
            for key, value in _keyed_values(payload, "section_attendance", 4, problems).items()
        }
        must_run_together = _tuples(payload, "course_concurrency_t", 3, problems)
        must_not_overlap = _tuples(payload, "course_concurrency_nt", 3, problems)
        friday_night_penalty = _ids(payload, "course_friday_penalty", problems)
        course_block_preference = _tuples(payload, "course_block_pref", 2, problems)

        # ---- referential integrity ------------------------------------ #
        # Every one of these would otherwise surface as a bare KeyError from
        # somewhere deep inside constraint generation.

        def check_members(
            label: str, values: frozenset[Any], universe: frozenset[str], position: str
        ) -> None:
            unknown = sorted(str(v) for v in values - universe)
            for item in unknown[:5]:
                problems.append(f"{label}: unknown {position} {item!r}")
            if len(unknown) > 5:
                problems.append(f"{label}: ... and {len(unknown) - 5} more unknown {position}s")

        check_members(
            "section_subset", frozenset(k[0] for k in section_keys), courses, "course"
        )
        check_members(
            "section_subset", frozenset(k[1] for k in section_keys), sections, "section"
        )
        check_members(
            "section_subset", frozenset(k[2] for k in section_keys), semesters, "semester"
        )
        check_members(
            "section_subset", frozenset(k[3] for k in section_keys), times_of_day, "time of day"
        )
        def check_pairs(
            label: str,
            pairs: frozenset[Any],
            left: tuple[frozenset[str], str],
            right: tuple[frozenset[str], str],
        ) -> None:
            check_members(label, frozenset(p[0] for p in pairs), *left)
            check_members(label, frozenset(p[1] for p in pairs), *right)

        slots = (timeslots, "timeslot")
        profs = (professors, "professor")
        blocks = (block_types, "block type")
        check_pairs("timeslot_dow_subset", timeslot_day, slots, (days_of_week, "day of week"))
        check_pairs(
            "timeslot_tod_subset", timeslot_time_of_day, slots, (times_of_day, "time of day")
        )
        check_pairs("timeslot_block_subset", timeslot_block, slots, blocks)
        check_pairs("professor_qualification", qualifications, profs, (courses, "course"))
        check_pairs("professor_block_pref", block_preference, profs, blocks)
        check_pairs("course_block_pref", course_block_preference, (courses, "course"), blocks)

        check_members("course_friday_penalty", friday_night_penalty, courses, "course")
        check_members(
            "professor_can_teach_night", can_teach_night, professors, "professor"
        )
        check_members(
            "professor_can_teach_out_DMS", can_teach_off_campus, professors, "professor"
        )

        # ---- completeness --------------------------------------------- #
        # The model indexes these by every member of a set, so a gap is fatal.

        for label, required, provided, position in (
            ("professor_teaching", professors, frozenset(teaching_load), "professor"),
            ("professor_pack_day_pref", professors, frozenset(pack_day_preference), "professor"),
            ("classroom_cap", classrooms, frozenset(classroom_capacity), "classroom"),
            ("section_attendance", section_keys, frozenset(attendance), "section"),
        ):
            gaps = sorted(str(v) for v in required - provided)
            for item in gaps[:5]:
                problems.append(f"{label}: no value for {position} {item}")
            if len(gaps) > 5:
                problems.append(f"{label}: ... and {len(gaps) - 5} more {position}s with no value")

        unknown_blocks = sorted(block_types - frozenset(BLOCK_WEIGHTS))
        for block in unknown_blocks:
            problems.append(
                f"block_type_set: {block!r} has no weight; known blocks are "
                f"{sorted(BLOCK_WEIGHTS)}"
            )

        # Every section must have at least one timeslot at its time of day, or
        # it can only ever land on a placeholder.
        slot_times = frozenset(td for _, td in timeslot_time_of_day)
        for time_of_day in sorted({k[3] for k in section_keys} - slot_times):
            problems.append(
                f"timeslot_tod_subset: no timeslot at time of day {time_of_day!r}, "
                "so sections scheduled then can only get a placeholder"
            )

        if problems:
            raise InvalidInstanceError(problems)

        # ---- augment with the reserved fallbacks ----------------------- #
        return cls(
            professors=professors | {PART_TIMER},
            courses=courses,
            sections=sections,
            classrooms=classrooms | {OFF_CAMPUS},
            semesters=semesters,
            timeslots=timeslots | {placeholder_for(td) for td in times_of_day},
            times_of_day=times_of_day,
            days_of_week=days_of_week,
            block_types=block_types,
            section_keys=section_keys,
            timeslot_day=timeslot_day,
            timeslot_time_of_day=(
                timeslot_time_of_day | {(placeholder_for(td), td) for td in times_of_day}
            ),
            timeslot_block=timeslot_block,
            overlapping_timeslots=overlapping,
            teaching_load=teaching_load,
            qualifications=qualifications,
            can_teach_night=can_teach_night,
            can_teach_off_campus=can_teach_off_campus,
            course_preference=course_preference,
            time_preference=time_preference,
            block_preference=block_preference,
            pack_day_preference=pack_day_preference,
            classroom_capacity=classroom_capacity,
            attendance=attendance,
            must_run_together=must_run_together,
            must_not_overlap=must_not_overlap,
            friday_night_penalty=friday_night_penalty,
            course_block_preference=course_block_preference,
        )
