"""The HTML report pages: generated from the payload, not hand-written."""

from __future__ import annotations

import json
import re
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
    from scheduler.instance import Instance
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


@pytest.mark.parametrize("kind", ["schedule", "instance"])
def test_pages_reach_out_for_the_webfont_and_nothing_else(payload, result, kind: str) -> None:
    """A page about real staffing fetches the brand faces, and nothing else."""
    html = (
        report.schedule_page(payload, result)
        if kind == "schedule"
        else report.instance_page(payload)
    )
    for forbidden in ("http://", "src=", "@import", "url("):
        assert forbidden not in html, f"{kind} page reaches out via {forbidden!r}"
    hosts = {u.split('"')[0].split("/")[0] for u in html.split('href="https://')[1:]}
    assert hosts == {"fonts.googleapis.com", "fonts.gstatic.com"}


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
    rows = _embedded(report.schedule_page(payload, result))["r"]
    assert len(rows) == len(result["assignments"])
    # the part-timer fallback surfaces as null, never as the reserved id
    assert all(r[0] != "part-timer" for r in rows)
    nulls = sum(1 for r in rows if r[0] is None)
    assert nulls == result["summary"]["unstaffed"]


def test_schedule_rows_carry_the_meeting_pattern(payload, result) -> None:
    rows = _embedded(report.schedule_page(payload, result))["r"]
    days_by_slot = report._slot_days(payload)
    assert rows, "no assignments to check"
    for row in rows:
        assert row[7] == days_by_slot[row[4]]


def test_schedule_labels_do_not_repeat_the_course(payload, result) -> None:
    rows = _embedded(report.schedule_page(payload, result))["r"]
    assert rows
    for row in rows:
        course, section, label = str(row[1]), str(row[2]), str(row[10])
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
    rows = _embedded(report.schedule_page(doubled, result))["r"]
    moved = [r for r in rows if r[4] == slot]
    assert moved and all(len(r[7]) == 2 for r in moved)


def test_instance_page_counts_supply_against_demand(payload) -> None:
    data = _embedded(report.instance_page(payload))
    loads = dict(report._pairs(payload["professor_teaching"]))
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
    assert _embedded(page.read_text())["r"]
