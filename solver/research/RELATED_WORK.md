# Related work and a defensible evaluation plan

Research snapshot: 2026-09-04. This is a bounded primary-source review, not a systematic
review or an established novelty claim. Sources were checked through official competition
specifications, author/institutional repositories, publisher abstracts, and ACM guidance.
Paper-level observations below use the accessible abstracts or specified benchmark definitions;
they do not imply that every full paper has been critically reviewed.

The current manuscript describes an integrated assignment of faculty, section meeting times,
and rooms, with institutional workload requirements and hierarchical compromises. The likely
research direction is a carefully evaluated institutional decision-support model. Neither
integrating these decisions nor using a MIP establishes novelty: both have precedents.

## What the closest sources establish

| Source | Established precedent | Consequence for this project |
| --- | --- | --- |
| Di Gaspero, McCollum, Schaerf (2007), ITC 2007 Track 3 [1] | Curriculum-based weekly lecture scheduling with an official model and evaluator. | Useful reference problem, but the current model is not an equivalent implementation. |
| Müller, Rudová, Müllerová (2018; journal treatment 2025), ITC 2019 [2] | Rich class time/room assignment combined with student sectioning and distribution constraints. | A broader benchmark does not automatically fit faculty allocation; student sectioning would require substantial new functionality. |
| Gunawan, Ng, Poh (2007) [3] | Simultaneous teacher assignment and course scheduling, with mathematical programming and hybrid search. | Do not claim first integration of teacher assignment and timetabling. |
| Domenech and Lusa (2016) [4] | MILP teacher assignment prioritizing teaching-load balance and teacher preferences, evaluated on a departmental case and generated instances. | Workload/preferences need comparison to existing assignment models, not just timetabling benchmarks. |
| Burke, Mareček, Parkes, Rudová (2010) [5] | Multiphase, objective-restricted timetabling MIP submodels, with quality bounds. | Staging/decomposition has prior art; test the specific deferred-row and incumbent-repair mechanisms. |
| Johannesson et al. (2026 preprint) [6] | Teaching-assignment formulation and SMT/CP/MILP evaluation on a Chalmers dataset, including load deviation and course switches. | Relevant recent comparison for workload and assignment stability; peer-reviewed status is not established here. |
| ACM artifact policy [7] | Separate recognition of artifact availability, evaluation, and independently validated results. | A public repository and passing tests are useful, but do not establish independent reproduction. |

The 2007 hybrid paper uses generated cases based on an Indonesian institution; its abstract
does not establish equivalent constraints or benchmark interchangeability with Telfer. [3]
The 2016 assignment paper does not, on the evidence inspected, establish a joint room/time
allocation benchmark for the present model. [4] These are relevant antecedents rather than
ready-to-run baselines.

## Benchmark compatibility must be demonstrated

ITC 2007 curriculum-based timetabling assigns each lecture a period and room, with the course's
teacher already given. Curriculum and teacher conflicts are hard constraints. Its four soft
criteria are room-capacity overflow, minimum working days, curriculum compactness, and course
room stability. [1]

The present scheduler chooses professors, uses meeting patterns rather than only elementary
periods, admits explicit unscheduled/off-campus outcomes, and applies institutional room
eligibility and workload rules. Its room-change cost concerns professor/day room usage, which
is different from keeping all lectures of one course in one room. Consequently, renaming a
`.ctt` file into YAML would not make a fair ITC 2007 experiment. This comparison is an inference
from the official definition and the current implementation.

An exact ITC 2007 adapter would need fixed teacher assignments, all required lecture counts,
the precise hard constraints, the four specified penalties and weights, and output accepted
by the official validator. The official evaluation weights are 1 per excess student, 5 per
missing working day, 2 per isolated curriculum lecture, and 1 per additional course room.
The competition provides validator source; use it as an external scoring oracle. [1]
If only a subset is translated, label it as a derived benchmark and enumerate each change;
do not compare its score to published ITC scores.

