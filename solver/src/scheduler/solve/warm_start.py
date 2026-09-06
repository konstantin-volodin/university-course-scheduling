"""Read and validate prior assignments without trusting stored scores or status."""

from collections.abc import Sequence
from typing import Any

from ..audit import audit_result
from ..config import Instance
from ..errors import SchedulerError
from .result import Assignment, Result


def assignments_from_result(payload: Any) -> list[Assignment]:
    if not isinstance(payload, dict) or not isinstance(payload.get("assignments"), list):
        raise SchedulerError("warm start: expected a result object with an assignments list")
    assignments = []
    for index, row in enumerate(payload["assignments"]):
        try:
            if not isinstance(row, dict):
                raise ValueError("expected an assignment object")
            for key in ("course_id", "semester_id", "time_of_day_id"):
                if not isinstance(row.get(key), str):
                    raise ValueError(f"{key} must be a string")
            for key in ("professor_id", "timeslot_id", "classroom_id"):
                if row.get(key) is not None and not isinstance(row[key], str):
                    raise ValueError(f"{key} must be a string or null")
            if isinstance(row.get("section_id"), bool) or not isinstance(
                row.get("section_id"), (str, int)
            ):
                raise ValueError("section_id must be a string or integer")
            if isinstance(row.get("solution_value"), bool) or not isinstance(
                row.get("solution_value"), (int, float)
            ):
                raise ValueError("solution_value must be numeric")
            assignments.append(Assignment(**row))
        except (TypeError, ValueError) as exc:
            raise SchedulerError(f"warm start: assignment {index}: {exc}") from exc
    return assignments


def validate_initial_assignments(instance: Instance, assignments: Sequence[Assignment]) -> None:
    findings = audit_result(instance, Result("feasible", 0.0, list(assignments)))
    if findings:
        first = findings[0]
        raise SchedulerError(
            f"warm start: {len(findings)} hard-rule failures; {first.code}: {first.message}"
        )
