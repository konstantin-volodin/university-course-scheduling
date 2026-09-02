# Workload Allocation Solver

Assigns professors, meeting times, and classrooms to course sections.

## Setup

```bash
uv python install 3.14
uv sync --python 3.14 --extra dev
make check
```

## Instances

- `../instances/tiny.yaml`: single-file example
- `../instances/medium/`: split example
- `../instances/telfer/`: full instance

See [../instances/README.md](../instances/README.md) for the YAML fields.

## Commands

```bash
scheduler solve ../instances/tiny.yaml -o result.json
scheduler solve ../instances/tiny.yaml --check
scheduler solve ../instances/medium --time-limit 60
scheduler solve ../instances/telfer --solver gurobi --time-limit 600
scheduler report ../instances/medium -o instance.html
cat ../instances/tiny.yaml | scheduler solve -
```

Output goes to stdout unless `-o` is set. Progress goes to stderr.

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
  config.py      YAML loading
  instance.py    payload validation
  model.py       scheduling model
  program.py     solver-neutral MIP types
  solve.py       staged solve and results
  backends/      HiGHS and Gurobi adapters
  report.py      HTML reports
  cli.py         command line
tests/
```

Dependency direction: `config → instance → model → program`.

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
4. Maximize preferences.

Stages 1–2 use an exact gap. Stages 3–4 use a 5% gap.

## Development

```bash
make check
make test
make lint
make types
make fmt
make example
```
