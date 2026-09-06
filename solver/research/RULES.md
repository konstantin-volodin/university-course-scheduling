# Implemented scheduling-policy inventory

This inventory describes the current implementation, not a universal university
policy, institutional approval, or an assertion that the model is complete.
Code links identify the implementation; named tests identify the evidence that
exercises it. Tests establish only their covered cases.

## Meaning of the classifications

- **Hard:** a selected assignment must obey the rule. The model can still become infeasible.
- **Fallback:** an explicit unresolved assignment is permitted, subject to other hard rules.
- **Soft:** an objective penalizes or rewards behavior; its name does not make it mandatory.

An assignment is identified by course, section, semester, and time of day. A null
professor denotes the anonymous part-timer fallback, a null timeslot denotes an
unscheduled section, and a null classroom denotes no physical room. These are
different conditions, not interchangeable evidence of a usable timetable.

## Rule inventory

| Rule | Classification and exact scope | Implementation and regression evidence | Unsupported boundary / interpretation risk |
| --- | --- | --- | --- |
| Section coverage | Hard: exactly one assignment for every declared `(course, section, semester, time_of_day)` key. Null fallback fields do not remove the section. | [`add_course_constraints`](../src/scheduler/model/builder.py#L576); [`test_every_section_gets_an_equality_row`](../tests/test_model.py#L73), [`test_missing_duplicate_and_underload`](../tests/test_audit.py#L63). | Not student enrollment, demand forecasting, or choosing how many sections to offer. A covered section can remain unscheduled. |
| Named-professor qualifications | Hard: a named professor must have a declared professor/course pair. YAML omission of `qualified_for` defaults to all courses. Preferences do not revoke eligibility. | [`_viable_assignments`](../src/scheduler/model/builder.py#L238), [qualification compilation](../src/scheduler/config/loader.py#L493); [`test_only_qualified_professors_are_assigned`](../tests/test_solve.py#L53), [`test_qualified_for_defaults_to_all`](../tests/test_config.py#L352). | No credential verification or inference that a preferred course is the only course someone can teach. Default-all requires institutional review. |
| Night permission | Hard for named professors: sections whose declared time of day is exactly `Night` require night permission, including unscheduled placeholders. | [`_viable_assignments`](../src/scheduler/model/builder.py#L238); [`test_qualification_and_night_permission`](../tests/test_audit.py#L72), [`test_night_restrictions_are_respected`](../tests/test_solve.py#L62). | Not arbitrary individual calendar availability or statutory working-time rules. `Night` is a literal category, not a universal clock threshold. |
| Teaching load | Hard minimum over all semesters combined; assigned section count equals contracted load plus nonnegative overload slack. Stage 1 minimizes total overload. Unscheduled sections count toward this modeled allocation. | [`add_professor_constraints`](../src/scheduler/model/builder.py#L374); [`test_teaching_load_rows_carry_the_right_hand_side`](../tests/test_model.py#L151), [`test_impossible_load_raises_rather_than_returning_junk`](../tests/test_solve.py#L225), [`test_missing_duplicate_and_underload`](../tests/test_audit.py#L63). | Not hours, credits, per-term maximum loads, fractional appointments, team teaching, or proof that allocated sections are actually delivered. No underload escape slack. |
| Anonymous staffing | Fallback: anonymous part-timers can cover sections without named-professor qualifications, night restrictions, personal load, or personal overlap limits. | [`_viable_assignments`](../src/scheduler/model/builder.py#L238), [`add_professor_constraints`](../src/scheduler/model/builder.py#L374); [`test_no_available_professors_falls_back_to_part_timers`](../tests/test_solve.py#L158). | This is an unresolved staffing pool, not one identified instructor who may literally teach simultaneous classes. No hiring budget or staffing supply is modeled. |
| Unscheduled sections | Fallback: a placeholder slot has no physical room and no actual resource occupancy. Penalized jointly with course-concurrency slacks in stage 2. | [`fallback_terms`](../src/scheduler/model/builder.py#L737); [`test_fallbacks_and_off_campus_permission`](../tests/test_audit.py#L94), [`test_a_blocked_degree_path_is_pushed_to_the_fallback`](../tests/test_solve.py#L386). | Hard-rule feasibility does not establish scheduling completeness. These sections have no meeting time. |
| Off-campus teaching | Fallback: a scheduled named professor may use the no-physical-room option only with off-campus permission; part-timers are exempt. Unscheduled placeholders do not need this permission and are excluded from the stage-3 off-campus objective. | [`_viable_assignments`](../src/scheduler/model/builder.py#L238), [`fallback_terms`](../src/scheduler/model/builder.py#L737); [`test_fallbacks_and_off_campus_permission`](../tests/test_audit.py#L94), [`test_no_usable_room_pushes_sections_off_campus`](../tests/test_solve.py#L239). | No off-campus room inventory, remote-delivery capability, travel time, cost, or institutional approval is inferred. The result's null-room count includes unscheduled sections, unlike the stage-3 objective. |
| Physical-room capacity and fill | Hard: attendance must be at most capacity and at least `minimum_room_fill × capacity`. The instance-wide fill fraction is configurable in `[0,1]`, general default `0`, Telfer default `0.8`. | [`_viable_assignments`](../src/scheduler/model/builder.py#L238); [`test_zero_room_fill_allows_an_underfilled_room`](../tests/test_policy.py#L51), [`test_zero_room_fill_still_rejects_over_capacity_rooms`](../tests/test_policy.py#L63), [`test_room_capacity_and_configurable_fill`](../tests/test_audit.py#L85). | Capacity does not include equipment, accessibility, room type, divisible rooms, safety certification, or variable attendance uncertainty. Fill is currently a hard policy, not a soft utilization preference. |
| Time of day and duration | Sections select from eligible pattern pools and accepted meeting formats. Positive whole-minute durations are supported; period restrictions are optional. The Telfer preset limits durations to 90/180 minutes and applies its configurable large-section night rule. | [`config/normalize.py`](../src/scheduler/config/normalize.py), [`_viable_assignments`](../src/scheduler/model/builder.py); [`test_pattern_model.py`](../tests/test_pattern_model.py). | A section shares one professor and room across its bundle. Independently staffed lecture/lab components are not represented. |
| Professor and room occupancy | Hard: within one semester, a named professor or physical room cannot serve two selected assignments at the same slot or directly overlapping slot IDs. Placeholders occupy neither; anonymous staffing and no-room resources are exempt. | [`_add_overlap_rows`](../src/scheduler/model/builder.py#L497), [`add_classroom_constraints`](../src/scheduler/model/builder.py#L565); [`test_resource_overlaps`](../tests/test_audit.py#L118), [`test_overlaps_do_not_cross_semesters`](../tests/test_audit.py#L173). | No travel buffers, setup/cleanup time, week patterns, dated exceptions, or cross-semester calendar collision handling. |
| Overlap input semantics | Weekly pattern intervals overlap on a shared day using half-open clock intervals. No overlap is inferred from a time-of-day label. | [`config/patterns.py`](../src/scheduler/config/patterns.py), [`config/normalize.py`](../src/scheduler/config/normalize.py); [`test_patterns.py`](../tests/test_patterns.py). | Repeating weeks only; dated exceptions and travel buffers are not modeled. |
| Program requirements | Hard: for a program/semester requiring at least two distinct courses, all scheduled sections of those courses compete for one place per conflict clique. Includes parallel sections of the same course and anonymous staffing. Unscheduled sections are excluded. | [`add_program_constraints`](../src/scheduler/model/builder.py#L686); [`test_program_period_rows_are_hard`](../tests/test_model.py#L211), [`test_program_conflicts_include_parallel_sections`](../tests/test_audit.py#L137). | Not student sectioning or “choose one compatible section per required course.” A one-course requirement produces no program rows. This stronger all-sections rule requires institution-specific validation. |
| Course self-concurrency | Soft: named-professor sections of the same course/semester incur excess-count slack when sharing the same exact slot ID. Anonymous staffing and placeholders are excluded. | [`add_concurrency_constraints`](../src/scheduler/model/builder.py#L624); [`test_soft_course_concurrency_does_not_fail_audit`](../tests/test_audit.py#L191). | Distinct overlapping IDs are not automatically added to the course self rule. The cited audit test establishes that soft concurrency is not a hard audit failure; it is not exhaustive objective coverage. |
| Course `apart` | Soft: specified pairs penalize simultaneous counts above one at an exact slot and cross-course direct-overlap edges. Same-course declarations do not get the cross-course edge expansion. Anonymous staffing and placeholders are excluded. | [`add_concurrency_constraints`](../src/scheduler/model/builder.py#L624); [`test_apart_detects_distinct_overlapping_meeting_ids`](../tests/test_concurrency_overlaps.py#L70), [`test_apart_does_not_confuse_overlap_with_transitive_connectivity`](../tests/test_concurrency_overlaps.py#L82), [`test_apart_keeps_the_part_timer_exemption`](../tests/test_concurrency_overlaps.py#L96). | Names such as `must_not_overlap` do not make this hard. Summed row slack is not necessarily a unique count of conflicting section pairs. |
| Course `together` | Soft: absolute difference of selected named-professor section counts for the two courses, separately at each exact slot ID. Anonymous staffing and placeholders are excluded. | [`add_concurrency_constraints`](../src/scheduler/model/builder.py#L624); [`test_together_still_requires_the_same_meeting_id`](../tests/test_concurrency_overlaps.py#L89). | Overlapping but different meeting IDs do not count as together. This matches counts, not section pairs, joint room sharing, or team-taught events. |
| Professor availability and preferences | `unavailable` excludes any bundle intersecting a forbidden interval; `time_preferences` adds soft window scores. The older `availability` preference field remains a period reward, not a hard exclusion. | [`config/normalize.py`](../src/scheduler/config/normalize.py); [`test_pattern_config.py`](../tests/test_pattern_config.py). | No dated leave or maximum consecutive teaching policy. |

## Ten-stage optimization policy

The authoritative order is [`_StagedSolve.run`](../src/scheduler/solve/solver.py#L123).
[`test_stages_preserve_priorities_and_pass_feasible_warm_starts`](../tests/test_stages.py#L75)
checks the actual objective expressions, ordering, gap requests, and handoffs.
Each minimization stage adds a rounded-up ceiling before subsequent stages.
Those ceilings preserve attained priorities, not necessarily globally optimal
priorities when a stage stops early. A solver-requested positive relative gap
also means “optimal” must not be interpreted as exact mathematical optimality.

| Stage | Objective minimized unless stated otherwise | Important grouping / boundary |
| --- | --- | --- |
| 1 | Total named-professor overload slack. | Minimum loads are already hard. Despite the display name, this is not a direct minimization of anonymous staffing. |
| 2 | Course-concurrency slack **plus** unscheduled-section count. | These two components can trade against each other within one stage. Zero unscheduled sections alone does not establish zero concurrency penalty. |
| 3 | Scheduled assignments without physical rooms. | Excludes placeholders; requests 5% relative gap. |
| 4 | Anonymous part-timer assignments in physical rooms. | Resolves room allocation in favor of named professors after the off-campus ceiling is set. |
| 5 | Semester time-of-day max–min spread **plus** weekday max–min spread. | Aggregate schedule balance, not individual-professor fairness. Weekday counts use block weights (`1.5 → 0.5`, `3.0 → 1`); empty buckets remain relevant. |
| 6 | Course block-preference violations. | An assignment whose slot shares no preferred block incurs a penalty, including placeholders when a course has a block preference. |
| 7 | Assignments of flagged courses on Friday night. | Not a general Friday ban. |
| 8 | Distinct physical rooms used per named professor/semester/day, minus one for each day with any physical room. | A room-count proxy, not a chronological transition or travel-distance count; requests 5% relative gap. |
| 9 | Professor-weighted active teaching days. | The expression charges each active day, despite the display label “additional teaching days”; it does not explicitly subtract a first free day. |
| 10 | **Maximize** course, time-of-day, and professor block rewards. | These three reward components trade additively; requests 5% relative gap. |

Balance and preference definitions are in
[`add_balance_constraints`](../src/scheduler/model/builder.py#L511),
[`add_professor_constraints`](../src/scheduler/model/builder.py#L374), and
[`preference_terms`](../src/scheduler/model/builder.py#L714).
The final exported scalar combines nine weighted preference components; it is
not a scalar representation of the entire lexicographic objective and cannot
by itself rank results with different earlier-stage violations.
[`test_preference_breakdown_reconciles_with_objective`](../tests/test_solve.py#L128)
checks that reported component arithmetic reconciles with this scalar.

## Independent audit versus solving

[`audit_result`](../src/scheduler/audit.py#L34) reads declared instance data and
exported assignments without using model rows. It checks assignment values and
identities, section coverage, qualification/permission rules, minimum loads,
room fit, time-of-day/large-section rules, resource overlaps, and the implemented
program semantics. It does **not** prove objective values, optimality, overload
minimality, soft course-concurrency satisfaction, preference quality, staffing
availability, or institutional acceptability.

`scheduler audit INSTANCE --result RESULT_JSON` separates hard findings from
unscheduled, unstaffed, and null-room counts. `--require-scheduled` adds only a
no-missing-timeslots gate. Neither a clean audit nor that gate establishes a
ready-to-publish timetable. See [CLI audit tests](../tests/test_cli_audit.py)
and [product requirements](../product/REQUIREMENTS.md).

Restricted cold-start searches and prior-result warm starts provide incumbents;
they do not redefine declared qualifications or fix the final assignments.
Their full-model validation is covered by [cold-start tests](../tests/test_cold_start.py)
and [warm-start tests](../tests/test_warm_start.py). Practical quality still
requires bounded end-to-end evaluation on the institution's actual instance.
