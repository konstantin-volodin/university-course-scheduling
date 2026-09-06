# From institutional solver to research and product

The objective is a publishable academic study and a university scheduling product
with explicit, generalizable semantics. Neither publication readiness nor suitability
for arbitrary universities has been established. Passing implementation tests is one
kind of evidence; it cannot substitute for independent institutional validation.

## Acceptance gates

| Outcome | Evidence required | Current gap |
| --- | --- | --- |
| Publishable paper | Reviewed problem definition, justified contribution against related work, correct formulation, controlled experiments, limitations, reproducible tables and artifacts | Existing manuscript is a formulation draft; novelty and effectiveness are unproven |
| Sellable product | Complete scheduling workflow, reliable saved runs, usable editing and validation, documented deployment/support, institutional pilot acceptance | Current application is a CLI and static reports; editing, operational controls and pilot evidence are missing |
| Generalizable model | Explicit supported rule vocabulary, institution-specific policy settings, independent schedule validation, multiple materially different institutional cases | Current formulation embeds assumptions about durations, workload, periods and fallbacks |

“Perfect” is treated as a demand for explicit semantics, testable invariants, and
honest coverage boundaries. A university with unsupported rules must receive a clear
unsupported result, not a silently approximated schedule.

## Delivery sequence

1. **Trustworthy core.** Preserve input qualifications, enforce real time overlaps,
   verify stage handoffs, expose unresolved assignments, and run checks automatically.
   Completed changes and their verification live in [TASKS.md](TASKS.md).
2. **Reproducible evidence.** Capture immutable input digests, versions, parameters,
   full results, failures and wall time for experiments. Add an independent schedule
   checker before using solver output as evidence of legality. Record stage bounds
   and termination details before making exact-optimality claims.
3. **Explicit policy.** Inventory every rule, its mathematical meaning, scope and
   hardness. Generalize validated settings incrementally, starting with room fill.
   Keep preferences distinct from hard unavailability and qualifications. Use
   contrasting synthetic institutional examples to test each new setting.
4. **Usable local workflow.** Deliver editable inputs, field-level validation,
   immutable runs, scenario comparison and documented exports. Demonstrate the
   complete workflow to scheduling staff before expanding to hosted collaboration.
5. **Comparative study.** Freeze an experiment protocol and run matched-budget
   baselines/ablations. Do not compare transformed benchmark scores to official
   leaderboards unless an exact adapter passes the official evaluator.
6. **Paper and pilot.** Reconcile equations with implementation, generate all tables
   from archived runs, document limitations and obtain domain review. Validate a
   second institution's rules and workload before broad product claims.

## Research decisions

The candidate contribution is an evaluated institutional decision-support approach
combining faculty allocation and explicit priorities for operational compromises.
Integration and staged MIP alone are not new. See
[related work and evaluation plan](research/RELATED_WORK.md) for precedents and
benchmark mismatches. Baseline comparisons must use the same feasible set and policy;
changing qualifications or priorities is a separate sensitivity experiment.

A time-limited stage can return a good incumbent without proving that its compromise
is unavoidable. Reports and the paper must distinguish those cases. Per-stage limits
are not total-runtime limits, and model construction is part of computation cost.

## Product decisions

Start with a local, single-user product and interoperable YAML/JSON. Do not introduce
hosted accounts or institution data transfers without a concrete operating model.
See [product requirements](product/REQUIREMENTS.md) for prioritized acceptance criteria.
Branding, calendar conventions and institutional policy must eventually be separate.

## External evidence still needed

- An administrator-approved rule inventory and a reference schedule for comparable
  offerings, including which compromises are permitted.
- Permission and provenance for any real data included in research artifacts.
- Requirements and representative data from at least one additional institution;
  variants of the Telfer instance do not establish cross-institution validity.
- Independent reproduction and domain review of the study's findings.
- Pilot feedback on editing, explanations, export compatibility and acceptable runtime.

These are future evidence gates, not reasons to stop implementing and testing the
general infrastructure that can be built now.
