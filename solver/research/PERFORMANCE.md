# Telfer performance regression investigation

Observed on 2026-09-04 during the foundational improvement pass. These are diagnostic
observations, not controlled comparative runtime results.

## Confirmed model growth

Using the current Telfer input and the historical narrowing routine from commit
`ea4bacc` (with its auxiliary solve bounded at five seconds), candidate counting gave:

| Formulation input | Professor/course pairs | Assignment candidates |
| --- | ---: | ---: |
| Historical preference-narrowed qualifications | 372 | 42,179 |
| All declared qualifications | 17,056 | 756,840 |

The count applied the current candidate eligibility conditions without allocating
the candidate matrix. The current count exactly matches the observed solve log.
Removing unsafe qualification pruning increased assignment candidates about 18x.

The observed full model had 780,642 variables, 40,095 rows and 12,193,357 nonzeros.
Model enumeration took 2.57 seconds; subsequent solve stages dominated elapsed time.
The timetable stage stopped early at combined conflict/unscheduled penalty 426.
Later stages took substantially longer than this small-instance validation pass.
The log does not establish exactly which internal solver operations dominate.

Restoring pruning as an invisible optimization would change the feasible set again.
The qualification regression demonstrates that such pruning can exclude the only
fully scheduled legal timetable even when faculty loads can be filled.

## Useful existing incumbent

The archived `instances/telfer.zip` contains a 426-assignment schedule with zero
unscheduled sections. On the current input it passes the new independent hard-rule
audit. That audit does not certify soft penalties or optimality. The current CLI
does not yet support importing this schedule as a warm start.

## Next implementation and experiments

1. Accept a validated previous schedule as an optional incumbent, reconstructing
   model auxiliaries and checking feasibility before offering it to the solver.
   Keep all declared qualifications in the optimization model.
2. Compare placeholder and validated-schedule initialization under the same rules,
   solver/version, hardware and budgets. Record early feasible schedules and stage
   vectors, not just final reward. Run measurements separately from the test suite.
3. Profile model loading, incumbent repair, presolve and branch-and-bound separately.
   Per-stage backend limits are not a guaranteed process-level deadline.
4. If needed, evaluate a small restricted model solely as a heuristic source of a
   feasible incumbent; the final model must retain the full legal choice set.
5. Evaluate formulation factorization/decomposition only against the independent
   checker and matched-policy baselines.

## Integration evidence

Two tiny and two medium runs with ten-second per-stage limits completed successfully
and passed independent hard-rule audits. Both medium runs scheduled all 36 sections
with no staffing, timeslot or room fallback. Their artifact is
`instances/results/research/2026-09-04-foundation.json`, including canonical inputs,
versions, Git revision/dirty state and complete results. They ran concurrently with
checks and therefore must not be used as controlled speed comparisons.
