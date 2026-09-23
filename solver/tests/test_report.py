"""The HTML report pages: generated from the payload, not hand-written."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scheduler import config, report
from scheduler.cli import main

INSTANCES = Path(__file__).parents[2] / "instances"
TINY = INSTANCES / "tiny"
MEDIUM = INSTANCES / "medium"


@pytest.fixture(scope="module")
def payload() -> dict[str, Any]:
    return config.load(MEDIUM)


@pytest.fixture(scope="module")
def result(payload: dict[str, Any]) -> dict[str, Any]:
    from scheduler.config.instance import Instance
    from scheduler.progress import silent
    from scheduler.solve import solve_instance

    solved = solve_instance(Instance.from_payload(payload), silent, time_limit=20)
    return solved.to_dict()


def _embedded(html: str) -> dict[str, Any]:
    match = re.search(r"const DATA=(\{.*?\});\n", html, re.S)
    assert match, "page carries no embedded data"
    return json.loads(match.group(1))


def _is_a_document(html: str) -> None:
    """A file on disk has to open in a browser on its own."""
    assert html.startswith("<!doctype html>")
    for tag in ("<html", "<head", "<body", "</body>", "</html>"):
        assert tag in html
    assert html.count("<script") == html.count("</script>")
    assert html.count("<style") == html.count("</style>")


def test_schedule_page_is_a_self_contained_document(payload, result) -> None:
    _is_a_document(report.schedule_page(payload, result))


def test_schedule_page_keeps_objective_details_out_of_the_schedule(payload, result) -> None:
    page = report.schedule_page(payload, result)
    assert "Preference breakdown" not in page
    assert "preferenceBreakdown" not in _embedded(page)


def test_objective_audit_caps_large_term_detail_without_changing_result() -> None:
    terms = [
        {
            "variable": f"x_{index}",
            "coefficient": 1 if index % 2 else -3,
            "value": 1,
            "contribution": 1 if index % 2 else -3,
        }
        for index in range(100)
    ]
    result = {
        "status": "optimal",
        "solver": "test",
        "objective": -100,
        "stages": [],
        "preference_breakdown": [
            {
                "name": "example",
                "label": "Example preference",
                "description": "A test component",
                "raw_value": 100,
                "weight": -1,
                "contribution": -100,
                "terms": terms,
            }
        ],
    }

    markdown = report.objective_markdown(result)

    assert "| Example preference | A test component | 100.00 | -1.00 | -100.00 |" in markdown
    assert "Active terms: 100; showing 12; omitted 88." in markdown
    assert "[result.json](result.json)" in markdown
    assert "| -3.00 | 38 | 38.00 | -114.00 |" in markdown
    assert "| 1.00 | 50 | 50.00 | 50.00 |" in markdown
    assert "`x_0`" in markdown
    assert "`x_99`" not in markdown
    assert len(markdown) < 4_000


def test_objective_audit_preserves_component_rows_and_does_not_mutate_result() -> None:
    result = {
        "preference_breakdown": [
            {
                "name": "empty",
                "label": "Empty component",
                "description": "No active terms",
                "raw_value": 0,
                "weight": 2,
                "contribution": 0,
            }
        ]
    }
    before = json.dumps(result, sort_keys=True)

    markdown = report.objective_markdown(result)

    assert "| Empty component | No active terms | 0.00 | 2.00 | 0.00 |" in markdown
    assert json.dumps(result, sort_keys=True) == before


@pytest.mark.parametrize("kind", ["schedule", "instance"])
def test_pages_do_not_require_external_assets(payload, result, kind: str) -> None:
    html = (
        report.schedule_page(payload, result)
        if kind == "schedule"
        else report.instance_page(payload)
    )
    for forbidden in ("http://", "https://", "src=", "@import", "url("):
        assert forbidden not in html, f"{kind} page reaches out via {forbidden!r}"


def test_embedded_data_cannot_close_its_script(payload, result) -> None:
    malicious = deepcopy(result)
    malicious["assignments"][0]["course_id"] = "</script><script>alert(1)</script>"

    page = report.schedule_page(payload, malicious)

    assert "</script><script>alert(1)</script>" not in page
    assert _embedded(page)["assignments"][0]["course"] == "</script><script>alert(1)</script>"


@pytest.mark.parametrize("kind", ["schedule", "instance"])
def test_pages_are_byte_identical_across_runs(payload, result, kind: str) -> None:
    """Regenerating must not churn the committed files."""
    make = (
        (lambda: report.schedule_page(payload, result))
        if kind == "schedule"
        else (lambda: report.instance_page(payload))
    )
    assert make() == make()


def test_schedule_page_carries_every_assignment(payload, result) -> None:
    rows = _embedded(report.schedule_page(payload, result))["assignments"]
    assert len(rows) == len(result["assignments"])
    # the part-timer fallback surfaces as null, never as the reserved id
    assert all(row["professor"] != "part-timer" for row in rows)
    nulls = sum(1 for row in rows if row["professor"] is None)
    assert nulls == result["summary"]["unstaffed"]


def test_schedule_rows_carry_the_meeting_pattern(payload, result) -> None:
    rows = _embedded(report.schedule_page(payload, result))["assignments"]
    days_by_slot: dict[str, list[str]] = {}
    for slot, day in payload["timeslot_dow_subset"]:
        days_by_slot.setdefault(slot, []).append(day)
    assert rows, "no assignments to check"
    for row in rows:
        assert row["days"] == days_by_slot[row["slot"]]


def test_schedule_labels_do_not_repeat_the_course(payload, result) -> None:
    rows = _embedded(report.schedule_page(payload, result))["assignments"]
    assert rows
    for row in rows:
        course, section, label = row["course"], row["section"], row["label"]
        expected = section if section.startswith(f"{course}-") else f"{course}-{section}"
        assert label == expected
        assert not label.startswith(f"{course}-{course}-")


def test_reports_keep_explanatory_copy_short(payload, result) -> None:
    pages = report.instance_page(payload) + report.schedule_page(payload, result)
    stale_copy = (
        "Who can teach, and what they will accept",
        "Where the demand sits",
        "Read together",
        "however good",
        "which matters because",
        "Timeslots are fixed patterns, not free hours",
        "Every section the solver placed",
    )
    assert all(text not in pages for text in stale_copy)


def test_a_two_day_slot_carries_both_days(payload, result) -> None:
    """The grid draws one cell per day, so a Mon+Thu section must carry both.

    The medium instance is single-day throughout, so the pattern is injected here
    rather than left to the fixture to happen to contain one.
    """
    assignment = result["assignments"][0]
    slot = assignment["timeslot_id"]
    doubled = dict(payload)
    doubled["timeslot_dow_subset"] = [
        *payload["timeslot_dow_subset"],
        [slot, "Thu" if [slot, "Thu"] not in payload["timeslot_dow_subset"] else "Wed"],
    ]
    rows = _embedded(report.schedule_page(doubled, result))["assignments"]
    moved = [row for row in rows if row["slot"] == slot]
    assert moved and all(len(row["days"]) == 2 for row in moved)


def test_instance_page_counts_supply_against_demand(payload) -> None:
    data = _embedded(report.instance_page(payload))
    loads = {
        professor: load
        for row in payload["professor_teaching"]
        for professor, load in row.items()
    }
    assert data["supply"]["capacity"] == sum(loads.values())
    assert data["supply"]["demand"] == len(payload["section_subset"])
    assert data["supply"]["gap"] == max(
        0, data["supply"]["demand"] - data["supply"]["capacity"]
    )


def test_instance_page_shows_every_timeslot(payload) -> None:
    """Including any slot the solver never used — this is the input, not the answer."""
    data = _embedded(report.instance_page(payload))
    assert {s[0] for s in data["slots"]} == {str(t) for t in payload["timeslot_set"]}


def test_instance_page_is_a_self_contained_document(payload) -> None:
    _is_a_document(report.instance_page(payload))


def test_cli_writes_both_pages(tmp_path: Path) -> None:
    out = tmp_path / "instance.html"
    assert main(["report", str(MEDIUM), "-o", str(out)]) == 0
    assert out.read_text().startswith("<!doctype html>")

    res = tmp_path / "r.json"
    assert main(["solve", str(TINY), "-q", "-o", str(res),
                 "--time-limit", "20"]) == 0
    page = tmp_path / "schedule.html"
    assert main(["report", str(TINY), "--result", str(res),
                 "-o", str(page)]) == 0
    assert "Solved Schedule" in page.read_text()


def test_solve_html_flag_writes_the_same_page(tmp_path: Path) -> None:
    res, page = tmp_path / "r.json", tmp_path / "s.html"
    assert main(["solve", str(TINY), "-q", "-o", str(res),
                 "--time-limit", "20", "--html", str(page)]) == 0
    _is_a_document(page.read_text())
    assert _embedded(page.read_text())["assignments"]
