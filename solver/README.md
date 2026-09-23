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

Solve output paths must be distinct and cannot refer to the input file, split
manifest or declared fragments. Checks include existing symlink and hardlink aliases
and run before the solver or log writer starts. Existing result files may still be
replaced on a successful solve; use a fresh output directory to preserve earlier runs.

```bash
scheduler solve ../instances/tiny --time-limit 30
scheduler solve ../instances/tiny --check
scheduler solve ../instances/medium --time-limit 60
scheduler solve ../instances/telfer --solver gurobi --time-limit 60
scheduler report ../instances/medium -o instance.html
cat ../instances/tiny/instance.yaml | scheduler solve - --time-limit 30
```

A file-backed solve writes `result.json`, `schedule.html`, and `instance.html`
to the instance folder's `results/` directory. `schedule.html` explains, in plain
language, every goal the solver optimised, its score, and what added to it.
A split instance directory is itself the instance folder. Use `-o` to
override the JSON path; the reports are written beside it. A solve read
from stdin continues to write JSON to stdout. Progress goes to stderr as timestamped `INFO` lines: model dimensions, search
progress, and stage objective, bound, gap, elapsed time, and status.
Use `--verbose` to also retain timestamped diagnostics in `solve.log` beside file outputs.
Use `--quiet` for warnings and errors only.

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
  solve/     staged solving, validated initialization, results, and room seeding
  backends/  HiGHS and Gurobi adapters
  report/    report rendering and frontend assets
  cli.py     command line
  audit.py   independent hard-rule checks on saved assignments
  benchmark.py  reproducible experiment records
tests/
```

The formulation follows `solve → model → config`; backend adapters translate the
solver-neutral program. The independent audit checks configuration and assignments
without calling the model builder. Package entry points expose the public API;
`backends/__init__.py` also contains the small lazy solver selector.

## Input formats

Preferred:

- single YAML file
- directory containing `instance.yaml` and referenced YAML files

Instance inputs use the YAML schema described in [the editing guide](../instances/README.md).
Legacy `/OPTIM_data/` payloads are no longer accepted by the CLI. Result files remain JSON.
The loader normalizes YAML into private model data; applications should call `config.load`
or `config.loads` before constructing an `Instance`.

Named meeting pools combine custom weekly bundles with generated candidates. The solver
chooses one whole bundle per section, sharing its professor and room across meetings.
Courses and sections can restrict eligible pools and acceptable meeting formats.
Use `--strict` (or `strict: true` in YAML) to require a named professor, listed room,
and real meeting pattern for every section.

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
`1`. The general preset defaults to `0`; `preset: telfer` defaults to `0.8`.
For example, `minimum_room_fill: 0` allows underfilled
rooms; room capacity remains a hard upper bound. The setting works in single YAML
files and split-instance manifests.

## Output

```json
{
  "status": "optimal",
  "solver": "highs",
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

- `optimal`: every stage attained an objective lower bound or reported backend
  optimality within numerical tolerances
- `feasible`: a solver-feasible result with at least one stage stopping without
  backend optimality or a lower-bound certificate; it may still contain unscheduled placeholders

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
When a feasible incumbent already attains a nonnegative objective's zero lower
bound, the stage skips search and still installs its cap. Its result records
`optimality_source: "lower_bound"`; other stages record `"backend"`.
Assignment variables are binary, including section-specific fallbacks. Teaching
and room-use indicators use bounds derived from section and timeslot capacity.
These bounds preserve the declared qualifications and legal schedules.
For HiGHS models with at least 100,000 columns, an incumbent, and a budget of
30 seconds or less, presolve is disabled and 20% of the budget is reserved for
solver completion overhead. Smaller models and longer searches retain presolve.
Objective and warm-start setup count toward the HiGHS stage budget and duration.
Reports include the full-stage backend's best bound and relative gap when
available; unavailable values appear as an em dash.

`make solve` defaults to 60 seconds per stage; override with `LIMIT=30` as needed.
Budget up to twelve times the per-stage time limit, plus preprocessing and report
generation. A 60-second limit allows up to twelve minutes of stage search; backend
overhead can exceed the requested limit, and a stage can finish without proving
optimality. This is a search budget, not a guaranteed wall-clock deadline.

## Development

```bash
make check
make test
make test-all
make lint
make types
make fmt
make example
```

`make test` runs the fast regression suite. `make test-all` includes the larger
solver integration cases; `make check` runs lint, types, and that full suite.
Report tests render a fixed schedule instead of solving another medium instance.

GitHub Actions runs `make check` on Python 3.14 using locked dependencies.
It validates all three public instances and solves the tiny example with a
30-second limit per stage. Each successful job provides downloadable JSON and
HTML reports. Full Telfer solves remain manual.
