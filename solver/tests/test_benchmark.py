"""Benchmark reports preserve successful evidence alongside isolated failures."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scheduler import benchmark

TINY = Path(__file__).parents[2] / "instances" / "tiny"


def test_tiny_benchmark_records_repeatable_payload_and_results(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    assert benchmark.main([
        str(TINY), "--repeat", "2", "--time-limit", "10", "--output", str(output),
    ]) == 0
    report = json.loads(output.read_text())
    assert report["schema_version"] == 1
    assert report["solver"] == "highs"
    assert report["time_limit_per_stage_seconds"] == 10
    assert report["repetitions"] == 2
    assert report["environment"]["python"]
    assert report["environment"]["packages"]["highspy"]
    normalized = json.dumps(
        benchmark.config.load(TINY), sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    expected_hash = hashlib.sha256(normalized.encode()).hexdigest()
    first, second = report["runs"]
    assert [run["repetition"] for run in report["runs"]] == [1, 2]
    assert first["result"]["assignments"] == second["result"]["assignments"]
    for run in report["runs"]:
        assert run["status"] == "success"
        assert run["audit"] == {"passed": True, "issues": []}
        assert run["source"] == str(TINY.resolve())
        assert run["payload_sha256"] == expected_hash
        snapshot = json.dumps(
            run["input_payload"], sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        assert hashlib.sha256(snapshot.encode()).hexdigest() == expected_hash
        assert len(run["result"]["assignments"]) == 3
        assert len(run["result"]["stages"]) == 10
        assert run["elapsed_seconds"] > 0


@pytest.mark.parametrize("arguments", [
    ["--time-limit", "0"], ["--time-limit", "nan"], ["--time-limit", "inf"],
    ["--time-limit", "-1"], ["--time-limit", "no"],
    ["--time-limit", "1", "--repeat", "0"],
    ["--time-limit", "1", "--repeat", "1.5"],
    ["--time-limit", "1", "--solver", "unknown"], [],
])
def test_invalid_arguments_fail_before_solving(tmp_path: Path, arguments: list[str]) -> None:
    output = tmp_path / "report.json"
    with pytest.raises(SystemExit) as exc:
        benchmark.main([str(TINY), "--output", str(output), *arguments])
    assert exc.value.code == 2
    assert not output.exists()


def test_missing_input_does_not_discard_successful_runs(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    assert benchmark.main([
        str(tmp_path / "missing.yaml"), str(TINY), "--time-limit", "10", "--output", str(output),
    ]) == 1
    failed, succeeded = json.loads(output.read_text())["runs"]
    assert failed["status"] == "error"
    assert failed["error"]["message"]
    assert failed["payload_sha256"] is None
    assert succeeded["status"] == "success"


def test_solver_failure_is_isolated_to_one_repetition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = benchmark.solve_instance
    calls = 0

    def fail_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated backend failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(benchmark, "solve_instance", fail_once)
    output = tmp_path / "report.json"
    assert benchmark.main([
        str(TINY), "--repeat", "2", "--time-limit", "10", "--output", str(output),
    ]) == 1
    first, second = json.loads(output.read_text())["runs"]
    assert first["error"] == {"type": "RuntimeError", "message": "simulated backend failure"}
    assert first["payload_sha256"] == second["payload_sha256"]
    assert second["status"] == "success"


def test_output_cannot_overwrite_an_input(tmp_path: Path) -> None:
    source = tmp_path / "instance.yaml"
    source.write_text("original input")
    with pytest.raises(SystemExit):
        benchmark.main([str(source), "--time-limit", "1", "--output", str(source)])
    assert source.read_text() == "original input"


def test_nonfinite_result_is_recorded_as_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        benchmark, "solve_instance",
        lambda *args, **kwargs: SimpleNamespace(to_dict=lambda: {"objective": float("nan")}),
    )
    output = tmp_path / "report.json"
    assert benchmark.main([
        str(TINY), "--time-limit", "10", "--output", str(output),
    ]) == 1
    report = json.loads(output.read_text())
    assert report["runs"][0]["error"]["type"] == "ValueError"
    assert "result" not in report["runs"][0]


def test_manifest_output_cannot_overwrite_a_fragment_before_solving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "instance.yaml"
    source.write_text("files: {courses: courses.yaml}")
    fragment = tmp_path / "courses.yaml"
    fragment.write_text("original courses")

    def unexpected_run(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("output protection must run before loading or solving")

    monkeypatch.setattr(benchmark, "_run", unexpected_run)
    with pytest.raises(SystemExit) as exc:
        benchmark.main([str(source), "--time-limit", "1", "--output", str(fragment)])
    assert exc.value.code == 2
    assert fragment.read_text() == "original courses"


def test_report_write_error_returns_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    assert benchmark.main([
        str(TINY), "--time-limit", "10", "--output", str(tmp_path),
    ]) == 1
    assert "Could not write benchmark report" in capsys.readouterr().err


def test_invalid_schedule_is_preserved_but_not_reported_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = benchmark.solve_instance

    def missing_section(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        return replace(result, assignments=result.assignments[1:])

    monkeypatch.setattr(benchmark, "solve_instance", missing_section)
    output = tmp_path / "audit.json"
    assert benchmark.main([
        str(TINY), "--time-limit", "10", "--output", str(output),
    ]) == 1
    run = json.loads(output.read_text())["runs"][0]
    assert run["status"] == "error"
    assert not run["audit"]["passed"]
    assert "section_count" in {issue["code"] for issue in run["audit"]["issues"]}
    assert len(run["result"]["assignments"]) == 2
