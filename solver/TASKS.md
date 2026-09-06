# Scheduler improvement pass

- [x] Preserve declared qualifications throughout solving; add a regression that
  distinguishes preference optimization from qualification restrictions.
- [x] Add accessible schedule issue filters and an empty-results state.
- [x] Restore regression coverage for stage priorities, caps, and repaired warm starts.
- [x] Add GitHub Actions checks for supported Python versions, locked dependencies,
  instance validation, and a bounded solve with downloadable reports.
- [x] Penalize overlapping meeting times for courses explicitly required to run apart.
- [x] Make institutional minimum room fill configurable with a compatible default.
- [x] Establish research positioning and measurable product requirements.
- [x] Add a reproducible experiment runner with input snapshots and failure records.
- [x] Reconcile identified manuscript equation mismatches and rebuild the PDF.
- [x] Independently audit exported schedules against hard input constraints.
- [x] Remove confirmed dead code, including obsolete objective helper APIs.
- [x] Run integrated checks and inspect the generated report in a browser.
- [ ] Add validated prior-schedule warm starts and investigate Telfer performance.
- [x] Commit the verified foundation in a git-spice stack and document Telfer limitations.

Scope: improve correctness and observability without inventing new university
policies. Full Telfer optimization remains a manual validation run. Preserving all
declared qualifications may increase its model size and runtime.

Verification so far: 216 tests passed `make check` on Python 3.13 and 3.14,
including room policy, independent audit, experiment runner and cleanup. A regenerated Telfer report
was inspected in Chromium; the eight-page manuscript PDF was rebuilt with TeX Live.
Two tiny and two medium experiment runs passed the independent hard-rule audit.
Telfer expanded about 18x after removing unsafe qualification pruning; see
[the performance investigation](research/PERFORMANCE.md). Its runtime is unresolved.
The GitHub Actions workflow is configured locally; no hosted run is claimed.
