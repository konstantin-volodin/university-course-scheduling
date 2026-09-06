"""Institutional room policy is explicit, validated, and applied by the model."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from scheduler import config, silent
from scheduler.config.instance import MIN_ROOM_FILL, Instance
from scheduler.errors import InvalidInstanceError
from scheduler.model import build
from scheduler.progress import Progress
from scheduler.solve import solve_instance

ROOM_EXAMPLE = """
semesters:
- Fall
classrooms:
  R1: 30
professors:
  p1:
    teaching_load: 1
    can_teach_off_campus: true
courses:
  C1:
    sections:
    - id: '1'
      semester: Fall
      time_of_day: Day
      students: 10
meeting_patterns:
  day:
    time_of_day: Day
    custom:
      AM:
      - day: Mon
        start: 09:00
        minutes: 90
"""


def test_default_room_fill_is_backward_compatible(payload: dict[str, Any]) -> None:
    assert payload["minimum_room_fill"] == 0.8
    inst = Instance.from_payload(payload)
    assert inst.minimum_room_fill == MIN_ROOM_FILL == 0.8
    with pytest.raises(FrozenInstanceError):
        inst.minimum_room_fill = 0  # type: ignore[misc]


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan"), float("inf"), True, None, "0.5"])
def test_invalid_room_fill_is_rejected(payload: dict[str, Any], value: Any) -> None:
    payload["minimum_room_fill"] = value
    with pytest.raises(InvalidInstanceError, match="minimum_room_fill"):
        Instance.from_payload(payload)


@pytest.mark.parametrize("value", [0, 0.5, 1])
def test_room_fill_accepts_endpoints_and_fractions(payload: dict[str, Any], value: float) -> None:
    payload["minimum_room_fill"] = value
    assert Instance.from_payload(payload).minimum_room_fill == value


def test_zero_room_fill_allows_an_underfilled_room() -> None:
    default = Instance.from_payload(config.loads("preset: telfer\n" + ROOM_EXAMPLE))
    relaxed = Instance.from_payload(config.loads("minimum_room_fill: 0\n" + ROOM_EXAMPLE))
    previous = solve_instance(default, progress=silent, time_limit=10)
    result = solve_instance(relaxed, progress=silent, time_limit=10)
    assert len(previous.off_campus) == 1
    assert not result.off_campus
    assert not result.unscheduled
    assert result.assignments[0].classroom_id == "R1"
    assert result.assignments[0].professor_id == "p1"


def test_zero_room_fill_still_rejects_over_capacity_rooms() -> None:
    text = "minimum_room_fill: 0\n" + ROOM_EXAMPLE.replace("students: 10", "students: 31")
    inst = Instance.from_payload(config.loads(text))
    built = build(inst, Progress(silent))
    assert not any(key.classroom == "R1" for key in built.assign)


def test_split_instance_preserves_room_fill(tmp_path: Path) -> None:
    import yaml

    example = yaml.safe_load(ROOM_EXAMPLE)
    files = {}
    for name in ("meeting_patterns", "classrooms", "professors", "courses"):
        files[name] = f"{name}.yaml"
        (tmp_path / files[name]).write_text(yaml.safe_dump(example[name]), encoding="utf-8")
    manifest = {"semesters": ["Fall"], "minimum_room_fill": 0.25, "files": files}
    (tmp_path / "instance.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    assert Instance.from_payload(config.load(tmp_path)).minimum_room_fill == 0.25
