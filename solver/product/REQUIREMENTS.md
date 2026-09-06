# University scheduling product requirements

This is a proposed delivery backlog grounded in the current repository, not a claim of
commercial readiness. The first product increment should let a scheduler edit a local instance,
validate it, run a bounded solve, and review unresolved assignments with reproducible evidence.
Hosted collaboration comes after that workflow has been validated with users.

## Evidence and current boundaries

| Area | Local evidence | Product implication |
|---|---|---|
| Input and validation | [`config/loader.py`](../src/scheduler/config/loader.py) loads single/split YAML, validates references and unknown fields; [`config/instance.py`](../src/scheduler/config/instance.py) builds the internal instance. | Reuse validation for editing and import; avoid a second interpretation of the schema. |
| User workflow | [`cli.py`](../src/scheduler/cli.py) exposes `solve`, `solve --check`, and `report`. | A local interface can wrap existing operations; there is no application service contract demonstrated here. |
| Institution assumptions | [`instances/README.md`](../../instances/README.md) documents 90/180-minute meetings, 80% room occupancy, `Fri`/`Night` semantics and default flags. [`model/builder.py`](../src/scheduler/model/builder.py) contains corresponding modeling choices. | These assumptions require explicit policy configuration before claiming suitability for another institution. |
| Optimization priorities | [`solve/solver.py`](../src/scheduler/solve/solver.py) orchestrates ten stages; [`README.md`](../README.md) explains per-stage budgets and priorities. | Explain priorities to users and record them with each run; a feasible result is not proof of every stage's optimum. |
| Review | [`report/renderer.py`](../src/scheduler/report/renderer.py) emits standalone HTML and objective Markdown; [`solve/result.py`](../src/scheduler/solve/result.py) represents missing professor/time/room as null. | There is an offline review foundation, but a missing assignment is not a diagnosis of why it is missing. |
| Packaging | [`pyproject.toml`](../pyproject.toml) packages a Python CLI with HiGHS and optional Gurobi. | Local deployment is the shortest path. Hosted operations and solver licensing requirements need separate verification. |

Priorities below describe sequence: P0 is the next local product increment, P1 enables broader
institution trials, and P2 enables managed collaboration. They are not time estimates.

## P0: editable, reproducible local workflow

| ID | Requirement | Acceptance evidence |
|---|---|---|
| EDIT-1 | Provide editable professors, courses/sections, rooms, meeting times and program requirements. Show field errors before solving, preserve stable IDs and require deliberate confirmation of referenced-record deletion. | A user can create an instance from a template, edit it, save/reopen it, and solve it. Invalid references identify the affected record and field. Saving an invalid draft cannot silently replace a validated instance. |
| EDIT-2 | Keep drafts distinct from validated snapshots and solved schedules. Display unsaved changes and use an explicit save operation. | Editing input after a solve marks the displayed result as belonging to the earlier snapshot. Reopening a saved draft preserves values, including false flags and zero preference scores. |
| RUN-1 | Expose validation, solver choice, progress, stage status and bounded execution. Clearly distinguish per-stage limits from a total run deadline. | Time-limit behavior agrees with the displayed estimate; failures preserve the input and any separately identified valid completed result. Cancellation is tested before it is advertised. |
| RUN-2 | Store every run in its own directory with input snapshot/digest, application and backend versions, policy version, limits, status and output files. | Running the same instance twice preserves both runs. A reviewer can identify exactly which input and policy produced a report. Failed runs cannot leave a mixture of previous and new artifacts presented as one result. |
| REVIEW-1 | Support filtering unstaffed, unscheduled and off-campus sections, including selecting sections that have no grid position. Keep result status and unresolved counts visible. | Counts reconcile with result JSON; combined filters have a clear empty state; null meeting times display as unassigned rather than a fabricated slot. Existing report work provides a starting point. |
| POLICY-1 | Inventory each implemented rule as hard feasibility, permitted fallback, or penalized preference. Show its scope and active priority. | A reviewed policy table links each rule to model code and a focused test. UI copy never promises that a penalized condition is prohibited. Current behavior is preserved until a policy change is explicitly selected. |

Keep the first editor local and single-user. A generic editable JSON text box may be useful for
developers but does not satisfy EDIT-1 for scheduling staff. Existing YAML remains an interoperable
format; any new editor must use the same validation and retain a documented export path.

## P1: generalize policy and explain results

