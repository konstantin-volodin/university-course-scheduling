"""Exercise schedule filters and unscheduled details without a browser dependency."""

import json
import shutil
import subprocess
from importlib.resources import files

import pytest

from scheduler.report import schedule_page


def test_schedule_filter_controls_are_labeled_and_self_contained() -> None:
    page = schedule_page({}, {})
    assert 'aria-labelledby="lbl-scheduled"' in page
    assert 'data-scheduled="no"' in page
    assert 'data-room="off"' in page
    assert 'aria-labelledby="unscheduled-title"' in page
    assert 'id="count" role="status" aria-live="polite"' in page
    assert "No sections match these filters" in page
    assert page == schedule_page({}, {})
    assert "src=" not in page


def test_schedule_filters_keep_unscheduled_sections_inspectable() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to exercise the report JavaScript")
    script = files("scheduler.report.assets").joinpath("schedule.js").read_text()
    data = {
        "assignments": [
            {
                "id": index,
                "course": "ADM",
                "section": str(index),
                "label": f"ADM-{index}",
                "semester": "Fall",
                "professor": None if index == 1 else "Faculty",
                "room": None if index == 1 else "R1",
                "slot": None if index == 1 else "M1",
                "days": [] if index == 1 else ["Mon"],
                "timeOfDay": "Morning",
                "length": "single",
                "students": 20,
            }
            for index in range(2)
        ],
        "days": ["Mon"],
        "timesOfDay": ["Morning"],
        "semesters": ["Fall"],
        "rooms": {"R1": 40},
        "summary": {"total": 2, "namedPct": 50, "bySemester": []},
        "stages": [],
    }
    harness = r"""
const assert=require('node:assert/strict');
const elements={}, listeners={};
function element(){return {innerHTML:'',hidden:false,appendChild(){},
  querySelector(){return {}},classList:{remove(){},toggle(){}}};}
const document={
  getElementById(id){return elements[id]||(elements[id]=element());},
  createElement:element, querySelectorAll(){return [];},
  addEventListener(type,handler){listeners[type]=handler;}
};
function filter(key,value){
  const button={dataset:{[key]:value},setAttribute(){}};
  button.parentNode={children:[button]};
  listeners.click({target:{closest(selector){
    return selector.startsWith('#semseg')?button:null;
  }}});
}
"""
    assertions = r"""
assert.equal(elements.unscheduled.hidden,false);
assert.match(elements.unscheduledrows.innerHTML,/ADM-1/);
filter('scheduled','no');
assert.equal(elements.gridwrap.hidden,true);
assert.match(elements.count.innerHTML,/<b>1<\/b> sections shown/);
const chip={dataset:{row:'1'},classList:{contains(){return false;}}};
listeners.click({target:{closest(selector){return selector==='.chip'?chip:null;}}});
assert.match(elements.detail.innerHTML,/Not assigned/);
assert.doesNotMatch(elements.detail.innerHTML,/null \(single\)/);
filter('staff','fac');
assert.equal(elements.emptyresults.hidden,false);
assert.equal(elements.unscheduled.hidden,true);
assert.equal(elements.detail.hidden,true);
filter('scheduled','all');
filter('staff','all');
filter('room','off');
assert.equal(elements.emptyresults.hidden,true);
assert.match(elements.unscheduledrows.innerHTML,/ADM-1/);
filter('room','on');
assert.equal(elements.unscheduled.hidden,true);
assert.equal(elements.gridwrap.hidden,false);
assert.match(elements.body.innerHTML,/ADM-0/);
"""
    completed = subprocess.run(
        [node, "-e", "const DATA=" + json.dumps(data) + ";" + harness + script + assertions],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
