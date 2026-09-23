"""Same instance in, same schedule out.

The answer depends on the order the model was built, and Python randomises
string hashing per process, which reorders any
iteration over a set. Before the sorting and the fixed thread count went in,
running the same instance twice returned different schedules with different
objective values. A scheduling tool that does that cannot be trusted or
debugged, so it gets its own test, run in real subprocesses where hash
randomisation is actually in play.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TINY = Path(__file__).parents[2] / "instances" / "tiny"

SCRIPT = """
import json, sys
from scheduler import config, solve, silent
result = solve(config.load(sys.argv[1]), progress=silent)
print(json.dumps({
    "stages": [(stage.key, stage.value) for stage in result.stages],
    "assignments": [
        [a.professor_id, a.course_id, a.section_id, a.timeslot_id, a.classroom_id]
        for a in result.assignments
    ],
}))
"""


def solve_in_subprocess(seed: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(TINY)],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": seed, "HOME": str(Path.home())},
    )
    return json.loads(completed.stdout)


def test_identical_across_processes_with_different_hash_seeds() -> None:
    runs = [solve_in_subprocess(seed) for seed in ("0", "1", "12345")]
    first = runs[0]
    for other in runs[1:]:
        assert other["stages"] == first["stages"]
        assert other["assignments"] == first["assignments"]


def test_repeated_solves_are_deterministic_and_preserve_input() -> None:
    import copy

    from scheduler import config, silent, solve

    payload = config.load(TINY)
    before = copy.deepcopy(payload)
    first = solve(payload, progress=silent, time_limit=10)
    assert payload == before
    second = solve(payload, progress=silent, time_limit=10)
    assert payload == before
    assert [(stage.key, stage.value) for stage in first.stages] == [
        (stage.key, stage.value) for stage in second.stages
    ]
    assert first.assignments == second.assignments
