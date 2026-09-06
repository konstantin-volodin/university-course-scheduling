"""Reject output collisions before opening logs or invoking a solver."""

from pathlib import Path
from typing import Any

import pytest

from scheduler import cli


@pytest.mark.parametrize(
    "filename", ["schedule.html", "instance.html", "objective.md", "solve.log"],
)
def test_reserved_output_name_rejected(tmp_path: Path, filename: str) -> None:
    args = cli.build_parser().parse_args([
        "solve", "-", "-o", str(tmp_path / filename), "--time-limit", "1",
    ])
    with pytest.raises(cli.SchedulerError, match="distinct"):
        cli._solve_output_paths(args)
    assert not list(tmp_path.iterdir())


def test_input_cannot_be_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    source.write_text("original input")
    args = cli.build_parser().parse_args([
        "solve", str(source), "-o", str(source), "--time-limit", "1",
    ])
    with pytest.raises(cli.SchedulerError, match="input instance"):
        cli._solve_output_paths(args)
    assert source.read_text() == "original input"


def test_html_cannot_alias_result(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    args = cli.build_parser().parse_args([
        "solve", "-", "-o", str(output), "--html", str(output), "--time-limit", "1",
    ])
    with pytest.raises(cli.SchedulerError, match="distinct"):
        cli._solve_output_paths(args)
    assert not output.exists()


@pytest.mark.parametrize("directory_input", [False, True])
def test_split_fragment_cannot_be_overwritten(tmp_path: Path, directory_input: bool) -> None:
    manifest = tmp_path / "instance.yaml"
    fragment = tmp_path / "courses.yaml"
    manifest.write_text("files:\n  courses: [courses.yaml]\n")
    fragment.write_text("original courses")
    args = cli.build_parser().parse_args([
        "solve", str(tmp_path if directory_input else manifest),
        "-o", str(fragment), "--time-limit", "1",
    ])
    with pytest.raises(cli.SchedulerError, match="input instance"):
        cli._solve_output_paths(args)
    assert fragment.read_text() == "original courses"


def test_cli_rejects_input_output_collision_before_solving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "input.yaml"
    template = Path(__file__).parents[2] / "instances" / "tiny" / "instance.yaml"
    original = template.read_text()
    source.write_text(original)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("unsafe output must be rejected before solving")

    monkeypatch.setattr(cli, "solve_instance", forbidden)
    assert cli.main([
        "solve", str(source), "-o", str(source), "--time-limit", "1",
    ]) == 1
    assert "must not overwrite" in capsys.readouterr().err
    assert source.read_text() == original
    assert not (tmp_path / "solve.log").exists()


def test_symlink_manifest_uses_loader_relative_fragment_paths(tmp_path: Path) -> None:
    original_dir = tmp_path / "original"
    original_dir.mkdir()
    manifest = original_dir / "instance.yaml"
    manifest.write_text("files:\n  courses: courses.yaml\n")
    link = tmp_path / "instance.yaml"
    link.symlink_to(manifest)
    fragment = tmp_path / "courses.yaml"
    fragment.write_text("local fragment used by loader")
    args = cli.build_parser().parse_args([
        "solve", str(link), "-o", str(fragment), "--time-limit", "1",
    ])
    with pytest.raises(cli.SchedulerError, match="input instance"):
        cli._solve_output_paths(args)
    assert fragment.read_text() == "local fragment used by loader"


def test_hardlinked_input_cannot_be_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    source.write_text("original input")
    output = tmp_path / "result.json"
    output.hardlink_to(source)
    args = cli.build_parser().parse_args([
        "solve", str(source), "-o", str(output), "--time-limit", "1",
    ])
    with pytest.raises(cli.SchedulerError, match="input instance"):
        cli._solve_output_paths(args)
    assert source.read_text() == "original input"
