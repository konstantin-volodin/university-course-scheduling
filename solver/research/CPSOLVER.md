# CPSolver reuse experiment — 2026-09-05

**Decision: retain the existing HiGHS semester neighborhood.** This CPSolver
adapter matched its room-placement quality and took substantially longer. The
unused adapter, Java setup, and experiment-specific tests were subsequently
removed during code cleanup. This note and the measured evidence remain as a
historical record; the experiment is no longer an executable project command.

## Measured comparison

Both methods received the same validated input schedule, legal professor ownership,
core institutional constraints, two earlier objective caps, and a 30-second
per-run process deadline. They restarted from the same seed for every repetition.
Runs were sequential; method order alternated. No broad test suite ran during the
measurements. One short Java compilation overlapped the later comparison, so the
timings are development-machine observations, not publication-grade isolation.

| Initial off-campus sections | Method | Final off-campus, three runs | Median wall seconds |
| ---: | --- | --- | ---: |
| 233 | CPSolver IFS adapter | 175, 175, 175 | 26.77 |
| 233 | Existing HiGHS neighborhood | 175, 175, 175 | 4.15 |
| 175 | CPSolver IFS adapter | 175, 175, 175 | 26.74 |
| 175 | Existing HiGHS neighborhood | 175, 175, 175 | 2.73 |

All twelve Telfer candidates passed a separate post-experiment hard-rule audit.
All 426 sections retained timeslots; 145 sections remained unstaffed. Faculty
ownership was fixed, so this experiment could not improve staffing. Teaching-load
and timetable penalties stayed zero. Neither method demonstrated a full-model
optimum or improved the final 175-room-fallback result.

A three-section Java smoke test with a known room recovery improved off-campus
use from 1 to 0, including a legal timeslot move. CPSolver finished in 3.38 seconds
within an eight-second allowance; HiGHS also reached 0. This checks that the
adapter can produce an improvement rather than merely return its seed.

## What was reused

Pinned **CPSolver 1.4.94** runs its own `SimpleSearch`, hill climbing, simulated
annealing, and move/swap/suggestion neighborhoods. Our small Java bridge defines
placement domains and capacity constraints; Python exports and validates them.
This is the generic IFS library, **not the specialized UniTime `coursett` solver**,
student sectioning, an ITC 2019 implementation, or a reproduction of the paper's
experiments. The negative result does not rule out a better specialized adapter
or different search configuration.

CPSolver fixes non-assignment auxiliaries to their seed values. HiGHS may optimize
auxiliaries and searches each semester separately. Thus this evaluates the two
implemented methods, not the engines on an identical mathematical formulation.
In these zero-conflict inputs the earlier caps keep core violation slacks at zero.
The search covers stage 3 only: importing a final schedule does not preserve its
later stage-4-through-10 caps.

## Deadline and acceptance behavior

One common Python model is constructed and the input seed is validated before
the runs. That preparation is measured separately. Per-run wall time includes
worker startup, projection/export, JVM startup, search, candidate checking, and
result writing. CPSolver export took about 1.3–1.4 seconds on the improved seed.
Its internal search reserves time for validation; unused budget is not padded.

The parent owns the last validated schedule. Each worker and all its descendants
occupy a separate POSIX process group. The parent kills that group at the deadline
if needed and retains the seed when candidate validation has not completed.
Regression tests exercise an uncooperative worker and missing Java. Native
cooperation is not required, although OS scheduling/reaping can add small latency.
This containment was implemented only in the retired experiment; production MIP stages still
have cooperative time limits and their previous overruns are unresolved.

## Archived evidence

At the time of the experiment, `make check` passed: Ruff, strict mypy (28 source
files), and **311 tests**.
The hash-pinned setup script successfully rebuilt the adapter from cached jars.
The exported best Telfer result also passed `scheduler audit --require-scheduled`.

- [Readable measurement summary](CPSOLVER_30S.json): individual durations, objectives,
  audit results, and evidence hashes.
- [Complete compressed run records](CPSOLVER_RUNS.json.gz): canonical inputs, seeds,
  every accepted assignment, source/classpath hashes, and runtime metadata. The
  first improved-seed run predates hash telemetry; this limitation is recorded.

The runtime used Eclipse Temurin OpenJDK 21.0.12.1+1. Its downloaded archive SHA-256
was `ce79869e1307ed8ee1e2baa86a412b1eb5b75d10a01006d788a6f968bcfaee94`, verified
against Adoptium's package metadata before extraction. Java and jars were isolated
under `/tmp`; no system installation or Python dependency change was needed.

To read the full archive:

```python
import gzip, json
with gzip.open("research/CPSOLVER_RUNS.json.gz", "rt") as stream:
    records = json.load(stream)
```