| ID | Requirement | Acceptance evidence |
|---|---|---|
| POLICY-2 | Introduce versioned institution presets with explicit settings for room utilization, supported meeting durations, named day/period rules, fallback permissions and optimization priorities. Separate institution settings from presentation branding. | Two synthetic institutions with materially different policies validate and solve without source changes. The existing institution's preset reproduces its documented policy. Reports name the effective preset and overrides. |
| POLICY-3 | Define how hard unavailability differs from preference scores and qualifications; make that distinction visible in editing. | A negative test proves an unavailable professor is never assigned in that interval; a separate preference test proves a less-preferred legal assignment remains possible. Unsupported forms are rejected instead of approximated silently. |
| EXPLAIN-1 | Add pre-solve diagnostics for demonstrable local exclusions: no qualified professor, no capacity-compatible room, or no compatible real meeting slot. | Diagnostics name the section and applied rule, match candidate generation, and separate zero-candidate facts from unresolved outcomes caused by global competition. |
| EXPLAIN-2 | Explain an unresolved result using evidence, with a distinction between a known exclusion, a competing allocation, and an unproven search outcome. | The UI does not claim impossibility from a time-limited run. Any proposed “relax this rule” explanation is backed by a separately labeled diagnostic solve with its own limit and changed policy recorded. |
| CHANGE-1 | Support scenario copies and result comparisons before adding manual assignment editing. Compare unresolved counts, stage values and changed sections. | A user can compare two immutable runs even after the source draft changes. Objective comparisons warn when policies or input scope differ. |
| CHANGE-2 | Later support locking selected assignments and requesting minimal disruption to a baseline. | A locked assignment is enforced or produces a clear conflict; it is never silently dropped. Disruption scoring is declared as a policy priority and tested against higher-priority requirements. |
| IO-1 | Publish versioned CSV import templates and a mapping/preview step for institution spreadsheets. Import into a draft, normalize types explicitly, and validate the complete draft before solving. | Fixtures cover duplicate IDs, invalid references, missing values and quoted cells. Import errors include source row/column. No partial import overwrites a validated snapshot. |
| IO-2 | Export documented schedule CSV and existing JSON/HTML, preserving stable IDs and explicit unresolved fields. | Exported rows reconcile with assignments; spreadsheet-oriented exports handle formula-like cell contents safely. Export includes policy/run identity and documents which fields can be round-tripped. |

Do not turn every model constant into an unrestricted user input at once. Start with named,
validated settings backed by examples and tests. The current two-duration formulation is a
specific generalization project; merely allowing another duration in YAML is insufficient.

## P2: privacy, collaboration and deployment

| ID | Requirement | Acceptance evidence |
|---|---|---|
| PRIV-1 | Define which professor, preference and enrollment fields are collected, who can view them, and which exports disclose them. Provide a redacted sharing mode where justified. | A sample shared report is reviewed for disclosure; redaction covers embedded JSON and downloadable data, not just visible HTML. Local storage locations and retention are documented. |
| TEAM-1 | Before shared hosting, add institution isolation and explicit viewer/editor/approver roles. | Tests exercise cross-institution object access and export access, including guessed IDs. A viewer cannot mutate an instance or initiate an unauthorized run. |
| TEAM-2 | Use revision checks for concurrent edits and record actor, timestamp, affected revision and action. Add an explicit approval/publish step for schedules. | Two editors cannot silently overwrite one another. A published schedule refers to an immutable run and approved revision; a subsequent draft remains separate. |
| OPS-1 | Establish a local distribution path first, then decide between institution-managed and hosted deployment using pilot requirements. | Clean-environment installation and a small bounded solve succeed from released artifacts; supported Python/OS/backend combinations are documented from tests. |
| OPS-2 | For hosting, isolate solve jobs with resource limits, cancellation, queueing, artifact ownership and cleanup. Keep the solver independent of HTTP requests. | A failed or cancelled job cannot corrupt another job; restart behavior is tested; disk and runtime quotas are enforced. Backend license constraints are verified for the intended operating model. |
| OPS-3 | Define backups, restoration, retention/deletion and operational logging for the chosen deployment. | A restore exercise recovers revisions and run provenance. Logs exclude unnecessary private input. Access, deletion and failure handling are demonstrated before accepting production data. |

## Decisions and evidence still needed

- Observe scheduling staff editing a realistic instance: preferred terminology, bulk editing needs,
  tolerated solve time and the information needed to trust a fallback remain unvalidated.
- Collect an independently reviewed policy inventory from a second institution. The current
  examples do not establish support for arbitrary duration, room equipment, multiple campuses,
  travel time, team teaching, alternating weeks or cross-listed sections.
- Decide whether “off campus” means an approved alternative delivery location or simply the
  absence of an assigned room. Current null output does not establish that operational meaning.
- Confirm which rules may be relaxed and who may approve changes. A configurable priority order
  alone does not establish institutional authority or acceptable schedules.
- Benchmark model construction, memory and solve outcomes on representative additional instances;
  package version, unit tests and one institution's result are not scale or readiness evidence.
- Validate required import/export formats with actual downstream systems before promising integrations.
- Establish deployment, access and retention requirements with intended institutions before selecting
  a hosting model or making privacy/compliance claims.

The next reviewable milestone is EDIT-1/2, RUN-1/2, REVIEW-1 and POLICY-1 with a synthetic sample,
documented manual acceptance walkthrough, passing repository checks, and an institution reviewer
who can trace the displayed schedule back to its input and policy.
