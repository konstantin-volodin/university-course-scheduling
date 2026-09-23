# Workload Allocation Solver

Assigns professors, meeting times, and classrooms to course sections.

## Setup

```bash
uv python install 3.14
uv sync --python 3.14 --extra dev
make check
```

## Instances

- `../instances/tiny/`: minimal example
- `../instances/medium/`: split example
- `../instances/telfer/`: full instance

See [../instances/README.md](../instances/README.md) for the YAML fields.

## Commands

```bash
scheduler solve ../instances/tiny --time-limit 30
scheduler solve ../instances/tiny --check
scheduler solve ../instances/medium --time-limit 60
scheduler solve ../instances/telfer --solver gurobi --time-limit 600
scheduler report ../instances/medium -o instance.html
cat ../instances/tiny/instance.yaml | scheduler solve - --time-limit 30
```

A file-backed solve writes `result.json`, `schedule.html`, `instance.html`,
`objective.md`, and `solve.log` to the instance folder's `results/` directory.
A split instance directory is itself the instance folder. Use `-o` to
override the JSON path; the reports and log are written beside it. A solve read
from stdin continues to write JSON to stdout. Progress goes to stderr.

Exit codes:

- `0`: success
- `1`: solve or I/O error
- `2`: invalid instance

Always set a time limit for large instances. The limit applies to each solve stage.

## Solvers

HiGHS is the default. Gurobi is optional:

```bash
uv sync --extra gurobi
```

The free Gurobi license is too small for medium and full instances.

## Source layout

```text
src/scheduler/
  config/    YAML loading and payload validation
  model/     scheduling formulation and solver-neutral MIP types
  solve/     staged solving, results, and room seeding
  backends/  HiGHS and Gurobi adapters
  report/    report rendering and frontend assets
  cli.py     command line
tests/
```

Dependency direction: `cli → solve → model → config`, with `backends` and
`report` as leaves. Every `__init__.py` is re-exports only; cross-package
imports go through them rather than reaching into a submodule.

## Input formats

Preferred:

- single YAML file
- directory containing `instance.yaml` and referenced YAML files

Legacy flat JSON payloads remain supported. Required keys are listed in
`scheduler.PAYLOAD_KEYS`.

Reserved IDs:

- professor: `part-timer`
- classroom: `other`
- meeting-time prefix: `placeholder_`

Reserved IDs are returned as `null` assignments.

Declared qualifications are preserved throughout solving, including
`qualified_for: all` and its default. Course ranks reward preferred assignments;
they never remove non-preferred courses from a professor's qualifications.
Instances with broad qualifications can therefore build larger models.

The optional top-level `minimum_room_fill` policy accepts a fraction from `0` to
`1` and defaults to `0.8`. For example, `minimum_room_fill: 0` allows underfilled
rooms; room capacity remains a hard upper bound. The setting works in single YAML
files and split-instance manifests.

## Output

```json
{
  "status": "optimal",
  "solver": "highs",
  "objective": -17.0,
  "assignments": [
    {
      "professor_id": "prof_a",
      "course_id": "ADM2000",
      "section_id": 3,
      "semester_id": "Fall",
      "timeslot_id": "Mon1800",
      "classroom_id": "DMS1150",
      "time_of_day_id": "Night",
      "solution_value": 1.0
    }
  ],
  "stages": [],
  "summary": {
    "assignments": 3,
    "unstaffed": 0,
    "unscheduled": 0,
    "off_campus": 0
  }
}
```

Status values:

- `optimal`: every stage proved its bound
- `feasible`: a valid result without full proof

Summary fields:

- `unstaffed`: no named professor
- `unscheduled`: no meeting time
- `off_campus`: no listed room

## Solve stages

1. Minimize teaching-load violations.
2. Minimize concurrency conflicts and unscheduled sections.
3. Minimize off-campus assignments.
4. Minimize part-timer use of physical rooms.
5. Balance time-of-day and day-of-week use.
6. Minimize course block violations.
7. Minimize Friday-night penalties.
8. Minimize room changes.
9. Minimize additional teaching days.
10. Maximize course, time, and block preference rewards.

Stages 3, 8, and 10 use a 5% gap; the others use an exact gap.
Each minimization stage caps its result before the next stage starts.
Budget up to ten times the per-stage time limit, plus preprocessing and report
generation. A 900-second limit allows up to 2.5 hours across the ten stages.

## Development

```bash
make check
make test
make lint
make types
make fmt
make example
```

GitHub Actions runs `make check` on Python 3.14 using locked dependencies.
It validates all three public instances and solves the tiny example with a
30-second limit per stage. Each successful job provides downloadable JSON and
HTML reports plus the objective audit. Full Telfer solves remain manual.
