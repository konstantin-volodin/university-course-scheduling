# Instances

| Path | Format | Size |
|---|---|---|
| `tiny/` | one file | 3 sections |
| `medium/` | split files | 36 sections |
| `telfer/` | split files | 426 sections |

## Setup

```bash
cd solver
uv python install 3.14
uv sync --python 3.14 --extra dev
cd ..
cp -R instances/tiny instances/my-university
# Or: cp -R instances/medium instances/my-university
```

## Split format

```text
my-university/
├── instance.yaml
├── meeting-times.yaml
├── classrooms.yaml
├── professors.yaml
├── courses.yaml
├── course-concurrency.yaml  # optional
└── programs.yaml            # optional
```

`instance.yaml`:

```yaml
semesters: [Fall, Winter]
files:
  meeting_times: meeting-times.yaml
  classrooms: classrooms.yaml
  professors: professors.yaml
  courses: courses.yaml
  course_concurrency: course-concurrency.yaml
```

A category may use several files:

```yaml
professors: [professors/business.yaml, professors/science.yaml]
courses: [courses/business.yaml, courses/science.yaml]
```

Paths are relative to `instance.yaml`. IDs must be unique across files.

## Meeting times

```yaml
- id: MW-0900
  days: {Mon: "09:00", Wed: "09:00"}
  duration_minutes: 90
  time_of_day: Morning
```

- Quote times and use the 24-hour clock.
- `duration_minutes`: `90` or `180`.
- Different daily starts are allowed: `{Mon: "08:30", Thu: "10:00"}`.
- Keep the names `Fri` and `Night` when using Friday/night rules.

## Classrooms

```yaml
SCI-201: 80
LIB-100: 160
```

Rooms must fit the section. By default they must also be at least 80% full.
Set top-level `minimum_room_fill` in `instance.yaml` to a fraction from 0 to 1
to change that institutional policy; `minimum_room_fill: 0` disables only the
minimum-fill rule, not the capacity upper bound. The setting also works in a
single-file instance.

`other` is reserved.

## Professors

```yaml
smith-jordan:
  teaching_load: 2
  qualified_for: [BIO101, BIO205]
  can_teach_night: true
  availability:
    Fall: {Morning: 3, Afternoon: 1}
  course_ranks: {BIO205: 3}
```

Required: `teaching_load`.

Optional:

- `qualified_for: all` (the default when omitted) or a list of course ids
- `can_teach_night` (default `false`)
- `can_teach_off_campus` (default `false`)
- `prefers_packed_days` (default `false`)
- `preferred_class_length`: `single` or `double`
- `availability`: preference scores
- `course_ranks`: preference scores

Preference scores: `0` or omitted = none; higher values = stronger. `part-timer`
is reserved.

## Flag defaults

When most entries share one flag value, declare it once in `instance.yaml` and
list only the exceptions:

```yaml
professor_defaults: {can_teach_night: true, can_teach_off_campus: true}
course_defaults: {penalise_friday_night: true}
```

`professor_defaults` accepts `can_teach_night`, `can_teach_off_campus`,
`prefers_packed_days`, and `preferred_class_length`; `course_defaults` accepts
`penalise_friday_night` and `preferred_class_length`. A flag on an individual
professor or course overrides the declared default. Note that a
`preferred_class_length` default applies to *every* entry that omits it —
including ones that previously had no preference — so only declare it when
that is what you mean.

## Courses

```yaml
BIO101:
  preferred_class_length: single
  penalise_friday_night: true
  sections:
    - id: BIO101-1
      semester: Fall
      time_of_day: Morning
      students: 72
```

Section IDs must be unique. Semesters and time-of-day names must already exist.

Optional concurrency rules:

```yaml
- {courses: [BIO101, BIO205], semester: Fall, must_run: apart}
- {courses: [BIO101, BIO205, BIO305], must_run: apart}
```

`apart` penalizes overlap, including distinct meeting IDs that overlap on the
clock. `together` penalizes unequal section counts at the same meeting ID and
takes exactly two courses. These are soft rules for named-faculty assignments;
part-timer and unscheduled fallbacks are exempt. Violations are minimized before
preferences, but a returned schedule can still contain violations. Omit
`semester` (or pass a list) to cover every semester; listing more than two
courses under `apart` applies the rule to every pair.

## Programs

A program names the courses a cohort must be able to take in each semester:

```yaml
programs:
  bcom-finance:
    Fall: [BIO101, BIO205]
    Winter: [BIO305]
```

Programs are read and validated, but do not yet affect the schedule.

## Commands

Run from `solver/`:

```bash
uv run scheduler solve ../instances/my-university --check
uv run scheduler report ../instances/my-university -o instance.html
uv run scheduler solve ../instances/my-university --time-limit 600
```

Result summary fields:

- `unstaffed`: no named professor
- `unscheduled`: no meeting time
- `off_campus`: no listed room
- `feasible`: valid result, optimality not proven within the limit
