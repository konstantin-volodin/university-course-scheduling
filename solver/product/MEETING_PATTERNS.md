# Meeting patterns: design and future calendar goal

Status: agreed design implemented. See `instances/template` and `instances/faculty`.

## Confirmed direction

- Aim for a general scheduling model, with Telfer restrictions expressed as additional
  institutional policy: duration choices, room fill, and large-section night rules.
- A section selects an indivisible bundle of recurring meetings.
- Explicit custom bundles and generated candidate bundles may coexist. The solver
  optimizes the selection jointly with professor and room assignments.
- Include generation from exact start lists or a time window and increment, with
  explicitly allowed day combinations. Missing bundles and generation settings are errors.
- Courses declare acceptable meeting structures, with defaults and section overrides.
  Support positive whole-minute durations, including 3 x 50 and 2 x 75, and measure
  daily teaching load in minutes. Total contact minutes alone are insufficient.
- Each section's bundle uses one professor and one room. Separately staffed lecture/lab
  components are a future extension.
- Meetings repeat weekly within the assigned semester for the current implementation.
- YAML may change, but must remain easy to edit by hand. Reduce repetition without
  requiring users to understand advanced YAML features.
- The initial user is a professor coordinating a faculty schedule. Deliver a concise
  YAML template, realistic faculty example, and precise validation errors. Spreadsheet
  import and submission forms are deferred.
- Distinguish hard professor unavailability from soft time preferences.
- Return clearly identified partial schedules by default; offer a strict mode requiring
  all sections to have a named professor, listed room, and real bundle. Hard conflicts
  remain forbidden in both modes.
- Remove the legacy /OPTIM_data/ input contract and migrate repository examples.

## Future goal: custom teaching weeks

Support meeting patterns active during selected weeks of a semester, including
alternating-week and partial-semester teaching. Weekly repetition should remain the
simple default for users who do not need calendar exceptions.

Before implementing this extension, define the semester calendar and how users name
or select teaching weeks; whether week selection belongs to each meeting or the
whole bundle; and how weekly activity affects conflicts, contact hours, teaching load,
preferences, and reports. Conflicts must require a shared active week as well as
overlapping day/time intervals. Cover disjoint and intersecting week sets in tests.

This is a future capability, not a requirement to add a weeks field now.

## Implementation decisions

- `meeting_patterns` contains named pools with `custom` and/or `generate` choices.
  Formats use explicit `meetings`, `minutes_each`, and `day_combinations` fields.
- Different starts per day are allowed by default; `same_start: true` restricts generation.
- Canonical patterns retain actual clock intervals through validation, solving, and reports.
  Equivalent candidates are deduplicated deterministically; candidate counts are reported.
- The solver selects whole patterns jointly with staff and rooms. No individual meeting
  decision variables or weekly expansion are needed for the current calendar.
- Professor teaching obligations count sections. Daily balance derives from actual minutes,
  normalized by 180 to preserve the existing objective scale. Fractional stage optima are
  preserved rather than rounded up; auxiliary bounds cover long meetings.
- The general preset imposes room capacity, with no minimum fill or large-section night rule.
  Telfer adds its 90/180-minute durations, 80% fill, and night restriction for long meetings
  exceeding 75 students. Named policy overrides are validated.
- Hard unavailability excludes any intersecting pattern in the specified semester(s).
  Soft time-window scores accumulate once per matching window and bundle.
- The CLI accepts the editable YAML schema; the legacy endpoint contract is removed.
  Internal normalized model rows remain private implementation data. Only the maintained `meeting_patterns` schema is accepted.
- Reports show the selected pattern's actual period and per-day clock times, including
  sections eligible across periods. CSV import and form collection remain future work.

## Validation

Focused tests cover generation, deterministic deduplication, custom bundles, arbitrary
meeting durations, defaults and overrides, exact overlaps, availability, strict infeasibility,
policy presets, reports, and warm restarts. Run `make check` from `solver/` for Ruff,
strict mypy, and the full pytest suite. The faculty example has six sections and 22
candidate bundles; a bounded strict solve produces a complete legal schedule.