ITC 2019 includes course/class hierarchies, week/day meeting patterns, allowed placements,
distribution constraints, and assignment of students to requested classes. Its official
objective combines time, room, distribution, and student-conflict penalties. Feasible
solutions are required. The original competition did not bound computation time or number
of processors, so leaderboard results are not a controlled runtime baseline. [2]

The current program-requirement groups are not individual student sectioning. An ITC 2019
claim would require implementing and validating the missing semantics, not replacing student
requests with pairwise course conflicts. For this project, a transparent institutional study
is the nearer-term experiment; an exact competition implementation is a separate workstream.

## Candidate contribution and limits

A testable candidate is: **an openly reproducible institutional scheduling model that combines
faculty allocation with an explicit hierarchy of operational compromises, together with an
evaluation of how that hierarchy and its computational implementation affect usable schedules.**
This is a research hypothesis and framing proposal, not an assertion of originality.

The literature already supports integrated allocation [3], workload/preferences [4, 6], and
multiphase mathematical programming [5]. The remaining question is whether the particular
institutional rules, validated data, explanatory outputs, or computational mechanisms provide
a significant contribution beyond those precedents. A broader full-text and citation search
is needed before a manuscript can claim a research gap.

Institutional priorities also need a rationale from scheduling stakeholders. A sequence of ten
objectives is a policy choice, not evidence of fairness. Balance of assignments across weekdays
does not by itself measure equity among professors. Qualification narrowing changes the feasible
set and must be explicitly disclosed and assessed, rather than presented as a universally safe
presolve reduction.

For interrupted stages, distinguish the best incumbent from a proved optimum. A later objective
cap can preserve an incumbent compromise without proving that compromise unavoidable. Claims
of exact lexicographic optimality require the appropriate bounds for every preceding stage.

## Experiments to run before making effectiveness claims

1. **Freeze semantics and validators.** Reconcile manuscript equations, code, and administrator
   interpretation. Build a schedule checker independent of model-row generation, including
   overlapping meeting patterns, course separation, qualifications, workload, and room rules.
   Document whether each reported count is a conflicting pair, affected section, or aggregate
   slack; they are not interchangeable.
2. **Describe data and evaluation units.** Publish dimensions, eligibility density, conflict
   density, room capacity distribution, and provenance for each case. Use multiple academic
   terms/years where available. Public synthetic instances should vary those properties with
   fixed generation seeds. Perturbations of one Telfer case are not independent universities.
3. **Use matched baselines.** Compare the full staged model to a straightforward implementation
   with all rows loaded initially, and to sequential faculty assignment then timetabling.
   Apply the same rule set and total compute budget. Compare to an existing manual schedule
   only when it represents the same offerings, resource availability, and constraints.
4. **Ablate mechanisms separately.** Test deferred rows on/off, repaired incumbent transfer
   on/off, room seeding on/off, and qualification narrowing on/off. For narrowing, report lost
   eligible assignments, feasibility/quality changes and runtime; this is a model-changing
   experiment. Hold objective priorities fixed for computational ablations.
5. **Separate policy experiments.** Vary priority order or calibrated weighted objectives only
   as an explicit policy sensitivity study. Report the full objective vector and changes in
   unstaffed, unscheduled, off-campus, conflict, and faculty preference outcomes. A higher final
   reward alone cannot establish improvement over a different compromise hierarchy.
6. **Measure whole-run performance.** Fix hardware, thread count, solver versions and seeds.
   Give every variant a declared total budget including preparation and all stages, or disclose
   stage allocations and total elapsed time explicitly. Record build time, time to first valid
   incumbent, each stage's incumbent and bound, termination reason, peak memory where measured,
   and final schedule-check result. Report timeouts and failures, not only successful cases.
7. **Evaluate stability and uncertainty.** Repeat identical deterministic runs to detect drift.
   If varying seeds, predeclare the seeds and report their distributions rather than selecting
   the best run. Aggregate at the instance level, provide paired differences, and explain any
   uncertainty interval assumptions. Distinguish seed variability from variation across real
   institutional cases.
