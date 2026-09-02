"""Same instance in, same schedule out.

This is not a nicety. The preference stages stop at the first solution within
GOOD_ENOUGH of optimal, so the answer depends on the order the model was built
in — and Python randomises string hashing per process, which reorders any
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

import pytest

TINY = Path(__file__).parents[2] / "instances" / "tiny.yaml"

SCRIPT = """
import json, sys
from scheduler import config, solve, silent
result = solve(config.load(sys.argv[1]), progress=silent)
print(json.dumps({
    "objective": result.objective,
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


@pytest.mark.slow
def test_identical_across_processes_with_different_hash_seeds() -> None:
    runs = [solve_in_subprocess(seed) for seed in ("0", "1", "12345")]
    first = runs[0]
    for other in runs[1:]:
        assert other["objective"] == first["objective"]
        assert other["assignments"] == first["assignments"]


def test_identical_within_a_process() -> None:
    from scheduler import config, silent, solve

    payload = config.load(TINY)

    first = solve(payload, progress=silent)
    second = solve(payload, progress=silent)

    assert first.objective == second.objective
    assert first.assignments == second.assignments


def test_solving_does_not_mutate_the_payload() -> None:
    """A caller reusing their payload must get the same instance back."""
    import copy

    from scheduler import config, silent, solve

    payload = config.load(TINY)

    before = copy.deepcopy(payload)
    solve(payload, progress=silent)
    assert payload == before
