from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from scheduler import config

INSTANCES = Path(__file__).parents[2] / "instances"


@pytest.fixture(scope="session")
def tiny_payload_source() -> dict[str, Any]:
    return config.load(INSTANCES / "tiny.yaml")


@pytest.fixture
def payload(tiny_payload_source: dict[str, Any]) -> dict[str, Any]:
    """A fresh, mutable copy of the tiny instance for each test."""
    return copy.deepcopy(tiny_payload_source)


@pytest.fixture(scope="session")
def oversized_payload() -> dict[str, Any]:
    """An instance too large for the size-limited pip licence.

    Built rather than stored: the point is to exceed whatever the local licence
    allows, and a fixture file would silently stop testing that if the licence
    ever changed.
    """
    professors = [f"prof{i:02d}" for i in range(8)]
    courses = [f"ADM{1000 + i}" for i in range(6)]
    times = ["Morning", "Afternoon", "Night"]
    days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    slots = [f"T{i:02d}" for i in range(20)]
    rooms = [f"R{i}" for i in range(8)]

    sections, subset, attendance = [], [], []
    doubled = [c for c in courses for _ in range(2)]
    for n, course in enumerate(doubled):
        section = str(n + 1)
        time_of_day = times[n % 3]
        sections.append(section)
        subset.append([course, section, "Fall", time_of_day])
        attendance.append({"key": [course, section, "Fall", time_of_day], "value": 40})

    return {
        "professor_set": professors,
        "course_set": courses,
        "section_set": sections,
        "classroom_set": rooms,
        "semester_set": ["Fall"],
        "timeslot_set": slots,
        "time_of_day_set": times,
        "day_of_week_set": days,
        "block_type_set": ["1.5", "3.0"],
        "section_subset": subset,
        "timeslot_tod_subset": [[s, times[i % 3]] for i, s in enumerate(slots)],
        "timeslot_dow_subset": [[s, days[i % 5]] for i, s in enumerate(slots)],
        "timeslot_block_subset": [[s, "1.5" if i % 2 else "3.0"] for i, s in enumerate(slots)],
        "timeslot_concurrency": [],
        "professor_teaching": [{p: 1} for p in professors],
        "professor_qualification": [[p, c] for p in professors for c in courses],
        "professor_can_teach_night": [[p, True] for p in professors],
        "professor_can_teach_out_DMS": [[p, True] for p in professors],
        "professor_course_pref": [],
        "professor_time_pref": [],
        "professor_block_pref": [],
        "professor_pack_day_pref": [[p, 1] for p in professors],
        "classroom_cap": [{r: 50} for r in rooms],
        "section_attendance": attendance,
        "course_concurrency_t": [],
        "course_concurrency_nt": [],
        "course_friday_penalty": [],
        "course_block_pref": [],
    }


@pytest.fixture(scope="session")
def medium_payload_source() -> dict[str, Any]:
    """The public medium example is large enough to exercise the staged solve."""
    return config.load(INSTANCES / "medium")
