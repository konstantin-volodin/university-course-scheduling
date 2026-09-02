"""Public solve results and their JSON representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .backends import DEFAULT_BACKEND

__all__ = ["Assignment", "Result", "Stage"]


@dataclass(frozen=True, slots=True)
class Assignment:
    """One scheduled section.

    ``None`` represents a fallback: a part-timer, an off-campus room, or a
    section for which no real timeslot was available.
    """

    professor_id: str | None
    course_id: str
    section_id: int | str
    semester_id: str
    timeslot_id: str | None
    classroom_id: str | None
    time_of_day_id: str
    solution_value: float


@dataclass(frozen=True, slots=True)
class Stage:
    """The result and duration of one lexicographic solve stage."""

    name: str
    value: float
    seconds: float
    proven: bool


@dataclass(frozen=True, slots=True)
class Result:
    status: str
    objective: float
    assignments: list[Assignment]
    solver: str = DEFAULT_BACKEND
    stages: list[Stage] = field(default_factory=list)

    @property
    def unstaffed(self) -> list[Assignment]:
        return [assignment for assignment in self.assignments if assignment.professor_id is None]

    @property
    def unscheduled(self) -> list[Assignment]:
        return [assignment for assignment in self.assignments if assignment.timeslot_id is None]

    @property
    def off_campus(self) -> list[Assignment]:
        return [assignment for assignment in self.assignments if assignment.classroom_id is None]

    def to_dict(self) -> dict[str, Any]:
        """Return the stable, JSON-ready wire representation."""
        return {
            "status": self.status,
            "solver": self.solver,
            "objective": self.objective,
            "assignments": [asdict(assignment) for assignment in self.assignments],
            "stages": [asdict(stage) for stage in self.stages],
            "summary": {
                "assignments": len(self.assignments),
                "unstaffed": len(self.unstaffed),
                "unscheduled": len(self.unscheduled),
                "off_campus": len(self.off_campus),
            },
        }
