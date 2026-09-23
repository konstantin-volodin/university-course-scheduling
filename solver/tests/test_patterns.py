from copy import deepcopy

import pytest

from scheduler.config.patterns import Meeting, MeetingPattern, overlaps, parse_patterns
from scheduler.errors import InvalidInstanceError


def generation():
    return {
        "standard": {
            "generate": {
                "formats": [
                    {"meetings": 2, "minutes_each": 75, "day_combinations": [["Mon", "Thu"]]}
                ],
                "start_times": ["08:30", "10:00"],
            }
        }
    }


def test_independent_starts_and_same_start():
    raw = generation()
    patterns, pools = parse_patterns(raw)
    assert len(patterns) == len(pools["standard"]) == 4
    assert any(len({m.start_minutes for m in p.meetings}) == 2 for p in patterns.values())
    raw["standard"]["generate"]["same_start"] = True
    assert len(parse_patterns(raw)[0]) == 2


def test_window_finish_and_determinism():
    raw = generation()
    config = raw["standard"]["generate"]
    config["start_times"] = {"start": "08:30", "end": "10:00", "every_minutes": 30}
    config["finish_by"] = "10:15"
    first = parse_patterns(raw)
    assert len(first[0]) == 4
    config["formats"][0]["day_combinations"] = [["Thu", "Mon"], ["Mon", "Thu"]]
    assert parse_patterns(raw) == first


def test_custom_deduplication_across_pools():
    raw = generation()
    raw["custom"] = {
        "custom": {
            "special": [
                {"day": "Mon", "start": "08:30", "minutes": 75},
                {"day": "Thu", "start": "10:00", "minutes": 75},
            ]
        }
    }
    patterns, pools = parse_patterns(raw)
    assert len(patterns) == 4
    assert pools["custom"] == ("special",)
    assert "special" in pools["standard"]
    assert parse_patterns(dict(reversed(list(raw.items())))) == (patterns, pools)


def test_overlap_half_open_and_day_specific():
    a = MeetingPattern("a", (Meeting("Mon", 510, 75), Meeting("Thu", 600, 75)))
    assert overlaps(a, MeetingPattern("b", (Meeting("Thu", 650, 50),)))
    assert not overlaps(a, MeetingPattern("b", (Meeting("Thu", 675, 50),)))
    assert not overlaps(a, MeetingPattern("b", (Meeting("Tue", 510, 75),)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("same_start", "yes"),
        ("start_times", ["25:00"]),
        ("start_times", []),
        ("finish_by", "07:00"),
        ("typo", 1),
    ],
)
def test_generator_validation(field, value):
    raw = deepcopy(generation())
    raw["standard"]["generate"][field] = value
    with pytest.raises(InvalidInstanceError, match=r"meeting_patterns\.standard\.generate"):
        parse_patterns(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("minutes_each", True),
        ("minutes_each", 0),
        ("minutes_each", 1.5),
        ("day_combinations", [["Mon", "Mon"]]),
        ("day_combinations", [["Monday", "Thu"]]),
        ("day_combinations", [["Mon"]]),
    ],
)
def test_format_validation(field, value):
    raw = generation()
    raw["standard"]["generate"]["formats"][0][field] = value
    with pytest.raises(InvalidInstanceError):
        parse_patterns(raw)


def test_custom_crosses_midnight():
    with pytest.raises(InvalidInstanceError, match="finish within"):
        parse_patterns(
            {
                "x": {
                    "custom": {
                        "late": [
                            {"day": "Mon", "start": "23:30", "minutes": 60},
                        ]
                    }
                }
            }
        )


def test_single_meeting_days_shorthand():
    raw = generation()
    raw["standard"]["generate"]["formats"] = [
        {"meetings": 1, "minutes_each": 50, "days": ["Mon", "Tue"]}
    ]
    assert len(parse_patterns(raw)[0]) == 4


def test_any_is_reserved_for_section_eligibility():
    raw = generation()
    raw["standard"]["time_of_day"] = "Any"
    with pytest.raises(InvalidInstanceError, match="Any is reserved"):
        parse_patterns(raw)
