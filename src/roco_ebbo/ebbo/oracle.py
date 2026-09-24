"""Deterministic, offline engineering Mock expensive-oracle adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from roco_ebbo.ebbo.baseline import MOCK_SEARCH_SPACE_VERSION, MockSearchSpace
from roco_ebbo.ebbo.contracts import (
    EvaluationStatus,
    JsonValue,
    OracleRequest,
    OracleResult,
    stable_id,
)

MOCK_ORACLE_VERSION = "ebbo-mock-expensive-oracle-v1"
MOCK_COST_SOURCE = "ebbo-mock-fixed-cost-v1"
MOCK_COST_UNIT = "mock-evaluation-unit"


@dataclass(frozen=True, slots=True)
class MockOracleOutcome:
    """Deterministic fault injection used only by tests and the engineering Mock."""

    kind: str = "success"
    actual_cost: float | None = 1.0

    def __post_init__(self) -> None:
        if self.kind not in {"success", "failed", "timed_out", "invalid_result"}:
            raise ValueError("unknown Mock oracle outcome")


@dataclass(frozen=True, slots=True)
class AcceptedAttempt:
    request: OracleRequest
    attempt_id: str
    x: int
    outcome: MockOracleOutcome


class _DispatchPermit:
    pass


class MockExpensiveOracle:
    """In-process adapter with no network, provider, credential, or fee surface."""

    def __init__(
        self,
        search_space: MockSearchSpace,
        *,
        outcomes: dict[int, MockOracleOutcome] | None = None,
    ) -> None:
        self.search_space = search_space
        self.outcomes = dict(outcomes or {})
        self._permit: _DispatchPermit | None = None

    def _bind_scheduler(self) -> _DispatchPermit:
        if self._permit is not None:
            raise RuntimeError("Mock oracle is already bound to a scheduler")
        self._permit = _DispatchPermit()
        return self._permit

    def expected_cost(self, candidate: dict[str, JsonValue]) -> dict[str, JsonValue]:
        self.search_space.validate_candidate(candidate)
        return {"amount": 1.0, "unit": MOCK_COST_UNIT, "source": MOCK_COST_SOURCE}

    def accept(self, request: OracleRequest, *, permit: object) -> AcceptedAttempt:
        """Accept only a scheduler-authorized request; no completion occurs here."""

        self._require_permit(permit)
        if request.problem_id != self.search_space.problem_id:
            raise ValueError("request problem_id does not match Mock search space")
        if request.oracle_contract_version != MOCK_ORACLE_VERSION:
            raise ValueError("request oracle contract does not match Mock adapter")
        if request.replicate_index != 0:
            raise ValueError("P9a Mock oracle does not permit replicate dispatch")
        x = self.search_space.validate_candidate(request.candidate)
        if request.candidate_id != self.search_space.candidate_id(request.candidate):
            raise ValueError("request candidate_id does not match candidate")
        attempt_id = stable_id(
            "attempt",
            {
                "adapter_version": MOCK_ORACLE_VERSION,
                "request_id": request.request_id,
                "attempt_index": 0,
            },
        )
        return AcceptedAttempt(
            request=request,
            attempt_id=attempt_id,
            x=x,
            outcome=self.outcomes.get(x, MockOracleOutcome()),
        )

    def complete(self, attempt: AcceptedAttempt, *, permit: object) -> dict[str, Any]:
        """Return one deterministic raw result for an already accepted attempt."""

        self._require_permit(permit)
        outcome = attempt.outcome
        cost: dict[str, JsonValue] = {
            "amount": outcome.actual_cost,
            "unit": MOCK_COST_UNIT,
            "source": MOCK_COST_SOURCE,
        }
        metadata: dict[str, JsonValue] = {
            "adapter_version": MOCK_ORACLE_VERSION,
            "search_space_version": MOCK_SEARCH_SPACE_VERSION,
            "objective_contract": "square-distance-to-two-plus-one-v1",
            "network": "unused",
            "financial_cost": 0.0,
            "financial_cost_currency": "NONE",
        }
        if outcome.kind == "invalid_result":
            return {
                "schema_version": "ebbo-oracle-result-v1",
                "result_id": "invalid-result-id",
                "request_id": attempt.request.request_id,
                "attempt_id": attempt.attempt_id,
                "status": "succeeded",
                "objective": "not-a-number",
                "constraints": None,
                "feasible": None,
                "failure": None,
                "actual_cost": cost,
                "noise": {"kind": "none"},
                "oracle_metadata": metadata,
                "started_at_utc": None,
                "completed_at_utc": None,
            }
        if outcome.kind == "success":
            objective = float((attempt.x - 2) ** 2 + 1)
            result = OracleResult.create(
                request_id=attempt.request.request_id,
                attempt_id=attempt.attempt_id,
                status=EvaluationStatus.SUCCEEDED,
                objective=objective,
                constraints=None,
                feasible=None,
                failure=None,
                actual_cost=cost,
                oracle_metadata=metadata,
            )
            return result.to_dict()
        status = (
            EvaluationStatus.TIMED_OUT if outcome.kind == "timed_out" else EvaluationStatus.FAILED
        )
        result = OracleResult.create(
            request_id=attempt.request.request_id,
            attempt_id=attempt.attempt_id,
            status=status,
            objective=None,
            constraints=None,
            feasible=None,
            failure={
                "type": "mock_timeout" if status is EvaluationStatus.TIMED_OUT else "mock_failure",
                "message": "deterministic engineering Mock outcome",
                "retryable": False,
            },
            actual_cost=cost,
            oracle_metadata=metadata,
        )
        return result.to_dict()

    def _require_permit(self, permit: object) -> None:
        if self._permit is None or permit is not self._permit:
            raise PermissionError("only the bound serial scheduler may dispatch the Mock oracle")
