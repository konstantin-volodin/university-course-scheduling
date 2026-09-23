"""Reports retain clocks and arbitrary lengths of weekly meeting bundles."""

import json
import re
from typing import Any

from scheduler.report import instance_page, schedule_page


def embedded(page: str) -> dict[str, Any]:
    match = re.search(r"const DATA=(\{.*?\});\n", page, re.S)
    assert match
    return json.loads(match[1])


def test_patterns_show_different_daily_clocks_and_arbitrary_lengths() -> None:
    payload = {
        "meeting_pattern_data": [{
            "id": "custom", "time_of_day": "Morning",
            "meetings": [
                {"day": "Mon", "start_minutes": 510, "duration_minutes": 50},
                {"day": "Thu", "start_minutes": 600, "duration_minutes": 75},
            ],
        }],
        "day_of_week_set": ["Mon", "Thu"],
        "time_of_day_set": ["Morning"], "semester_set": ["Fall"],
    }
    result = {"assignments": [{
        "course_id": "C", "section_id": "1", "semester_id": "Fall",
        "timeslot_id": "custom", "time_of_day_id": "Morning",
    }]}
    meetings = [{"day": "Mon", "time": "08:30\u201309:20"},
                {"day": "Thu", "time": "10:00\u201311:15"}]
    row = embedded(schedule_page(payload, result))["assignments"][0]
    assert row["days"] == ["Mon", "Thu"]
    assert row["length"] == "50 min + 75 min"
    assert row["meetings"] == meetings
    slot = embedded(instance_page(payload))["slots"][0]
    assert slot == ["custom", "Morning", ["Mon", "Thu"], "50 min + 75 min", meetings]


def test_payload_without_clocks_keeps_legacy_description() -> None:
    payload = {"timeslot_dow_subset": [["slot", "Mon"]],
               "timeslot_block_subset": [["slot", "3.0"]]}
    slot = embedded(instance_page(payload))["slots"][0]
    assert slot[3:] == ["double", []]


def test_flexible_period_section_uses_chosen_pattern_period_and_keeps_attendance() -> None:
    payload = {
        "meeting_pattern_data": [{
            "id": "morning", "time_of_day": "Morning",
            "meetings": [{"day": "Mon", "start_minutes": 540, "duration_minutes": 50}],
        }],
        "day_of_week_set": ["Mon"], "time_of_day_set": ["Any"],
        "semester_set": ["Fall"],
        "section_subset": [["C", "1", "Fall", "Any"]],
        "section_attendance": [[['C', '1', 'Fall', 'Any'], 35]],
    }
    result = {"assignments": [{
        "course_id": "C", "section_id": "1", "semester_id": "Fall",
        "timeslot_id": "morning", "time_of_day_id": "Any",
    }]}
    schedule = embedded(schedule_page(payload, result))
    assert schedule["timesOfDay"] == ["Morning"]
    assert schedule["assignments"][0]["timeOfDay"] == "Morning"
    assert schedule["assignments"][0]["students"] == 35
    instance = embedded(instance_page(payload))
    assert instance["tods"] == ["Morning"]
    assert instance["bytod"] == [["Choice across periods", 1]]
