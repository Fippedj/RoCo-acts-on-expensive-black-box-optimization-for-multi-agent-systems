"""Serial P9a scheduler and the sole Mock oracle dispatch boundary."""

from __future__ import annotations

import math

from roco_ebbo.ebbo.baseline import CandidatePool
from roco_ebbo.ebbo.contracts import (
    EvaluationStatus,
    JsonValue,
    Observation,
    OracleRequest,
    OracleResult,
    derive_seed,
)
from roco_ebbo.ebbo.ledger import EBBOBudgetExceeded, EBBOLedger
from roco_ebbo.ebbo.oracle import MOCK_COST_SOURCE, MOCK_COST_UNIT, MockExpensiveOracle
from roco_ebbo.ebbo.store import AuditEvent, ObservationStore


class DuplicateDispatchError(RuntimeError):
    """Raised when a candidate was already accepted by the oracle."""


class NoCandidateError(RuntimeError):
    """Raised when dispatch is requested with an empty candidate pool."""


class SerialScheduler:
    """A deterministic max_concurrency=1 scheduler; async/pending work is out of scope."""

    max_concurrency = 1

    def __init__(
        self,
        *,
        oracle: MockExpensiveOracle,
        ledger: EBBOLedger,
        store: ObservationStore,
        run_id: str,
        root_seed: int,
        max_concurrency: int = 1,
    ) -> None:
        if max_concurrency != 1:
            raise ValueError("P9a scheduler requires max_concurrency=1")
        if not run_id:
            raise ValueError("run_id must be non-empty")
        self.oracle = oracle
        self.ledger = ledger
        self.store = store
        self.run_id = run_id
        self.root_seed = root_seed
        self._permit = oracle._bind_scheduler()
        self._dispatched_candidate_ids: set[str] = set()
        self._request_index = 0
        self._requests: list[OracleRequest] = []
        self._results: list[OracleResult] = []

    @property
    def dispatched_candidate_ids(self) -> frozenset[str]:
        return frozenset(self._dispatched_candidate_ids)

    @property
    def requests(self) -> tuple[OracleRequest, ...]:
        return tuple(self._requests)

    @property
    def results(self) -> tuple[OracleResult, ...]:
        return tuple(self._results)

    def dispatch(self, pool: CandidatePool) -> Observation:
        if not pool.entries:
            self._audit("dispatch_rejected_empty_pool", {"pool_id": pool.pool_id})
            raise NoCandidateError("candidate pool has no entries")
        selected = pool.selected
        if selected.candidate_id in self._dispatched_candidate_ids:
            self._audit(
                "dispatch_rejected_duplicate",
                {"pool_id": pool.pool_id, "candidate_id": selected.candidate_id},
            )
            raise DuplicateDispatchError("candidate was already dispatched")

        request = self._new_request(selected.candidate_id, dict(selected.candidate), pool.pool_id)
        expected_amount = request.budget_reservation["expected_cost"]
        assert type(expected_amount) in (int, float)
        assert isinstance(expected_amount, (int, float))
        try:
            self.ledger.reserve(request.request_id, float(expected_amount))
        except EBBOBudgetExceeded as exc:
            self._audit(
                "dispatch_rejected_budget",
                {"request": request.replay_dict(), "reason": str(exc)},
            )
            raise
        self._requests.append(request)
        self._audit("request_reserved", {"request": request.to_dict()})

        try:
            accepted = self.oracle.accept(request, permit=self._permit)
        except Exception as exc:
            self.ledger.cancel_before_accept(request.request_id)
            self._audit(
                "oracle_rejected_before_accept",
                {"request_id": request.request_id, "error_type": type(exc).__name__},
            )
            raise

        self.ledger.accept(request.request_id, accepted.attempt_id)
        self._dispatched_candidate_ids.add(selected.candidate_id)
        self._audit(
            "oracle_accepted",
            {
                "request_id": request.request_id,
                "attempt_id": accepted.attempt_id,
                "oracle_calls": self.ledger.oracle_calls,
            },
        )

        try:
            raw_result = self.oracle.complete(accepted, permit=self._permit)
        except Exception as exc:
            raw_result = {
                "completion_error_type": type(exc).__name__,
                "actual_cost": {
                    "amount": None,
                    "unit": MOCK_COST_UNIT,
                    "source": MOCK_COST_SOURCE,
                },
            }
            self._audit(
                "oracle_completion_failed",
                {
                    "request_id": request.request_id,
                    "attempt_id": accepted.attempt_id,
                    "error_type": type(exc).__name__,
                },
            )
        try:
            result = OracleResult.from_dict(raw_result)
            if result.request_id != request.request_id or result.attempt_id != accepted.attempt_id:
                raise ValueError("oracle result identity does not match accepted attempt")
            if result.constraints is not None or result.feasible is not None:
                raise ValueError("P9a unconstrained Mock result cannot include constraints")
        except (TypeError, ValueError) as exc:
            amount = _recover_actual_cost(raw_result)
            result = OracleResult.create(
                request_id=request.request_id,
                attempt_id=accepted.attempt_id,
                status=EvaluationStatus.FAILED,
                objective=None,
                constraints=None,
                feasible=None,
                failure={
                    "type": "invalid_result",
                    "message": "oracle result failed the strict P9a contract",
                    "validation_error_type": type(exc).__name__,
                    "retryable": False,
                },
                actual_cost={
                    "amount": amount,
                    "unit": MOCK_COST_UNIT,
                    "source": MOCK_COST_SOURCE,
                },
                oracle_metadata={
                    "adapter_version": "ebbo-mock-expensive-oracle-v1",
                    "network": "unused",
                    "invalid_result": True,
                },
            )
        actual_amount = result.actual_cost["amount"]
        assert actual_amount is None or type(actual_amount) in (int, float)
        assert actual_amount is None or isinstance(actual_amount, (int, float))
        failure_type = None
        if result.failure is not None:
            raw_failure_type = result.failure.get("type")
            failure_type = raw_failure_type if isinstance(raw_failure_type, str) else "failed"
        self.ledger.settle(
            result.attempt_id,
            status=result.status,
            actual_cost=None if actual_amount is None else float(actual_amount),
            failure_type=failure_type,
        )
        self._results.append(result)
        self._audit(
            "result_recorded",
            {"result": result.to_dict(), "ledger": self.ledger.replay_dict()},
        )
        observation = Observation.from_result(
            request,
            result,
            completion_sequence=len(self.store.observations),
        )
        self.store.append_observation(observation)
        self._audit(
            "observation_appended",
            {"observation": observation.to_dict()},
        )
        return observation

    def cancel_before_accept(self, pool: CandidatePool) -> OracleRequest:
        """Exercise the audited pre-accept cancellation transition without dispatch."""

        if not pool.entries:
            self._audit("cancel_rejected_empty_pool", {"pool_id": pool.pool_id})
            raise NoCandidateError("candidate pool has no entries")
        selected = pool.selected
        if selected.candidate_id in self._dispatched_candidate_ids:
            self._audit(
                "cancel_rejected_duplicate",
                {"pool_id": pool.pool_id, "candidate_id": selected.candidate_id},
            )
            raise DuplicateDispatchError("candidate was already dispatched")
        request = self._new_request(selected.candidate_id, dict(selected.candidate), pool.pool_id)
        expected_amount = request.budget_reservation["expected_cost"]
        assert type(expected_amount) in (int, float)
        assert isinstance(expected_amount, (int, float))
        self.ledger.reserve(request.request_id, float(expected_amount))
        self._requests.append(request)
        self._audit("request_reserved", {"request": request.to_dict()})
        self.ledger.cancel_before_accept(request.request_id)
        self._audit(
            "cancelled_before_accept",
            {
                "request_id": request.request_id,
                "status": EvaluationStatus.CANCELLED_BEFORE_ACCEPT.value,
            },
        )
        return request

    def _new_request(
        self,
        candidate_id: str,
        candidate: dict[str, JsonValue],
        pool_id: str,
    ) -> OracleRequest:
        expected = self.oracle.expected_cost(candidate)
        oracle_seed = derive_seed(self.root_seed, "oracle", self._request_index, candidate_id)
        request = OracleRequest.create(
            run_id=self.run_id,
            problem_id=self.oracle.search_space.problem_id,
            candidate_id=candidate_id,
            candidate=candidate,
            problem_version="mock-quadratic-engineering-v1",
            oracle_contract_version="ebbo-mock-expensive-oracle-v1",
            logical_evaluation_index=self._request_index,
            replicate_index=0,
            oracle_seed=oracle_seed,
            timeout_seconds=1.0,
            seed_lineage={
                "root_seed": self.root_seed,
                "request_index": self._request_index,
                "candidate_seed": derive_seed(
                    self.root_seed, "candidate", self._request_index, candidate_id
                ),
                "oracle_seed": oracle_seed,
            },
            budget_reservation={
                "expected_cost": expected["amount"],
                "cost_unit": expected["unit"],
                "cost_source": expected["source"],
                "oracle_calls": 1,
            },
            provenance={
                "candidate_pool_id": pool_id,
                "acquisition_contract": "ebbo-lower-confidence-bound-v1",
                "scheduler": "ebbo-serial-scheduler-v1",
            },
        )
        self._request_index += 1
        return request

    def _audit(self, kind: str, payload: dict[str, JsonValue]) -> None:
        self.store.append_audit(AuditEvent.create(len(self.store.events), kind, payload))


def _recover_actual_cost(raw_result: object) -> float | None:
    if not isinstance(raw_result, dict):
        return None
    raw_cost = raw_result.get("actual_cost")
    if not isinstance(raw_cost, dict):
        return None
    amount = raw_cost.get("amount")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        return None
    if not math.isfinite(amount) or amount < 0:
        return None
    return float(amount)
