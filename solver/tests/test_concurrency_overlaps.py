"""Course separation must account for distinct overlapping meeting IDs."""

from __future__ import annotations

from typing import Any

import pytest

from scheduler import silent
from scheduler.backends.highs import HighsBackend
from scheduler.config import PART_TIMER, Instance
from scheduler.model import build
from scheduler.model.program import Row, Sense
from scheduler.progress import Progress


def forced_concurrency(
    payload: dict[str, Any],
    *,
    overlaps: list[list[str]],
    together: bool = False,
    part_timer: bool = False,
) -> tuple[float, list[float]]:
    payload["section_set"] = ["1"]
    payload["section_subset"] = [
        ["ADM1000", "1", "Fall", "Day"],
        ["ADM2000", "1", "Fall", "Day"],
    ]
    payload["section_attendance"] = [
        {"key": section, "value": 40} for section in payload["section_subset"]
    ]
    payload["professor_teaching"] = [{"prof_a": 1}, {"prof_b": 0 if part_timer else 1}]
    payload["professor_qualification"] = [["prof_a", "ADM1000"], ["prof_b", "ADM2000"]]
    payload["classroom_cap"] = [{"DMS1150": 40}, {"DMS1160": 40}]
    payload["timeslot_concurrency"] = overlaps
    payload["course_concurrency_t"] = [["ADM1000", "ADM2000", "Fall"]] if together else []
    payload["course_concurrency_nt"] = [] if together else [["ADM1000", "ADM2000", "Fall"]]
    built = build(Instance.from_payload(payload), Progress(silent))
    backend = HighsBackend()
    try:
        backend.load(built.program)
        placements = [
            ("ADM1000", "prof_a", "Mon0900", "DMS1150"),
            ("ADM2000", PART_TIMER if part_timer else "prof_b", "Wed0900", "DMS1160"),
        ]
        for course, professor, slot, room in placements:
            variable = next(
                index
                for key, index in built.assign.items()
                if (key.course, key.professor, key.timeslot, key.classroom)
                == (course, professor, slot, room)
            )
            backend.add_rows([Row(f"force_{course}", {variable: 1}, Sense.EQ, 1)])
        outcome = backend.optimise(
            built.objectives.concurrency, maximise=False, gap=0, time_limit=5
        )
        assert outcome.usable, outcome.detail
        return outcome.objective, outcome.values
    finally:
        backend.close()


@pytest.mark.parametrize(
    "overlaps",
    [
        [["Mon0900", "Wed0900"]],
        [["Wed0900", "Mon0900"]],
    ],
)
def test_apart_detects_distinct_overlapping_meeting_ids(
    payload: dict[str, Any], overlaps: list[list[str]]
) -> None:
    value, values = forced_concurrency(payload, overlaps=overlaps)
    assert value > 0
    assert forced_concurrency(payload, overlaps=overlaps) == (value, values)


@pytest.mark.parametrize(
    "overlaps",
    [[], [["Mon0900", "Mon1800"], ["Mon1800", "Wed0900"]]],
)
def test_apart_does_not_confuse_overlap_with_transitive_connectivity(
    payload: dict[str, Any], overlaps: list[list[str]]
) -> None:
    value, _ = forced_concurrency(payload, overlaps=overlaps)
    assert value == 0


def test_together_still_requires_the_same_meeting_id(payload: dict[str, Any]) -> None:
    value, _ = forced_concurrency(
        payload, overlaps=[["Mon0900", "Wed0900"]], together=True
    )
    assert value > 0


def test_apart_keeps_the_part_timer_exemption(payload: dict[str, Any]) -> None:
    value, _ = forced_concurrency(
        payload, overlaps=[["Mon0900", "Wed0900"]], part_timer=True
    )
    assert value == 0
