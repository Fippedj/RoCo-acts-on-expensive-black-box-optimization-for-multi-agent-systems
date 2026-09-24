from __future__ import annotations

from pathlib import Path

import pytest

from roco_ebbo.ebbo import (
    EBBOBudgetExceeded,
    EBBOLedger,
    EvaluationStatus,
    Observation,
    ObservationStore,
    OracleRequest,
    OracleResult,
)
from roco_ebbo.ebbo.store import AuditEvent


def _observation() -> Observation:
    request = OracleRequest.create(
        run_id="store-run",
        problem_id="store-problem",
        candidate_id="candidate-a",
        candidate={"x": 1},
        seed_lineage={"root_seed": 5},
        budget_reservation={"expected_cost": 1.0},
    )
    result = OracleResult.create(
        request_id=request.request_id,
        attempt_id="attempt-a",
        status=EvaluationStatus.SUCCEEDED,
        objective=2.0,
        constraints=None,
        feasible=None,
        failure=None,
        actual_cost={"amount": 1.0, "unit": "mock-unit", "source": "mock-v1"},
        oracle_metadata={},
    )
    return Observation.from_result(request, result)


def test_accepted_attempt_is_permanent_across_failure_timeout_and_cost_overrun() -> None:
    ledger = EBBOLedger(3, 10, 1.5, "mock-unit")
    cases = (
        ("request-a", "attempt-a", EvaluationStatus.FAILED, 1.0, "mock_failure"),
        ("request-b", "attempt-b", EvaluationStatus.TIMED_OUT, 0.5, "timed_out"),
        ("request-c", "attempt-c", EvaluationStatus.SUCCEEDED, 2.0, None),
    )
    for request_id, attempt_id, status, cost, failure_type in cases:
        # The final overrun is accepted only because its expected reservation is zero.
        ledger.reserve(request_id, 0.0)
        ledger.accept(request_id, attempt_id)
        ledger.settle(
            attempt_id,
            status=status,
            actual_cost=cost,
            failure_type=failure_type,
        )

    assert ledger.oracle_calls == 3
    assert ledger.evaluations_succeeded == 1
    assert ledger.evaluations_failed == 2
    assert ledger.evaluations_timed_out == 1
    assert ledger.known_cost == 3.5
    assert ledger.exceeded_limits == ("cost",)


def test_budget_preflight_cancel_and_unknown_cost_never_refund_accepted_calls() -> None:
    ledger = EBBOLedger(1, 10, 1.0, "mock-unit")
    ledger.reserve("cancelled", 1.0)
    ledger.cancel_before_accept("cancelled")
    assert ledger.oracle_calls == 0

    ledger.reserve("accepted", 1.0)
    ledger.accept("accepted", "attempt-unknown")
    ledger.settle(
        "attempt-unknown",
        status=EvaluationStatus.FAILED,
        actual_cost=None,
        failure_type="unknown_cost_failure",
    )
    assert ledger.oracle_calls == 1
    assert ledger.accounting_complete is False
    assert ledger.unknown_cost_attempt_ids == ["attempt-unknown"]
    with pytest.raises(EBBOBudgetExceeded, match="unknown|oracle call"):
        ledger.reserve("later", 0.0)


def test_append_only_store_snapshot_reopen_and_replay_are_consistent(tmp_path: Path) -> None:
    store = ObservationStore(tmp_path / "store")
    event = AuditEvent.create(0, "fixture", {"accepted": True})
    observation = _observation()
    store.append_audit(event)
    store.append_observation(observation)
    snapshot = store.snapshot()
    checksum = store.replay_checksum({"oracle_calls": 1})

    reopened = ObservationStore(tmp_path / "store")
    assert reopened.events == (event,)
    assert reopened.observations == (observation,)
    assert reopened.snapshot() == snapshot
    assert reopened.replay_checksum({"oracle_calls": 1}) == checksum
    with pytest.raises(ValueError, match="already present"):
        reopened.append_observation(observation)
    with pytest.raises(ValueError, match="contiguously"):
        reopened.append_audit(AuditEvent.create(3, "gap", {}))

    leaked_event = reopened.events[0]
    leaked_event.payload["accepted"] = False
    leaked_observation = reopened.observations[0]
    leaked_observation.candidate["x"] = 99
    assert reopened.snapshot() == snapshot
    assert reopened.replay_checksum({"oracle_calls": 1}) == checksum

    event.payload["accepted"] = False
    observation.candidate["x"] = 99
    assert store.snapshot() == snapshot
    assert store.replay_checksum({"oracle_calls": 1}) == checksum

    forged = AuditEvent.create(1, "forged", {"value": 1})
    forged.payload["value"] = 2
    with pytest.raises(ValueError, match="event_id"):
        reopened.append_audit(forged)
    assert reopened.snapshot() == snapshot