8. **Package the evidence.** Archive an immutable commit, dependency lock, licensed/shareable
   instances or a documented synthetic substitute, commands, parameters, raw results, checker,
   and scripts regenerating every table. Invite someone outside the implementation team to
   execute it. Artifact availability and independently validated findings are distinct. [7]

No experiments described in this section have been executed as part of this literature note.
No external benchmark score, scheduling improvement percentage, or publication acceptance
prediction is asserted.

## Sources

1. Luca Di Gaspero, Barry McCollum, Andrea Schaerf (2007).
   *The Second International Timetabling Competition (ITC-2007): Curriculum-based Course
   Timetabling (Track 3).* [Official technical report](https://www.eeecs.qub.ac.uk/itc2007/curriculmcourse/report/curriculumtechreport.pdf).
   Supporting official pages: [problem model](https://www.eeecs.qub.ac.uk/itc2007/curriculmcourse/course_curriculm_index_files/problemmodel.htm),
   [evaluation](https://www.eeecs.qub.ac.uk/itc2007/curriculmcourse/course_curriculm_index_files/evaluation.htm),
   [input format](https://www.eeecs.qub.ac.uk/itc2007/curriculmcourse/course_curriculm_index_files/Inputformat.htm),
   [validator](https://www.eeecs.qub.ac.uk/itc2007/curriculmcourse/course_curriculm_index_files/validation.htm).
2. Tomáš Müller, Hana Rudová, Zuzana Müllerová (2018).
   *University course timetabling and International Timetabling Competition 2019*,
   PATAT 2018, pp. 5–31. [Author-hosted paper](https://www.unitime.org/papers/itc2019-patat2018.pdf).
   Journal treatment: *Real-world university course timetabling at the International
   Timetabling Competition 2019*, Journal of Scheduling 28, 247–267 (2025),
   [DOI](https://doi.org/10.1007/s10951-023-00801-w).
   [Official competition overview](https://www.itc2019.org/),
   [format](https://www.itc2019.org/format), [rules](https://www.itc2019.org/rules).
3. Aldy Gunawan, Kien Ming Ng, Kim Leng Poh (2007).
   *Solving the teacher assignment-course scheduling problem by a hybrid Algorithm.*
   International Journal of Computer, Information, and Systems Science, and Engineering
   1(2), 136–141. [Author's institutional repository](https://ink.library.smu.edu.sg/sis_research/4001/).
4. Bruno Domenech, Amaia Lusa (2016).
   *A MILP model for the teacher assignment problem considering teachers' preferences.*
   European Journal of Operational Research 249(3), 1153–1160.
   [DOI](https://doi.org/10.1016/j.ejor.2015.08.057),
   [institutional repository and open manuscript](https://upcommons.upc.edu/entities/publication/8c7700e0-698b-4bbb-8cf3-a43165ea90c4).
5. Edmund K. Burke, Jakub Mareček, Andrew J. Parkes, Hana Rudová (2010).
   *Decomposition, Reformulation, and Diving in University Course Timetabling.*
   Computers & Operations Research 37(3), 582–597.
   [DOI](https://doi.org/10.1016/j.cor.2009.02.023),
   [author preprint](https://arxiv.org/abs/0903.1095).
6. Moa Johannesson, Lina Brink, Alvin Combrink, Sabino Francesco Roselli, Martin Fabian (2026).
   *A General Formulation for the Teaching Assignment Problem: Computational Analysis Over
   a Real-World Dataset.* [Author preprint, arXiv:2602.09605](https://arxiv.org/abs/2602.09605).
   This note does not establish peer-reviewed publication status or independently verify
   the authors' experimental outcomes.
7. Association for Computing Machinery. *Artifact Review and Badging*, version 1.1 guidance.
   [Canonical policy](https://www.acm.org/publications/policies/artifact-review-and-badging-current).
   The canonical URL returned HTTP 403 during this review; the text was available through
   [ACM's publication-site mirror](https://prod-www.acm.bloomreach.cloud/publications/policies/artifact-review-and-badging-current).
