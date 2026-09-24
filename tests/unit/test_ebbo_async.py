"""P9c finite pending, irrevocable accounting, cancellation, and recovery tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from roco_ebbo.ebbo.async_ledger import AsyncEBBOLedger
from roco_ebbo.ebbo.async_scheduler import AsyncMockScheduler
from roco_ebbo.ebbo.baseline import CandidatePool, CandidatePoolEntry, MockSearchSpace
from roco_ebbo.ebbo.contracts import EvaluationStatus, canonical_json, stable_id
from roco_ebbo.ebbo.ledger import EBBOBudgetExceeded
from roco_ebbo.ebbo.oracle import MOCK_COST_UNIT, MockExpensiveOracle, MockOracleOutcome
from roco_ebbo.ebbo.scheduler import DuplicateDispatchError, NoCandidateError
from roco_ebbo.ebbo.store import AuditEvent, ObservationStore


class CountingOracle(MockExpensiveOracle):
    def __init__(
        self, space: MockSearchSpace, outcomes: dict[int, MockOracleOutcome] | None = None
    ) -> None:
        super().__init__(space, outcomes=outcomes)
        self.accept_count = 0

    def accept(self, request: Any, *, permit: object) -> Any:
        self.accept_count += 1
        return super().accept(request, permit=permit)


def _setup(
    root: Path,
    *,
    max_calls: int = 4,
    max_cost: float = 4.0,
    max_concurrency: int = 2,
    outcomes: dict[int, MockOracleOutcome] | None = None,
) -> tuple[AsyncMockScheduler, CountingOracle]:
    space = MockSearchSpace(-2, 3)
    oracle = CountingOracle(space, outcomes)
    scheduler = AsyncMockScheduler(
        oracle=oracle,
        ledger=AsyncEBBOLedger(
            max_calls,
            100,
            max_cost,
            MOCK_COST_UNIT,
            max_concurrency=max_concurrency,
        ),
        store=ObservationStore(root),
        run_id="p9c-unit-run",
        root_seed=19,
        config_digest="p9c-unit-config",
    )
    return scheduler, oracle


def _pool(scheduler: AsyncMockScheduler, x: int) -> CandidatePool:
    space = scheduler.oracle.search_space
    candidate = space.candidate(x)
    return CandidatePool.create(
        (
            CandidatePoolEntry(
                space.candidate_id(candidate),
                candidate,
                predicted_mean=0.0,
                uncertainty=1.0,
                acquisition_score=0.0,
            ),
        ),
        ledger=scheduler.ledger,
    )


def _resume(
    root: Path,
    *,
    max_calls: int = 4,
    max_cost: float = 4.0,
    max_concurrency: int = 2,
    outcomes: dict[int, MockOracleOutcome] | None = None,
) -> tuple[AsyncMockScheduler, CountingOracle]:
    oracle = CountingOracle(MockSearchSpace(-2, 3), outcomes)
    scheduler = AsyncMockScheduler.resume(
        oracle=oracle,
        store=ObservationStore(root),
        run_id="p9c-unit-run",
        root_seed=19,
        config_digest="p9c-unit-config",
        max_oracle_calls=max_calls,
        max_candidate_proposals=100,
        max_cost=max_cost,
        max_concurrency=max_concurrency,
    )
    return scheduler, oracle


def test_reserved_accepted_and_cost_holds_prevent_overbooking(tmp_path: Path) -> None:
    scheduler, oracle = _setup(tmp_path, max_calls=2, max_cost=2.0)
    first = scheduler.reserve(_pool(scheduler, 0))
    second = scheduler.reserve(_pool(scheduler, 1))
    assert scheduler.ledger.outstanding == 2
    assert scheduler.ledger.expected_cost_held == 2.0
    assert scheduler.ledger.oracle_calls == oracle.accept_count == 0

    third_pool = _pool(scheduler, 2)
    with pytest.raises(EBBOBudgetExceeded, match="max_concurrency"):
        scheduler.reserve(third_pool)
    assert scheduler.store.events[-1].kind == "async_dispatch_rejected"
    assert scheduler.ledger.oracle_calls == 0

    assert scheduler.cancel(first.request_id) is EvaluationStatus.CANCELLED_BEFORE_ACCEPT
    assert scheduler.ledger.outstanding == 1
    assert scheduler.ledger.expected_cost_held == 1.0
    third = scheduler.reserve(third_pool)
    scheduler.accept(second.request_id)
    scheduler.accept(third.request_id)
    assert scheduler.ledger.oracle_calls == oracle.accept_count == 2
    assert scheduler.ledger.expected_cost_held == 2.0
    assert scheduler.ledger.evaluations_total == 0
    scheduler.complete_batch((third.request_id, second.request_id))
    assert scheduler.ledger.oracle_calls == 2
    assert scheduler.ledger.evaluations_succeeded == 2
    assert scheduler.ledger.known_cost == 2.0
    assert scheduler.ledger.expected_cost_held == 0.0
    assert [item.request_id for item in scheduler.results] == sorted(
        (second.request_id, third.request_id)
    )
    with pytest.raises(EBBOBudgetExceeded):
        scheduler.reserve(_pool(scheduler, 3))
    assert scheduler.ledger.oracle_calls == 2


def test_accepted_after_cancel_and_late_result_never_refund_or_duplicate(tmp_path: Path) -> None:
    scheduler, oracle = _setup(tmp_path, max_calls=1, max_cost=1.0)
    request = scheduler.reserve(_pool(scheduler, 0))
    scheduler.accept(request.request_id)
    assert scheduler.ledger.oracle_calls == 1
    assert scheduler.cancel(request.request_id) is EvaluationStatus.CANCEL_REQUESTED
    assert scheduler.cancel(request.request_id) is EvaluationStatus.CANCEL_REQUESTED
    assert scheduler.ledger.oracle_calls == 1
    assert scheduler.ledger.evaluations_total == 0
    observation = scheduler.acknowledge_cancel(request.request_id)
    assert observation is not None
    assert observation.status is EvaluationStatus.CANCELLED_AFTER_ACCEPT
    assert observation.objective is observation.constraints is observation.feasible is None
    assert scheduler.ledger.evaluations_failed == 1
    assert scheduler.ledger.failure_breakdown == {"cancelled_after_accept": 1}
    assert scheduler.ledger.known_cost == 1.0
    assert scheduler.complete(request.request_id) is None
    assert scheduler.acknowledge_cancel(request.request_id) is None
    assert scheduler.ledger.oracle_calls == oracle.accept_count == 1
    assert len(scheduler.results) == len(scheduler.store.observations) == 1
    assert [e.kind for e in scheduler.store.events][-2:] == [
        "async_late_result",
        "async_late_cancel_ack",
    ]


def test_cancel_result_race_result_wins_and_is_not_overwritten(tmp_path: Path) -> None:
    scheduler, _ = _setup(tmp_path)
    request = scheduler.reserve(_pool(scheduler, 1))
    scheduler.accept(request.request_id)
    scheduler.cancel(request.request_id)
    observation = scheduler.complete(request.request_id)
    assert observation is not None and observation.status is EvaluationStatus.SUCCEEDED
    assert scheduler.acknowledge_cancel(request.request_id) is None
    assert scheduler.ledger.oracle_calls == scheduler.ledger.evaluations_succeeded == 1
    assert len(scheduler.store.observations) == 1


@pytest.mark.parametrize(
    ("outcome", "status", "failure_type"),
    [
        (MockOracleOutcome("failed"), EvaluationStatus.FAILED, "mock_failure"),
        (MockOracleOutcome("timed_out"), EvaluationStatus.TIMED_OUT, "mock_timeout"),
        (MockOracleOutcome("invalid_result"), EvaluationStatus.FAILED, "invalid_result"),
    ],
)
def test_failed_timeout_invalid_result_are_facts_not_penalties(
    tmp_path: Path,
    outcome: MockOracleOutcome,
    status: EvaluationStatus,
    failure_type: str,
) -> None:
    scheduler, _ = _setup(tmp_path, outcomes={0: outcome})
    request = scheduler.reserve(_pool(scheduler, 0))
    scheduler.accept(request.request_id)
    observation = scheduler.complete(request.request_id)
    assert observation is not None and observation.status is status
    assert observation.objective is observation.constraints is observation.feasible is None
    assert observation.eligible_for_objective_surrogate is False
    assert observation.failure is not None and observation.failure["type"] == failure_type
    assert scheduler.ledger.oracle_calls == scheduler.ledger.evaluations_failed == 1


@pytest.mark.parametrize("cost", [None, 2.0])
def test_unknown_actual_cost_and_overrun_close_new_admission(
    tmp_path: Path,
    cost: float | None,
) -> None:
    scheduler, _ = _setup(
        tmp_path,
        max_calls=2,
        max_cost=1.0,
        outcomes={0: MockOracleOutcome("success", actual_cost=cost)},
    )
    request = scheduler.reserve(_pool(scheduler, 0))
    scheduler.accept(request.request_id)
    scheduler.complete(request.request_id)
    assert scheduler.ledger.oracle_calls == 1
    if cost is None:
        assert len(scheduler.ledger.unknown_cost_attempt_ids) == 1
        assert scheduler.ledger.known_cost == 0.0
    else:
        assert scheduler.ledger.known_cost == 2.0
        assert scheduler.ledger.exceeded_limits == ("cost",)
    with pytest.raises(EBBOBudgetExceeded):
        scheduler.reserve(_pool(scheduler, 1))
    assert scheduler.ledger.oracle_calls == 1


def test_duplicate_pool_membership_and_oracle_capability_are_audited(tmp_path: Path) -> None:
    scheduler, oracle = _setup(tmp_path)
    pool = _pool(scheduler, 0)
    with pytest.raises(ValueError, match="current candidate pool"):
        scheduler.reserve(pool, entry_id="unknown-entry")
    assert scheduler.store.events[-1].kind == "async_dispatch_rejected"
    with pytest.raises(NoCandidateError):
        scheduler.reserve(CandidatePool.create((), ledger=scheduler.ledger))
    request = scheduler.reserve(pool)
    with pytest.raises(DuplicateDispatchError):
        scheduler.reserve(pool)
    scheduler.accept(request.request_id)
    with pytest.raises(DuplicateDispatchError):
        scheduler.reserve(pool)
    assert scheduler.ledger.oracle_calls == 1
    with pytest.raises(PermissionError, match="scheduler"):
        oracle.accept(request, permit=object())


@pytest.mark.parametrize("phase", ["reserved", "accepted", "cancel_requested", "settled"])
def test_each_committed_checkpoint_phase_resumes_without_reaccept(
    tmp_path: Path,
    phase: str,
) -> None:
    scheduler, _ = _setup(tmp_path)
    request = scheduler.reserve(_pool(scheduler, 0))
    if phase != "reserved":
        scheduler.accept(request.request_id)
    if phase in {"cancel_requested", "settled"}:
        scheduler.cancel(request.request_id)
    if phase == "settled":
        scheduler.acknowledge_cancel(request.request_id)
    before_events = scheduler.store.semantic_snapshot()
    before_ledger = scheduler.ledger.replay_dict()
    restored, oracle = _resume(tmp_path)
    assert oracle.accept_count == 0
    assert restored.store.semantic_snapshot() == before_events
    assert restored.ledger.replay_dict() == before_ledger
    if phase == "reserved":
        restored.accept(request.request_id)
        assert oracle.accept_count == 1
    elif phase == "accepted":
        restored.complete(request.request_id)
    elif phase == "cancel_requested":
        restored.acknowledge_cancel(request.request_id)
    else:
        assert not restored.pending
    assert restored.ledger.oracle_calls == 1


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "hash",
        "unknown_field",
        "duplicate_json",
        "wrong_config",
        "orphan_temp",
        "orphan_audit",
        "missing_observations",
        "rehash_pending",
    ],
)
def test_damaged_or_mismatched_checkpoint_fails_closed(tmp_path: Path, damage: str) -> None:
    scheduler, _ = _setup(tmp_path)
    request = scheduler.reserve(_pool(scheduler, 0))
    scheduler.accept(request.request_id)
    scheduler.complete(request.request_id)
    checkpoint = tmp_path / "checkpoint.json"
    if damage == "missing":
        checkpoint.unlink()
    elif damage == "hash":
        checkpoint.write_text(
            checkpoint.read_text().replace("p9c-unit-config", "wrong"), encoding="utf-8"
        )
    elif damage == "unknown_field":
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        state["extra"] = 1
        checkpoint.write_text(canonical_json(state), encoding="utf-8")
    elif damage == "duplicate_json":
        checkpoint.write_text('{"x":1,"x":2}', encoding="utf-8")
    elif damage == "wrong_config":
        with pytest.raises(ValueError, match="identity"):
            AsyncMockScheduler.resume(
                oracle=CountingOracle(MockSearchSpace(-2, 3)),
                store=ObservationStore(tmp_path),
                run_id="p9c-unit-run",
                root_seed=19,
                config_digest="wrong",
                max_oracle_calls=4,
                max_candidate_proposals=100,
                max_cost=4.0,
                max_concurrency=2,
            )
        return
    elif damage == "orphan_temp":
        (tmp_path / "checkpoint.json.tmp").write_text("partial", encoding="utf-8")
    elif damage == "orphan_audit":
        scheduler.store.append_audit(AuditEvent.create(len(scheduler.store.events), "orphan", {}))
    elif damage == "missing_observations":
        (tmp_path / "observations.jsonl").unlink()
    else:
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        state["state"]["pending"] = [
            {"request_id": request.request_id, "status": "accepted", "attempt_id": "wrong"}
        ]
        body = {key: value for key, value in state.items() if key != "checkpoint_id"}
        state["checkpoint_id"] = stable_id("async-checkpoint", body)
        checkpoint.write_text(canonical_json(state), encoding="utf-8")
    with pytest.raises(ValueError):
        _resume(tmp_path)


def test_invalid_transition_callbacks_are_audited_without_dispatch(tmp_path: Path) -> None:
    scheduler, oracle = _setup(tmp_path)
    request = scheduler.reserve(_pool(scheduler, 0))
    with pytest.raises(ValueError, match="not accepted"):
        scheduler.complete(request.request_id)
    assert scheduler.store.events[-1].kind == "async_completion_rejected"
    with pytest.raises(ValueError, match="cancel acknowledgement"):
        scheduler.acknowledge_cancel(request.request_id)
    assert scheduler.store.events[-1].kind == "async_cancel_ack_rejected"
    assert oracle.accept_count == scheduler.ledger.oracle_calls == 0
    scheduler.accept(request.request_id)
    with pytest.raises(ValueError, match="not reserved"):
        scheduler.accept(request.request_id)
    assert scheduler.store.events[-1].kind == "async_accept_rejected"
    assert oracle.accept_count == scheduler.ledger.oracle_calls == 1
    scheduler.complete(request.request_id)
    assert scheduler.complete(request.request_id) is None
    assert scheduler.store.events[-1].kind == "async_late_result"
    with pytest.raises(ValueError, match="no accepted"):
        scheduler.complete("unknown-request")
    assert scheduler.store.events[-1].kind == "async_completion_rejected"
    assert scheduler.ledger.oracle_calls == 1


class WrongCostUnitOracle(CountingOracle):
    def complete(self, attempt: Any, *, permit: object) -> dict[str, Any]:
        raw = super().complete(attempt, permit=permit)
        raw["actual_cost"]["unit"] = "not-mock-unit"
        return raw


def test_invalid_cost_unit_is_unknown_not_relabelled_as_mock_cost(tmp_path: Path) -> None:
    space = MockSearchSpace(-2, 3)
    oracle = WrongCostUnitOracle(space)
    scheduler = AsyncMockScheduler(
        oracle=oracle,
        ledger=AsyncEBBOLedger(2, 10, 2.0, MOCK_COST_UNIT, max_concurrency=2),
        store=ObservationStore(tmp_path),
        run_id="wrong-cost-unit",
        root_seed=19,
        config_digest="wrong-cost-config",
    )
    request = scheduler.reserve(_pool(scheduler, 0))
    scheduler.accept(request.request_id)
    observation = scheduler.complete(request.request_id)
    assert observation is not None and observation.status is EvaluationStatus.FAILED
    assert observation.actual_cost["amount"] is None
    assert scheduler.ledger.known_cost == 0.0
    assert scheduler.ledger.unknown_cost_attempt_ids == [observation.attempt_id]
    with pytest.raises(EBBOBudgetExceeded, match="unknown"):
        scheduler.reserve(_pool(scheduler, 1))


@pytest.mark.parametrize("damage", ["accepted_mapping", "known_cost"])
def test_rehashed_but_inconsistent_checkpoint_state_is_rejected(
    tmp_path: Path,
    damage: str,
) -> None:
    scheduler, _ = _setup(tmp_path)
    request = scheduler.reserve(_pool(scheduler, 0))
    attempt_id = scheduler.accept(request.request_id)
    if damage == "known_cost":
        scheduler.complete(request.request_id)
    checkpoint = tmp_path / "checkpoint.json"
    document = json.loads(checkpoint.read_text(encoding="utf-8"))
    ledger_state = document["state"]["ledger"]
    if damage == "accepted_mapping":
        ledger_state["accepted_attempts"][attempt_id] = "other-request"
    else:
        ledger_state["public"]["cost"]["known_total"] = 99.0
    body = {key: value for key, value in document.items() if key != "checkpoint_id"}
    document["checkpoint_id"] = stable_id("async-checkpoint", body)
    checkpoint.write_text(canonical_json(document), encoding="utf-8")
    with pytest.raises(ValueError):
        _resume(tmp_path)
