# Instances

| Path | Format | Size |
|---|---|---|
| `template/` | commented starter | 1 section |
| `faculty/` | editable generated/custom bundles | 6 sections |
| `tiny/` | one file | 3 sections |
| `medium/` | split files | 36 sections |
| `telfer/` | split files | 426 sections |

## Setup

```bash
cd solver
uv python install 3.14
uv sync --python 3.14 --extra dev
cd ..
cp -R instances/template instances/my-university
# Or: cp -R instances/medium instances/my-university
```

## Split format

```text
my-university/
├── instance.yaml
├── meeting-patterns.yaml
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
  meeting_patterns: meeting-patterns.yaml
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

## Meeting patterns

The solver chooses a complete weekly bundle for each section, together with one
professor and one room shared by every meeting. Bundles repeat throughout their
semester. Teaching-week calendars and separately staffed lecture/lab components
are future extensions; there is no week field to maintain today.

A pool can generate bundles, supply custom bundles, or combine both:

```yaml
meeting_patterns:
  standard:
    generate:
      formats:
        - meetings: 2
          minutes_each: 75
          day_combinations:
            - [Mon, Thu]
            - [Tue, Fri]
      start_times: ["09:00", "10:30", "13:00"]
      finish_by: "17:00"
      same_start: false
    custom:
      special:
        - {day: Mon, start: "08:30", minutes: 75}
        - {day: Thu, start: "10:00", minutes: 75}
```

Each format explicitly states its meeting count and duration. Three 50-minute
meetings use `meetings: 3`, `minutes_each: 50`, and a three-day combination.
A single meeting may use `days: [Mon, Tue, Wed]` instead of `day_combinations`.
Durations are positive whole minutes. Quote all clock times and use weekday
names `Mon`, `Tue`, `Wed`, `Thu`, `Fri`, `Sat`, `Sun`.

`same_start` defaults to `false`: the generator considers independently chosen
starts on each day. Set it to `true` to require matching starts. `finish_by`
limits the end of each generated meeting. Start times may instead be a window:

```yaml
start_times:
  start: "08:30"
  end: "11:30"  # Last permitted start, included if aligned with the increment.
  every_minutes: 30
```

Generation enumerates permitted choices; optimization selects among them.
Equivalent bundles are deduplicated, and custom IDs take precedence over generated
IDs. Pool `time_of_day` defaults to `Day`; set it explicitly for categories such
as `Morning` or `Night`. Custom bundles may use different starts on different days.
Touching endpoints do not overlap. Wider windows and more day combinations create
more candidates; start with your faculty's actual permitted teaching periods.

See [template/instance.yaml](template/instance.yaml) for a commented starter and
[faculty/instance.yaml](faculty/instance.yaml) for six courses with both custom and
generated bundles. No YAML anchors are needed.

## Classrooms

```yaml
SCI-201: 80
LIB-100: 160
```

Rooms must fit the section. The `general` preset (the default) imposes no minimum
occupancy. Institution policy is explicit:

```yaml
preset: telfer
policy:
  minimum_room_fill: 0.8
  allowed_durations: [90, 180]
  large_section_threshold: 75
  long_meeting_minutes: 180
  night_period: Night
```

These are the Telfer defaults: long meetings above the threshold require the night
period. General policy allows arbitrary positive durations and has no large-section
night rule. Override individual fields, for example `minimum_room_fill: 0` or
`large_section_threshold: null`. Capacity remains a hard upper bound. Telfer also
defaults to penalizing Friday-night teaching; general policy permits night teaching
unless a professor opts out.

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
- `can_teach_night` (default `true` for general, `false` for Telfer)
- `can_teach_off_campus` (default `false`)
- `prefers_packed_days` (default `false`)
- `preferred_class_length`: `single` or `double`
- `availability`: preference scores
- `course_ranks`: preference scores

Preference scores: `0` or omitted = none; higher values = stronger. `part-timer`
is reserved.

Hard unavailability and soft clock-based preferences are separate:

```yaml
unavailable:
  - {semester: Fall, days: [Tue], start: "13:00", end: "17:00"}
time_preferences:
  - {days: [Mon, Thu], start: "08:00", end: "10:00", score: -2}
  - {days: [Wed], start: "10:00", end: "12:00", score: 3}
```

A window applies to any bundle with an intersecting meeting; touching endpoints
are legal. Omit `semester` to apply it to every term. Positive time preference
scores favor a bundle, negative scores discourage it, and matching windows add.
Each window contributes once per bundle even if several meetings intersect it.
`teaching_load` counts sections, while daily teaching load uses minutes.

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

## Courses and inherited defaults

```yaml
course_defaults:
  semester: Fall
  meeting_patterns: [standard]
  formats:
    - {meetings: 2, minutes_each: 75}
courses:
  BIO101:
    sections:
      - id: BIO101-1
        students: 72
      - id: BIO101-2
        students: 30
        meeting_patterns: [evening]
        formats:
          - {meetings: 1, minutes_each: 150}
```

Define every referenced pool, including `evening` in this illustration.
`meeting_patterns`, `formats`, `semester`, and `time_of_day` inherit from
`course_defaults` to course to section; the closest value replaces the inherited
value. Pool lists select eligible bundles; `formats` further restricts them to
acceptable teaching structures. These are hard requirements. Empty candidate
sets produce a validation error.

Without a pool selection all pools are eligible. Without `formats` all structures
in the selected pools are accepted. `time_of_day` defaults to `Any`, allowing
choices across categories; an explicit category restricts the choices. Semester
may be omitted only when the instance has one semester or a default supplies it.
Section IDs must be unique. Courses in different semesters can reuse rooms and
times without conflicts.

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

Students in a program should be able to take one scheduled section of every
required course without two of them overlapping. Extra sections of a course may
share a time; only the sections the students would pick must fit together. This
is a soft goal: each required course the students cannot fit in counts one point
in the "Let each program's students take every required course" stage, and the
schedule report names each one.

## Complete or partial schedules

Default mode returns the best available schedule and identifies unscheduled,
unstaffed, or off-campus sections. Hard conflicts remain forbidden.
Set top-level `strict: true` (or CLI `--strict`) to require every section to have
a complete bundle, named professor, and listed room. An impossible strict instance
is reported as infeasible.

## Commands

Run from `solver/`:

```bash
uv run scheduler solve ../instances/my-university --check --time-limit 30
uv run scheduler report ../instances/my-university -o instance.html
uv run scheduler solve ../instances/my-university --time-limit 60
```

Result summary fields:

- `unstaffed`: no named professor
- `unscheduled`: no meeting time
- `off_campus`: no listed room
- `feasible`: valid result, optimality not proven within the limit
