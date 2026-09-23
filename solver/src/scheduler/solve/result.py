"""Public solve results and their JSON representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from ..backends import DEFAULT_BACKEND

__all__ = ["Assignment", "Result", "Stage", "StageItem"]


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
class StageItem:
    """One thing that adds to a stage's score, described for a reader."""

    description: str
    amount: float


@dataclass(frozen=True, slots=True)
class Stage:
    """The result and duration of one lexicographic solve stage.

    ``value`` is the score when the stage finished; ``final`` is the score in
    the returned schedule, which later stages can only keep or improve.
    ``proven`` records backend-reported optimality under numerical tolerances,
    or an attained objective lower bound; ``optimality_source`` says which.
    """

    name: str
    value: float
    seconds: float
    proven: bool
    optimality_source: Literal["backend", "lower_bound"] = "backend"
    best_bound: float | None = None
    relative_gap: float | None = None
    key: str = ""
    meaning: str = ""
    maximise: bool = False
    final: float | None = None
    items: list[StageItem] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Result:
    status: str
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
            "assignments": [asdict(assignment) for assignment in self.assignments],
            "stages": [asdict(stage) for stage in self.stages],
            "summary": {
                "assignments": len(self.assignments),
                "unstaffed": len(self.unstaffed),
                "unscheduled": len(self.unscheduled),
                "off_campus": len(self.off_campus),
            },
        }
