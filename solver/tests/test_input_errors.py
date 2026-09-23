"""Reject invalid solve limits before doing work and report I/O failures cleanly."""

from pathlib import Path
from typing import Any

import pytest

from scheduler import cli
from scheduler.solve import solve


@pytest.mark.parametrize("limit", ["0", "-1", "nan", "inf", "-inf", "1e999"])
def test_cli_rejects_invalid_limit_before_reading_instance(
    limit: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "results" / "result.json"
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "solve", str(tmp_path / "missing.yaml"),
            f"--time-limit={limit}", "-o", str(output),
        ])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "more than 0 and at most 60" in captured.err
    assert captured.out == ""
    assert not output.parent.exists()


@pytest.mark.parametrize("limit", [0.0, -1.0, float("nan"), float("inf"), -float("inf")])
def test_api_rejects_invalid_limit(payload: dict[str, Any], limit: float) -> None:
    with pytest.raises(ValueError, match="more than 0 and at most 60"):
        solve(payload, time_limit=limit)


def test_cli_reports_os_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unreadable(path: str) -> Any:
        raise PermissionError(f"Permission denied: {path}")

    monkeypatch.setattr(cli, "_read_instance", unreadable)
    assert cli.main(["solve", "instance.yaml", "--time-limit=1"]) == 1
    captured = capsys.readouterr()
    assert "error: Permission denied: instance.yaml" in captured.err
    assert captured.out == ""
