from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from roco_ebbo.ebbo import (
    CandidatePool,
    CandidatePoolEntry,
    DuplicateDispatchError,
    EBBOBudgetExceeded,
    EBBOLedger,
    EvaluationStatus,
    MockExpensiveOracle,
    MockOracleOutcome,
    MockSearchSpace,
    NearestObservationSurrogate,
    NoCandidateError,
    ObservationStore,
    OracleRequest,
    SerialScheduler,
    build_candidate_pool,
)
from roco_ebbo.ebbo.oracle import AcceptedAttempt


def _runtime(
    tmp_path: Path,
    *,
    outcomes: dict[int, MockOracleOutcome] | None = None,
    max_calls: int = 10,
    max_cost: float = 10.0,
) -> tuple[MockSearchSpace, EBBOLedger, MockExpensiveOracle, SerialScheduler]:
    space = MockSearchSpace(-2, 3)
    ledger = EBBOLedger(max_calls, 100, max_cost, "mock-evaluation-unit")
    oracle = MockExpensiveOracle(space, outcomes=outcomes)
    scheduler = SerialScheduler(
        oracle=oracle,
        ledger=ledger,
        store=ObservationStore(tmp_path),
        run_id="scheduler-test",
        root_seed=17,
    )
    return space, ledger, oracle, scheduler


def _pool(space: MockSearchSpace, ledger: EBBOLedger, x: int) -> CandidatePool:
    candidate = space.candidate(x)
    return CandidatePool.create(
        (
            CandidatePoolEntry(
                candidate_id=space.candidate_id(candidate),
                candidate=candidate,
                predicted_mean=0.0,
                uncertainty=1.0,
                acquisition_score=0.0,
            ),
        ),
        ledger=ledger,
    )


@pytest.mark.parametrize(
    ("outcome", "status", "failure_type"),
    [
        (MockOracleOutcome("success"), EvaluationStatus.SUCCEEDED, None),
        (MockOracleOutcome("failed"), EvaluationStatus.FAILED, "mock_failure"),
        (MockOracleOutcome("timed_out"), EvaluationStatus.TIMED_OUT, "mock_timeout"),
        (MockOracleOutcome("invalid_result"), EvaluationStatus.FAILED, "invalid_result"),
    ],
)
def test_scheduler_records_success_failure_timeout_and_invalid_result(
    tmp_path: Path,
    outcome: MockOracleOutcome,
    status: EvaluationStatus,
    failure_type: str | None,
) -> None:
    space, ledger, _, scheduler = _runtime(tmp_path, outcomes={1: outcome})

    observation = scheduler.dispatch(_pool(space, ledger, 1))

    assert ledger.oracle_calls == 1
    assert observation.status is status
    if status is EvaluationStatus.SUCCEEDED:
        assert observation.objective == 2.0
        assert observation.failure is None
    else:
        assert observation.objective is None
        assert observation.constraints is None
        assert observation.feasible is None
        assert observation.failure is not None
        assert observation.failure["type"] == failure_type


def test_preflight_rejection_and_preaccept_cancel_are_audited_without_call(
    tmp_path: Path,
) -> None:
    space, ledger, _, scheduler = _runtime(tmp_path / "reject", max_calls=0)
    with pytest.raises(EBBOBudgetExceeded):
        scheduler.dispatch(_pool(space, ledger, 0))
    assert ledger.oracle_calls == 0
    assert scheduler.store.events[-1].kind == "dispatch_rejected_budget"

    space, ledger, _, scheduler = _runtime(tmp_path / "cancel")
    scheduler.cancel_before_accept(_pool(space, ledger, 0))
    assert ledger.oracle_calls == 0
    assert scheduler.store.events[-1].kind == "cancelled_before_accept"


def test_actual_cost_overrun_and_unknown_cost_remain_visible_and_fail_closed(
    tmp_path: Path,
) -> None:
    space, overrun, _, scheduler = _runtime(
        tmp_path / "overrun",
        outcomes={0: MockOracleOutcome("success", actual_cost=2.0)},
        max_cost=1.0,
    )
    scheduler.dispatch(_pool(space, overrun, 0))
    assert overrun.oracle_calls == 1
    assert overrun.known_cost == 2.0
    assert overrun.exceeded_limits == ("cost",)

    space, unknown, _, scheduler = _runtime(
        tmp_path / "unknown",
        outcomes={0: MockOracleOutcome("success", actual_cost=None)},
    )
    scheduler.dispatch(_pool(space, unknown, 0))
    assert unknown.oracle_calls == 1
    assert not unknown.accounting_complete
    with pytest.raises(EBBOBudgetExceeded, match="unknown"):
        scheduler.dispatch(_pool(space, unknown, 1))


