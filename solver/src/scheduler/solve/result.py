"""Public solve results and their JSON representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from ..backends import DEFAULT_BACKEND

__all__ = ["Assignment", "ObjectiveBreakdown", "ObjectiveTerm", "Result", "Stage"]


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
    """The result and duration of one lexicographic solve stage.

    ``proven`` records backend-reported optimality under the configured gap and
    numerical tolerances, not necessarily an exact mathematical optimum, or an
    attained objective lower bound. ``optimality_source`` distinguishes them.
    """

    name: str
    value: float
    seconds: float
    proven: bool
    optimality_source: Literal["backend", "lower_bound"] = "backend"
    best_bound: float | None = None
    relative_gap: float | None = None


@dataclass(frozen=True, slots=True)
class ObjectiveTerm:
    """One active model term contributing to a preference component."""

    variable: str
    coefficient: float
    value: float
    contribution: float


@dataclass(frozen=True, slots=True)
class ObjectiveBreakdown:
    """Raw and weighted value of one final preference component."""

    name: str
    label: str
    description: str
    raw_value: float
    weight: float
    contribution: float
    terms: list[ObjectiveTerm] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Result:
    status: str
    objective: float
    assignments: list[Assignment]
    solver: str = DEFAULT_BACKEND
    stages: list[Stage] = field(default_factory=list)
    preference_breakdown: list[ObjectiveBreakdown] = field(default_factory=list)

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
            "preference_breakdown": [
                asdict(component) for component in self.preference_breakdown
            ],
            "summary": {
                "assignments": len(self.assignments),
                "unstaffed": len(self.unstaffed),
                "unscheduled": len(self.unscheduled),
                "off_campus": len(self.off_campus),
            },
        }
