"""Independent monotonic budget ledger for accepted EBBO oracle attempts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, cast

from roco_ebbo.ebbo.contracts import EvaluationStatus, JsonValue, require_json_safe

EBBO_LEDGER_VERSION = "ebbo-ledger-v1"


class EBBOBudgetExceeded(RuntimeError):
    """Raised before dispatch when an EBBO hard limit cannot admit a request."""


@dataclass(slots=True)
class EBBOLedger:
    """P9a-only ledger; deliberately unrelated to the Stage 2--5 BudgetLedger."""

    max_oracle_calls: int | None
    max_candidate_proposals: int | None
    max_cost: float | None
    cost_unit: str
    oracle_calls: int = 0
    evaluations_succeeded: int = 0
    evaluations_failed: int = 0
    candidate_proposals: int = 0
    known_cost: float = 0.0
    wall_time_seconds: float = 0.0
    failure_breakdown: dict[str, int] = field(default_factory=dict)
    unknown_cost_attempt_ids: list[str] = field(default_factory=list)
    _reservations: dict[str, float | None] = field(default_factory=dict, repr=False)
    _accepted_attempts: dict[str, str] = field(default_factory=dict, repr=False)
    _settled_attempts: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        for name, value in {
            "max_oracle_calls": self.max_oracle_calls,
            "max_candidate_proposals": self.max_candidate_proposals,
        }.items():
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or null")
        if self.max_cost is not None and (
            type(self.max_cost) not in (int, float)
            or not math.isfinite(self.max_cost)
            or self.max_cost < 0
        ):
            raise ValueError("max_cost must be finite and non-negative or null")
        if not self.cost_unit:
            raise ValueError("cost_unit must be non-empty")

    @property
    def evaluations_total(self) -> int:
        return self.evaluations_succeeded + self.evaluations_failed

    @property
    def evaluations_timed_out(self) -> int:
        return self.failure_breakdown.get("timed_out", 0)

    @property
    def llm_calls(self) -> int:
        return 0

    @property
    def tokens(self) -> int:
        return 0

    @property
    def accounting_complete(self) -> bool:
        return not self.unknown_cost_attempt_ids

    @property
    def reached_limits(self) -> tuple[str, ...]:
        reached: list[str] = []
        if self.max_oracle_calls is not None and self.oracle_calls >= self.max_oracle_calls:
            reached.append("oracle_calls")
        if (
            self.max_candidate_proposals is not None
            and self.candidate_proposals >= self.max_candidate_proposals
        ):
            reached.append("candidate_proposals")
        if self.max_cost is not None and self.known_cost >= self.max_cost:
            reached.append("cost")
        if self.unknown_cost_attempt_ids:
            reached.append("unknown_cost")
        return tuple(reached)

    @property
    def exceeded_limits(self) -> tuple[str, ...]:
        exceeded: list[str] = []
        if self.max_oracle_calls is not None and self.oracle_calls > self.max_oracle_calls:
            exceeded.append("oracle_calls")
        if (
            self.max_candidate_proposals is not None
            and self.candidate_proposals > self.max_candidate_proposals
        ):
            exceeded.append("candidate_proposals")
        if self.max_cost is not None and self.known_cost > self.max_cost:
            exceeded.append("cost")
        return tuple(exceeded)

    def record_candidate_proposal(self, count: int = 1) -> None:
        if type(count) is not int or count < 0:
            raise ValueError("candidate proposal count must be a non-negative integer")
        projected = self.candidate_proposals + count
        if self.max_candidate_proposals is not None and projected > self.max_candidate_proposals:
            raise EBBOBudgetExceeded("candidate proposal budget would be exceeded")
        self.candidate_proposals = projected

    def reserve(self, request_id: str, expected_cost: float | None) -> None:
        """Preflight a request without counting an oracle call."""

        if request_id in self._reservations:
            raise ValueError("request already has an active reservation")
        if self._accepted_attempts:
            raise EBBOBudgetExceeded("serial P9a scheduler already has an accepted attempt")
        if self.unknown_cost_attempt_ids:
            raise EBBOBudgetExceeded("unknown accepted cost requires fail-closed scheduling")
        if self.max_oracle_calls is not None and self.oracle_calls + 1 > self.max_oracle_calls:
            raise EBBOBudgetExceeded("oracle call budget would be exceeded")
        normalized_cost = _optional_cost(expected_cost, "expected_cost")
        reserved_known = sum(item for item in self._reservations.values() if item is not None)
        if self.max_cost is not None:
            if normalized_cost is None:
                raise EBBOBudgetExceeded("unknown expected cost cannot enter a limited cost budget")
            if self.known_cost + reserved_known + normalized_cost > self.max_cost:
                raise EBBOBudgetExceeded("cost budget would be exceeded")
        self._reservations[request_id] = normalized_cost

    def cancel_before_accept(self, request_id: str) -> None:
        if request_id not in self._reservations:
            raise ValueError("request has no active reservation")
        del self._reservations[request_id]

    def accept(self, request_id: str, attempt_id: str) -> None:
        """Permanently count an accepted attempt before any completion handling."""

        if request_id not in self._reservations:
            raise ValueError("accepted request has no reservation")
        if attempt_id in self._accepted_attempts or attempt_id in self._settled_attempts:
            raise ValueError("attempt_id has already been recorded")
        del self._reservations[request_id]
        self.oracle_calls += 1
        self._accepted_attempts[attempt_id] = request_id

    def settle(
        self,
        attempt_id: str,
        *,
        status: EvaluationStatus,
        actual_cost: float | None,
        failure_type: str | None = None,
    ) -> None:
        """Settle an accepted attempt without ever rolling back its call count."""

        if attempt_id not in self._accepted_attempts:
            raise ValueError("attempt is not accepted or was already settled")
        if status not in {
            EvaluationStatus.SUCCEEDED,
            EvaluationStatus.FAILED,
            EvaluationStatus.TIMED_OUT,
        }:
            raise ValueError("settlement requires a terminal oracle status")
        if status is EvaluationStatus.SUCCEEDED and failure_type is not None:
            raise ValueError("successful evaluation cannot have a failure_type")
        normalized_cost = _optional_cost(actual_cost, "actual_cost")
        del self._accepted_attempts[attempt_id]
        self._settled_attempts.add(attempt_id)
        if normalized_cost is None:
            self.unknown_cost_attempt_ids.append(attempt_id)
        else:
            self.known_cost += normalized_cost
        if status is EvaluationStatus.SUCCEEDED:
            self.evaluations_succeeded += 1
        else:
            self.evaluations_failed += 1
            category = failure_type or status.value
            self.failure_breakdown[category] = self.failure_breakdown.get(category, 0) + 1

    def observe_wall_time(self, elapsed_seconds: float) -> None:
        if type(elapsed_seconds) not in (int, float) or not math.isfinite(elapsed_seconds):
            raise ValueError("wall time must be finite")
        if elapsed_seconds < 0:
            raise ValueError("wall time must be non-negative")
        self.wall_time_seconds = max(self.wall_time_seconds, float(elapsed_seconds))

    def replay_dict(self) -> dict[str, JsonValue]:
        value = self.to_dict()
        value.pop("wall_time_seconds")
        return value

    def to_dict(self) -> dict[str, JsonValue]:
        unknown_attempt_ids = cast(list[JsonValue], sorted(self.unknown_cost_attempt_ids))
        active_request_ids = cast(list[JsonValue], sorted(self._reservations))
        accepted_attempt_ids = cast(list[JsonValue], sorted(self._accepted_attempts))
        value: dict[str, JsonValue] = {
            "schema_version": EBBO_LEDGER_VERSION,
            "oracle_calls": self.oracle_calls,
            "evaluations": {
                "total": self.evaluations_total,
                "succeeded": self.evaluations_succeeded,
                "failed": self.evaluations_failed,
                "failure_breakdown": dict(sorted(self.failure_breakdown.items())),
            },
            "candidate_proposals": self.candidate_proposals,
            "llm_calls": 0,
            "tokens": {"input": 0, "output": 0, "total": 0},
            "cost": {
                "known_total": self.known_cost,
                "unit": self.cost_unit,
                "accounting_complete": self.accounting_complete,
                "unknown_attempt_ids": unknown_attempt_ids,
            },
            "wall_time_seconds": self.wall_time_seconds,
            "reservations": {
                "active_request_ids": active_request_ids,
                "accepted_attempt_ids": accepted_attempt_ids,
            },
            "limits": {
                "max_oracle_calls": self.max_oracle_calls,
                "max_candidate_proposals": self.max_candidate_proposals,
                "max_cost": self.max_cost,
                "cost_unit": self.cost_unit,
            },
            "reached_limits": list(self.reached_limits),
            "exceeded_limits": list(self.exceeded_limits),
        }
        require_json_safe(value)
        return value

    def to_snapshot(self) -> dict[str, JsonValue]:
        return self.to_dict()


def _optional_cost(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative or null")
    return float(value)
