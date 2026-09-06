"""Restricted searches provide hints without rewriting qualification policy."""

from dataclasses import replace
from typing import Any

import pytest

from scheduler import silent
from scheduler.config import Instance
from scheduler.model import BuiltModel, build
from scheduler.progress import Progress
from scheduler.solve import cold_start
from scheduler.solve.solver import _extract, _placeholder_seed
from scheduler.solve.warm_start import validate_initial_assignments


def test_restricted_candidate_respects_original_model(payload: dict[str, Any]) -> None:
    instance = Instance.from_payload(payload)
    # Add a legal but unpreferred edge, making the restriction effective while
    # leaving the fixture's exact-load matching and preferred edges available.
    instance = replace(
        instance, qualifications=instance.qualifications | {("prof_b", "ADM2000")},
    )
    full = build(instance, Progress(silent))
    candidate = cold_start.restricted_incumbent(full, 2.0, "highs", Progress(silent))

    assert candidate is not None
    assignments = _extract(full, candidate)
    validate_initial_assignments(instance, assignments)
    assert all(assignment.timeslot_id is not None for assignment in assignments)
    assert full.instance is instance
    assert ("prof_b", "ADM2000") in full.instance.qualifications
    assert all(
        assignment.professor_id is None
        or (assignment.professor_id, assignment.course_id) in instance.qualifications
        for assignment in assignments
    )


def test_ineffective_restriction_skips_backend(
    payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = Instance.from_payload(payload)
    instance = replace(instance, course_preference=dict.fromkeys(instance.qualifications, 1.0))
    full = build(instance, Progress(silent))

    def unexpected_backend(*args: Any, **kwargs: Any) -> None:
        pytest.fail("an ineffective restriction must not start a backend")

    monkeypatch.setattr(cold_start, "open_backend", unexpected_backend)
    assert cold_start.restricted_incumbent(full, 1.0, "highs", Progress(silent)) is None


def test_preference_cannot_add_undeclared_qualification(
    payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = Instance.from_payload(payload)
    instance = replace(
        instance, course_preference={**instance.course_preference, ("prof_b", "ADM2000"): 100.0},
    )
    full = build(instance, Progress(silent))
    original = instance.qualifications
    real_build = cold_start.build
    seen = []

    def checked_build(inst: Instance, progress: Progress) -> BuiltModel:
        seen.append(inst.qualifications)
        assert inst.qualifications <= original
        return real_build(inst, progress)

    monkeypatch.setattr(cold_start, "build", checked_build)
    candidate = cold_start.restricted_incumbent(full, 2.0, "highs", Progress(silent))
    # The matching can already need every declared edge, in which case skipping
    # is correct and no invented preference edge may make it appear effective.
    assert not seen or all(qualified <= original for qualified in seen)
    if candidate is not None:
        validate_initial_assignments(instance, _extract(full, candidate))


@pytest.mark.parametrize("budget", [0.0, -1.0, float("inf"), float("nan")])
def test_restricted_search_requires_finite_positive_budget(
    payload: dict[str, Any], budget: float,
) -> None:
    full = build(Instance.from_payload(payload), Progress(silent))
    with pytest.raises(ValueError, match="positive and finite"):
        cold_start.restricted_incumbent(full, budget, "highs", Progress(silent))


def test_missing_load_matching_skips_restricted_search(
    payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scheduler.solve import solver

    full = build(Instance.from_payload(payload), Progress(silent))
    assert _placeholder_seed(full)
    monkeypatch.setattr(solver, "_placeholder_seed", lambda built: [])
    assert cold_start.restricted_incumbent(full, 1.0, "highs", Progress(silent)) is None


@pytest.mark.parametrize(("limit", "budget"), [(None, 10.0), (2.0, 2.0), (60.0, 10.0)])
@pytest.mark.parametrize("has_candidate", [False, True])
def test_solve_invokes_bounded_search_and_uses_candidate(
    payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
    limit: float | None, budget: float, has_candidate: bool,
) -> None:
    from scheduler.solve import solver

    instance = Instance.from_payload(payload)
    candidates: list[list[float]] = []

    def search(
        full: BuiltModel, time_limit: float, backend: str, progress: Progress,
    ) -> list[float] | None:
        assert full.instance is instance
        assert time_limit == budget
        assert backend == "highs"
        candidates.append(_placeholder_seed(full))
        return candidates[-1] if has_candidate else None

    class ReachedFullSolve(Exception):
        pass

    def inspect_start(staged: solver._StagedSolve, *args: Any, **kwargs: Any) -> float:
        assert len(candidates) == 1
        assert staged.time_limit == limit
        assert staged.values == candidates[0]
        if has_candidate:
            assert staged.values is candidates[0]
        else:
            assert staged.values is not candidates[0]
        raise ReachedFullSolve

    monkeypatch.setattr(cold_start, "restricted_incumbent", search)
    monkeypatch.setattr(solver._StagedSolve, "run", inspect_start)
    with pytest.raises(ReachedFullSolve):
        solver.solve_instance(instance, silent, time_limit=limit)


def test_explicit_warm_start_bypasses_automatic_search(
    payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scheduler.solve import solver

    instance = Instance.from_payload(payload)
    built = build(instance, Progress(silent))
    assignments = _extract(built, _placeholder_seed(built))
    expected = solver._schedule_seed(built, assignments)

    def unexpected_search(*args: Any, **kwargs: Any) -> None:
        pytest.fail("explicit validated warm starts must skip automatic restricted search")

    class ReachedFullSolve(Exception):
        pass

    def inspect_start(staged: solver._StagedSolve, *args: Any, **kwargs: Any) -> float:
        assert staged.values == expected
        raise ReachedFullSolve

    monkeypatch.setattr(cold_start, "restricted_incumbent", unexpected_search)
    monkeypatch.setattr(solver._StagedSolve, "run", inspect_start)
    with pytest.raises(ReachedFullSolve):
        solver.solve_instance(instance, silent, time_limit=2, initial_assignments=assignments)
