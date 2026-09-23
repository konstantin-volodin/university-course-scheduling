"""The CLI contract: stdout carries JSON and nothing else, so it can be piped.

Gurobi prints its licence banner to stdout when its environment starts, which
silently corrupted the output of the earlier version of this tool. That is what
`test_stdout_is_pure_json` is really guarding.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scheduler.cli import main
from scheduler.solve import Assignment, Result

INSTANCES = Path(__file__).parents[2] / "instances"
TINY = INSTANCES / "tiny"
TINY_FILE = TINY / "instance.yaml"
MEDIUM = INSTANCES / "medium"


@pytest.mark.parametrize("flag", [None, "--quiet", "--verbose"])
def test_console_verbosity_and_optional_diagnostic_log(
    flag: str | None, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    args = ["solve", str(TINY), "-o", str(tmp_path / "result.json"), "--time-limit", "1"]
    if flag:
        args.append(flag)
    assert main(args) == 0
    output = capsys.readouterr()
    assert not output.out
    assert "\x1b" not in output.err
    log = tmp_path / "solve.log"
    if flag == "--quiet":
        assert not output.err
        assert not log.exists()
    elif flag == "--verbose":
        assert "professor constraints" in output.err
        assert "professor constraints" in log.read_text()
    else:
        assert not log.exists()
        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO", output.err)
        assert "[stage] 1/12" in output.err
        assert "[stage] 12/12" in output.err
        assert "professor constraints" in output.err
        assert "objective=" in output.err
        assert "bound=" in output.err
        assert "gap=" in output.err
        assert "elapsed=" in output.err



def test_unscheduled_result_warns_even_when_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = Result("feasible", [Assignment(
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
    assert main(["solve", str(TINY), "-o", str(output), "-q", "--time-limit", "1"]) == 0

    result = json.loads(output.read_text())
    assert result["status"] == "optimal"
    assert len(result["assignments"]) == 3


def test_solve_writes_three_default_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "tiny.yaml"
    source.write_text(TINY_FILE.read_text())

    assert main(["solve", str(source), "-q", "--time-limit", "1"]) == 0

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
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = yaml.safe_load(TINY_FILE.read_text())
    del config["classrooms"]
    broken = tmp_path / "broken.yaml"
    broken.write_text(yaml.safe_dump(config))

    assert main(["solve", str(broken), "--check"]) == 2
    assert "classrooms" in capsys.readouterr().err


def test_missing_file_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["solve", "/nonexistent/instance.json", "-q"]) == 1
    assert "error" in capsys.readouterr().err


def test_malformed_yaml_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("{not json")
    assert main(["solve", str(bad), "-q"]) == 2
    assert "invalid YAML" in capsys.readouterr().err


def test_infeasible_instance_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = yaml.safe_load(TINY_FILE.read_text())
    for professor in config["professors"].values():
        professor["teaching_load"] = 9
    instance = tmp_path / "hard.yaml"
    instance.write_text(yaml.safe_dump(config))

    assert main(["solve", str(instance), "-q", "--time-limit", "1"]) == 1
    assert "teaching load" in capsys.readouterr().err


@pytest.mark.parametrize("quiet", [False, True])
def test_stdin_stdout_and_progress_streams(quiet: bool) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "scheduler", "solve", "-", "--time-limit", "1",
         *(["-q"] if quiet else [])],
        input=TINY_FILE.read_text(), capture_output=True, text=True, check=True,
    )
    assert json.loads(completed.stdout)["status"] == "optimal"
    if quiet:
        assert not completed.stderr
    else:
        assert "solving" in completed.stderr


def test_version() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "scheduler", "--version"],
        capture_output=True, text=True, check=True,
    )
    assert completed.stdout.strip().startswith("scheduler ")


def test_strict_flag_requires_operational_assignments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scheduler.config import Instance

    def capture(instance: Instance, *args: object, **kwargs: object) -> Result:
        assert instance.strict
        return Result("feasible", [])

    monkeypatch.setattr("scheduler.cli.solve_instance", capture)
    assert main([
        "solve", str(TINY), "--strict", "--time-limit", "1", "-q",
        "-o", str(tmp_path / "result.json"),
    ]) == 0


@pytest.mark.parametrize("stdin", [False, True])
def test_normalized_legacy_payload_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], stdin: bool,
) -> None:
    from io import StringIO

    from scheduler.config import load

    legacy = json.dumps(load(TINY))
    source = tmp_path / "legacy.json"
    source.write_text(legacy)
    monkeypatch.setattr(sys, "stdin", StringIO(legacy))
    assert main(["solve", "-" if stdin else str(source), "--check"]) == 2
    assert "invalid instance" in capsys.readouterr().err