def test_duplicate_empty_pool_and_direct_oracle_dispatch_are_rejected(
    tmp_path: Path,
) -> None:
    space, ledger, oracle, scheduler = _runtime(tmp_path)
    pool = _pool(space, ledger, 0)
    scheduler.dispatch(pool)
    with pytest.raises(DuplicateDispatchError):
        scheduler.dispatch(pool)
    assert ledger.oracle_calls == 1

    empty = CandidatePool.create((), ledger=ledger)
    with pytest.raises(NoCandidateError):
        scheduler.dispatch(empty)
    assert ledger.oracle_calls == 1

    request = OracleRequest.create(
        run_id="unauthorized",
        problem_id=space.problem_id,
        candidate_id=space.candidate_id(space.candidate(1)),
        candidate=space.candidate(1),
        seed_lineage={"root_seed": 1},
        budget_reservation={"expected_cost": 1.0},
    )
    with pytest.raises(PermissionError, match="scheduler"):
        oracle.accept(request, permit=object())


def test_candidate_pool_is_finite_deduplicated_immutable_and_tie_broken_by_id() -> None:
    space = MockSearchSpace(-2, 2)
    ledger = EBBOLedger(5, 10, 10.0, "mock-evaluation-unit")
    candidates = [space.candidate(-1), space.candidate(1)]
    entries = tuple(
        CandidatePoolEntry(
            candidate_id=space.candidate_id(candidate),
            candidate=candidate,
            predicted_mean=3.0,
            uncertainty=0.5,
            acquisition_score=2.0,
        )
        for candidate in candidates
    )
    pool = CandidatePool.create((entries[1], entries[0], entries[0]), ledger=ledger)

    assert len(pool.entries) == 2
    assert pool.duplicates_removed == 1
    assert ledger.candidate_proposals == 3
    assert [entry.candidate_id for entry in pool.entries] == sorted(
        entry.candidate_id for entry in entries
    )
    with pytest.raises(FrozenInstanceError):
        pool.pool_id = "changed"  # type: ignore[misc]
    candidates[0]["x"] = 2
    assert pool.entries[0].to_dict()["candidate"] != {"x": 2}
    with pytest.raises(TypeError):
        pool.entries[0].candidate["x"] = 2  # type: ignore[index]


def test_pool_generation_is_seeded_deterministic_and_reports_no_entries_when_exhausted() -> None:
    space = MockSearchSpace(0, 2)
    surrogate = NearestObservationSurrogate(space, prior_mean=10.0)
    first_ledger = EBBOLedger(3, 10, 10.0, "mock-evaluation-unit")
    second_ledger = EBBOLedger(3, 10, 10.0, "mock-evaluation-unit")
    first = build_candidate_pool(
        search_space=space,
        surrogate=surrogate,
        root_seed=29,
        iteration=0,
        pool_size=3,
        beta=2.0,
        excluded_candidate_ids=set(),
        ledger=first_ledger,
    )
    second = build_candidate_pool(
        search_space=space,
        surrogate=surrogate,
        root_seed=29,
        iteration=0,
        pool_size=3,
        beta=2.0,
        excluded_candidate_ids=set(),
        ledger=second_ledger,
    )
    assert first.to_dict() == second.to_dict()

    exhausted = build_candidate_pool(
        search_space=space,
        surrogate=surrogate,
        root_seed=29,
        iteration=1,
        pool_size=3,
        beta=2.0,
        excluded_candidate_ids={space.candidate_id(space.candidate(x)) for x in range(3)},
        ledger=first_ledger,
    )
    assert exhausted.entries == ()


class _ExplodingOracle(MockExpensiveOracle):
    def complete(self, attempt: AcceptedAttempt, *, permit: object) -> dict[str, Any]:
        raise RuntimeError("synthetic post-accept completion failure")


def test_accepted_completion_exception_becomes_failed_observation(tmp_path: Path) -> None:
    space = MockSearchSpace(-2, 3)
    ledger = EBBOLedger(2, 10, 2.0, "mock-evaluation-unit")
    scheduler = SerialScheduler(
        oracle=_ExplodingOracle(space),
        ledger=ledger,
        store=ObservationStore(tmp_path),
        run_id="post-accept-error",
        root_seed=17,
    )

    observation = scheduler.dispatch(_pool(space, ledger, 0))

    assert ledger.oracle_calls == ledger.evaluations_failed == 1
    assert ledger.accounting_complete is False
    assert observation.status is EvaluationStatus.FAILED
    assert observation.objective is observation.constraints is observation.feasible is None
    assert observation.failure is not None
    assert observation.failure["type"] == "invalid_result"
    assert [event.kind for event in scheduler.store.events] == [
        "request_reserved",
        "oracle_accepted",
        "oracle_completion_failed",
        "result_recorded",
        "observation_appended",
    ]
