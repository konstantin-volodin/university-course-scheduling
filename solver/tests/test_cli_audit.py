"""Read-only hard-rule auditing keeps legality separate from completeness."""

import json
from pathlib import Path
from typing import Any

import pytest

from scheduler import cli


@pytest.fixture
def audit_files(tmp_path: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    instance = tmp_path / "input.json"
    instance.write_text(json.dumps(payload))
    assignments = [
        {
            "professor_id": professor, "course_id": course, "section_id": section,
            "semester_id": "Fall", "timeslot_id": slot, "classroom_id": "DMS1150",
            "time_of_day_id": tod, "solution_value": 1.0,
        }
        for professor, course, section, slot, tod in [
            ("prof_a", "ADM1000", 1, "Mon0900", "Day"),
            ("prof_b", "ADM1000", 2, "Wed0900", "Day"),
            ("prof_a", "ADM2000", 3, "Mon1800", "Night"),
        ]
    ]
    result = tmp_path / "old-result.json"
    # Historical solver claims are not evidence for this independent check.
    result.write_text(json.dumps({"status": "optimal", "objective": "ignored",
                                  "assignments": assignments}))
    return instance, result


@pytest.fixture(autouse=True)
def forbid_solving(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("audit must never invoke the solver")

    monkeypatch.setattr(cli, "solve_instance", forbidden)


def test_audit_legal_saved_result_is_read_only(
    audit_files: tuple[Path, Path], capsys: pytest.CaptureFixture[str],
) -> None:
    instance, result = audit_files
    before = {path.name: path.read_bytes() for path in instance.parent.iterdir()}
    assert cli.main(["audit", str(instance), "--result", str(result), "--require-scheduled"]) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["hard_rules"] == {"passed": True, "issues": []}
    assert report["unresolved"] == {"unscheduled": 0, "unstaffed": 0, "off_campus": 0}
    assert report["scheduling_gate"] == {"required": True, "passed": True}
    assert "not optimality or operational readiness" in report["scope"]
    assert not captured.err
    assert {path.name: path.read_bytes() for path in instance.parent.iterdir()} == before


@pytest.mark.parametrize("required", [False, True])
def test_legal_unscheduled_result_has_separate_optional_gate(
    audit_files: tuple[Path, Path], capsys: pytest.CaptureFixture[str], required: bool,
) -> None:
    instance, result = audit_files
    saved = json.loads(result.read_text())
    for assignment in saved["assignments"]:
        assignment.update(timeslot_id=None, classroom_id=None)
    result.write_text(json.dumps(saved))
    args = ["audit", str(instance), "--result", str(result)]
    if required:
        args.append("--require-scheduled")
    assert cli.main(args) == int(required)
    report = json.loads(capsys.readouterr().out)
    assert report["hard_rules"] == {"passed": True, "issues": []}
    assert report["unresolved"] == {"unscheduled": 3, "unstaffed": 0, "off_campus": 3}
    assert report["scheduling_gate"] == {"required": required, "passed": not required}


def test_unknown_professor_is_a_hard_error(
    audit_files: tuple[Path, Path], capsys: pytest.CaptureFixture[str],
) -> None:
    instance, result = audit_files
    saved = json.loads(result.read_text())
    saved["assignments"][0]["professor_id"] = "unknown-professor"
    result.write_text(json.dumps(saved))
    assert cli.main(["audit", str(instance), "--result", str(result)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report["hard_rules"]["passed"]
    assert any(issue["code"] == "unknown_professor" for issue in report["hard_rules"]["issues"])
    assert report["unresolved"]["unscheduled"] == 0


@pytest.mark.parametrize("change", ["empty", "missing", "duplicate"])
def test_incomplete_section_coverage_fails_even_without_null_timeslots(
    audit_files: tuple[Path, Path], capsys: pytest.CaptureFixture[str], change: str,
) -> None:
    instance, result = audit_files
    saved = json.loads(result.read_text())
    if change == "empty":
        saved["assignments"] = []
    elif change == "missing":
        saved["assignments"].pop()
    else:
        saved["assignments"].append(saved["assignments"][0])
    result.write_text(json.dumps(saved))
    assert cli.main([
        "audit", str(instance), "--result", str(result), "--require-scheduled",
    ]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["unresolved"]["unscheduled"] == 0
    assert not report["hard_rules"]["passed"]
    assert any(issue["code"] == "section_count" for issue in report["hard_rules"]["issues"])


@pytest.mark.parametrize("contents", ["{", "{}", '{"assignments": [null]}'])
def test_malformed_result_errors_are_concise(
    audit_files: tuple[Path, Path], capsys: pytest.CaptureFixture[str], contents: str,
) -> None:
    instance, result = audit_files
    result.write_text(contents)
    assert cli.main(["audit", str(instance), "--result", str(result)]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.err
    assert "warm start" not in captured.err


def test_non_utf8_result_is_a_concise_error(
    audit_files: tuple[Path, Path], capsys: pytest.CaptureFixture[str],
) -> None:
    instance, result = audit_files
    result.write_bytes(b"\xff")
    assert cli.main(["audit", str(instance), "--result", str(result)]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert "result must be UTF-8 text" in captured.err
