"""The CLI contract: stdout carries JSON and nothing else, so it can be piped.

Gurobi prints its licence banner to stdout when its environment starts, which
silently corrupted the output of the earlier version of this tool. That is what
`test_stdout_is_pure_json` is really guarding.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scheduler.cli import main
from scheduler.solve import Assignment, Result

INSTANCES = Path(__file__).parents[2] / "instances"
TINY = INSTANCES / "tiny"
TINY_FILE = TINY / "instance.yaml"
MEDIUM = INSTANCES / "medium"


def test_unscheduled_result_warns_even_when_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = Result("feasible", 0.0, [Assignment(
        professor_id=None, course_id="C", section_id="1", semester_id="Fall",
        timeslot_id=None, classroom_id=None, time_of_day_id="Day", solution_value=1.0,
    )])
    monkeypatch.setattr("scheduler.cli.solve_instance", lambda *args, **kwargs: result)
    output = tmp_path / "result.json"
    assert main(["solve", str(TINY), "-o", str(output), "-q", "--time-limit", "1"]) == 0
    captured = capsys.readouterr()
    assert "incomplete timetable: 1 of 1 sections have no timeslot" in captured.err
    assert captured.out == ""
    assert json.loads(output.read_text())["status"] == "feasible"


def test_solve_writes_json_to_a_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "result.json"
    assert main(["solve", str(TINY), "-o", str(output), "-q"]) == 0

    result = json.loads(output.read_text())
    assert result["status"] == "optimal"
    assert len(result["assignments"]) == 3


def test_solve_writes_three_default_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "tiny.yaml"
    source.write_text(TINY_FILE.read_text())

    assert main(["solve", str(source), "-q"]) == 0

    results = tmp_path / "results"
    assert json.loads((results / "result.json").read_text())["status"] == "optimal"
    assert (results / "schedule.html").read_text().startswith("<!doctype html>")
    assert (results / "instance.html").read_text().startswith("<!doctype html>")
    assert capsys.readouterr().out == ""


def test_check_validates_without_solving(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["solve", str(TINY), "--check"]) == 0
    assert "valid" in capsys.readouterr().err


def test_check_accepts_a_split_instance_directory(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["solve", str(MEDIUM), "--check"]) == 0
    assert "valid" in capsys.readouterr().err


def test_check_reports_an_invalid_instance(
    tmp_path: Path, payload: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    del payload["classroom_cap"]
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(payload))

    assert main(["solve", str(broken), "--check"]) == 2
    assert "classroom_cap" in capsys.readouterr().err


def test_missing_file_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["solve", "/nonexistent/instance.json", "-q"]) == 1
    assert "error" in capsys.readouterr().err


def test_malformed_json_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert main(["solve", str(bad), "-q"]) == 1
    assert "invalid JSON" in capsys.readouterr().err


def test_infeasible_instance_exits_nonzero(
    tmp_path: Path, payload: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    payload["professor_teaching"] = [{"prof_a": 9}, {"prof_b": 9}]
    instance = tmp_path / "hard.json"
    instance.write_text(json.dumps(payload))

    assert main(["solve", str(instance), "-q"]) == 1
    assert "teaching load" in capsys.readouterr().err


@pytest.mark.slow
def test_stdin_stdout_is_pure_json() -> None:
    """The streaming form still reserves stdout exclusively for the result JSON."""
    completed = subprocess.run(
        [sys.executable, "-m", "scheduler", "solve", "-"],
        input=TINY_FILE.read_text(), capture_output=True, text=True, check=True,
    )
    result = json.loads(completed.stdout)  # would raise if anything else leaked
    assert result["status"] == "optimal"


@pytest.mark.slow
def test_reads_an_instance_from_stdin() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "scheduler", "solve", "-", "-q"],
        input=TINY_FILE.read_text(), capture_output=True, text=True, check=True,
    )
    assert json.loads(completed.stdout)["status"] == "optimal"


@pytest.mark.slow
def test_progress_goes_to_stderr() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "scheduler", "solve", "-"],
        input=TINY_FILE.read_text(), capture_output=True, text=True, check=True,
    )
    assert "solving" in completed.stderr
    json.loads(completed.stdout)


def test_version() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "scheduler", "--version"],
        capture_output=True, text=True, check=True,
    )
    assert completed.stdout.strip().startswith("scheduler ")
