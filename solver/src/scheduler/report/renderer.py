"""Render an instance, or a solved schedule, as a standalone HTML page.

    scheduler report config.yaml -o instance.html
    scheduler report config.yaml --result result.json -o schedule.html

Both pages are one self-contained file: no build step, no template engine.
The data is embedded as JSON and the page draws itself, so the file keeps
working after the repo moves.
"""

from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from importlib import resources
from typing import Any

from ..config import OFF_CAMPUS, PART_TIMER

__all__ = ["instance_page", "schedule_page"]


def _asset(name: str) -> str:
    return resources.files("scheduler.report.assets").joinpath(name).read_text(encoding="utf-8")

_DISPLAY = '"Helvetica Neue",Arial,sans-serif'
_SANS = '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif'
_MONO = 'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace'

_CSS = _asset("base.css")


def _doc(title: str, body: str, data: Any, script: str) -> str:
    """Wrap a page body into a complete, self-contained HTML document."""
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
        f"{body}\n"
        f"<script>\nconst DATA={_json_for_script(data)};\n</script>\n"
        f"<script>\n{script}\n</script>\n</body>\n</html>\n"
    )


def _json_for_script(data: Any) -> str:
    """Encode data without allowing it to close the surrounding script tag."""
    return (
        json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


# --------------------------------------------------------------------------- #
# shared payload readers
# --------------------------------------------------------------------------- #

def _pairs(rows: Any) -> list[tuple[Any, Any]]:
    """``[["a","b"], {"a": 1}]`` -> ``[("a","b"), ("a",1)]`` — both shapes occur.

    Keys are usually ids, but ``section_attendance`` keys on the 4-tuple, so
    neither side is narrowed to ``str`` here.
    """
    out: list[tuple[Any, Any]] = []
    for row in rows or []:
        if isinstance(row, dict):
            if "key" in row:
                out.append((row["key"], row.get("value")))
            else:
                out.extend(row.items())
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            out.append((row[0], row[1] if len(row) == 2 else list(row[1:])))
    return out


def _slot_days(payload: Any) -> dict[str, list[str]]:
    days: dict[str, list[str]] = defaultdict(list)
    for slot, day in _pairs(payload.get("timeslot_dow_subset")):
        days[slot].append(day)
    return dict(days)


def _slot_len(payload: Any) -> dict[str, str]:
    # block type is the meeting length in hours; "3.0" is the double block.
    return {s: ("double" if str(b) == "3.0" else "single")
            for s, b in _pairs(payload.get("timeslot_block_subset"))}


def _slot_tod(payload: Any) -> dict[str, str]:
    return dict(_pairs(payload.get("timeslot_tod_subset")))


def _order(payload: Any, key: str, fallback: list[str]) -> list[str]:
    got = [str(x) for x in payload.get(key) or []]
    ranked = [f for f in fallback if f in got]
    return ranked + [g for g in got if g not in ranked]


_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_TODS = ["Morning", "Afternoon", "Evening", "Night"]


# --------------------------------------------------------------------------- #
# the solved schedule
# --------------------------------------------------------------------------- #

_SCHEDULE_BODY = _asset("schedule.html")
_SCHEDULE_JS = _asset("schedule.js")


def schedule_page(payload: Any, result: Any, *, title: str = "Solved Schedule") -> str:
    """The solved schedule as a week grid, one per semester."""
    days_of = _slot_days(payload)
    len_of = _slot_len(payload)
    students = {
        tuple(str(part) for part in key): value
        for key, value in _pairs(payload.get("section_attendance"))
        if isinstance(key, (list, tuple)) and len(key) == 4
    }
    rooms = {str(k): v for k, v in _pairs(payload.get("classroom_cap"))}

    rows = []
    for row_id, a in enumerate(result.get("assignments", [])):
        slot = a.get("timeslot_id")
        room = a.get("classroom_id")
        prof = a.get("professor_id")
        course = str(a.get("course_id"))
        section = str(a.get("section_id"))
        semester = str(a.get("semester_id"))
        time_of_day = str(a.get("time_of_day_id"))
        rows.append(
            {
                "id": row_id,
                "professor": None if prof in (None, PART_TIMER) else prof,
                "course": course,
                "section": section,
                "semester": semester,
                "slot": slot,
                "room": None if room in (None, OFF_CAMPUS) else room,
                "timeOfDay": time_of_day,
                "days": days_of.get(slot, []),
                "length": len_of.get(slot, "single"),
                "students": students.get((course, section, semester, time_of_day)),
                "label": _section_label(course, section),
            }
        )

    summary = result.get("summary") or {}
    data = {
        "assignments": rows,
        "rooms": rooms,
        "days": _order(payload, "day_of_week_set", _DAYS),
        "timesOfDay": _order(payload, "time_of_day_set", _TODS),
        "semesters": [str(s) for s in payload.get("semester_set") or []],
        "summary": {"unscheduled": summary.get("unscheduled", 0)},
        "stages": result.get("stages") or [],
    }
    body = _SCHEDULE_BODY.format(
        eyebrow=html.escape(
            f"{len(rows)} sections · solver: {result.get('solver', 'n/a')} "
            f"· status: {result.get('status', 'n/a')}"
        ),
        heading=html.escape(title),
    )
    return _doc(title, body, data, _SCHEDULE_JS)


def _section_label(course: Any, section: Any) -> str:
    """Return a section label without repeating a course already in its id."""
    course_id = str(course)
    section_id = str(section)
    if section_id == course_id or section_id.startswith(f"{course_id}-"):
        return section_id
    return f"{course_id}-{section_id}"


# --------------------------------------------------------------------------- #
# the instance behind it
# --------------------------------------------------------------------------- #

_INSTANCE_BODY = _asset("instance.html")
_INSTANCE_JS = _asset("instance.js")


def instance_page(payload: Any, *, title: str = "Scheduling Instance") -> str:
    """The inputs: the week on offer, who can teach, what must be covered."""
    days_of = _slot_days(payload)
    len_of = _slot_len(payload)
    tod_of = _slot_tod(payload)
    loads = {str(k): int(v) for k, v in _pairs(payload.get("professor_teaching"))}
    rooms = sorted(((str(k), int(v)) for k, v in _pairs(payload.get("classroom_cap"))),
                   key=lambda kv: -kv[1])
    sections = [tuple(str(x) for x in s) for s in payload.get("section_subset") or []]
    sizes = [int(v) for _, v in _pairs(payload.get("section_attendance"))]

    n_prof = len(loads)
    capacity = sum(loads.values())
    demand = len(sections)
    night = sum(1 for _, v in _pairs(payload.get("professor_can_teach_night")) if v)
    offc = sum(1 for _, v in _pairs(payload.get("professor_can_teach_out_DMS")) if v)
    packed = sum(1 for _, v in _pairs(payload.get("professor_pack_day_pref")) if v)
    courses = [str(c) for c in payload.get("course_set") or []]

    by_sem = Counter(s[2] for s in sections)
    by_tod = Counter(s[3] for s in sections)
    load_hist = Counter(loads.values())

    bands = [(0, 40), (41, 80), (81, 120), (121, 200), (201, 10**9)]
    labels = ["≤40", "41-80", "81-120", "121-200", "200+"]
    size_hist = [
        [labels[i], sum(1 for s in sizes if lo <= s <= hi)]
        for i, (lo, hi) in enumerate(bands)
    ]

    sem_order = [str(s) for s in payload.get("semester_set") or []]
    data = {
        "stats": [
            [n_prof, "professors", ""],
            [len(courses), "courses", ""],
            [demand, "sections to cover", ""],
            [len(days_of), "timeslots", ""],
            [len(rooms), "rooms", ""],
            [max(0, demand - capacity), "part-time gap", "pt"],
        ],
        "supply": {"capacity": capacity, "demand": demand, "gap": max(0, demand - capacity)},
        "bysem": (
            [[s, by_sem.get(s, 0)] for s in sem_order]
            or [[s, n] for s, n in sorted(by_sem.items())]
        ),
        "bytod": [[t, by_tod.get(t, 0)] for t in _order(payload, "time_of_day_set", _TODS)],
        "perms": [
            ["Can teach night", night],
            ["Can go off campus", offc],
            ["Prefer packed days", packed],
        ],
        "nprof": n_prof,
        "loadhist": [[str(k), load_hist[k]] for k in sorted(load_hist)],
        "sizehist": size_hist,
        "days": _order(payload, "day_of_week_set", _DAYS),
        "tods": _order(payload, "time_of_day_set", _TODS),
        "slots": sorted(
            ([s, tod_of.get(s, ""), days_of.get(s, []), len_of.get(s, "single")]
             for s in days_of),
            key=lambda r: str(r[0]),
        ),
        "rooms": [[r, cap, sum(1 for s in sizes if s <= cap)] for r, cap in rooms],
    }
    body = _INSTANCE_BODY.format(
        eyebrow=html.escape(
            f"{n_prof} professors · {len(courses)} courses · {demand} sections "
            f"· {len(rooms)} rooms"
        ),
        heading=html.escape(title),
    )
    return _doc(title, body, data, _INSTANCE_JS)
