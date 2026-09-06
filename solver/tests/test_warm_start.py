"""External incumbents must be legal and remain hints, not fixed assignments."""

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from scheduler.audit import audit_result
from scheduler.cli import main
from scheduler.config import Instance
from scheduler.errors import SchedulerError
from scheduler.model import build
from scheduler.progress import Progress, silent
from scheduler.solve.solver import _extract, _placeholder_seed, solve_instance
from scheduler.solve.warm_start import assignments_from_result, validate_initial_assignments


@pytest.mark.slow
def test_prior_result_round_trip(payload: dict[str, Any]) -> None:
    instance = Instance.from_payload(payload)
    original = solve_instance(instance, time_limit=10)
    assignments = assignments_from_result(asdict(original))
    validate_initial_assignments(instance, assignments)
    resumed = solve_instance(instance, time_limit=10, initial_assignments=assignments)
    assert not audit_result(instance, resumed)
    assert sum(a.timeslot_id is None for a in resumed.assignments) == 0
    assert [stage.value for stage in resumed.stages] == [
        stage.value for stage in original.stages
    ]


def test_incomplete_seed_rejected(payload: dict[str, Any]) -> None:
    with pytest.raises(SchedulerError, match="warm start"):
        solve_instance(Instance.from_payload(payload), time_limit=10, initial_assignments=[])


def test_seed_is_not_a_fixed_timetable(payload: dict[str, Any]) -> None:
    instance = Instance.from_payload(payload)
    built = build(instance, Progress(silent))
    assignments = _extract(built, _placeholder_seed(built))
    assert all(assignment.timeslot_id is None for assignment in assignments)
    validate_initial_assignments(instance, assignments)

    result = solve_instance(instance, silent, time_limit=10, initial_assignments=assignments)

    assert not result.unscheduled
    assert not audit_result(instance, result)


@pytest.mark.parametrize("value", [None, [], {}, {"assignments": [None]},
                                  {"assignments": [{}]}])
def test_malformed_seed_rejected(value: Any) -> None:
    with pytest.raises(SchedulerError, match="warm start"):
        assignments_from_result(value)


def test_invalid_cli_seed_leaves_existing_outputs_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text('{"assignments": []}')
    output = tmp_path / "result.json"
    output.write_text("previous result")
    log = tmp_path / "solve.log"
    log.write_text("previous log")
    instance = Path(__file__).parents[2] / "instances" / "tiny"
    assert main([
        "solve", str(instance), "--warm-start", str(seed), "--time-limit", "1",
        "-o", str(output), "-q",
    ]) != 0
    assert "warm start" in capsys.readouterr().err
    assert output.read_text() == "previous result"
    assert log.read_text() == "previous log"
