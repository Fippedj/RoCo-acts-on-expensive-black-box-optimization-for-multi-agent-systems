"""P9c-only concurrent Mock ledger; P9a/P9b ledger stays serial and unchanged."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, cast

from roco_ebbo.ebbo.contracts import EvaluationStatus, JsonValue, require_json_safe
from roco_ebbo.ebbo.ledger import EBBOBudgetExceeded, EBBOLedger, _optional_cost

ASYNC_LEDGER_VERSION = "ebbo-async-ledger-v1"


@dataclass(slots=True)
class AsyncEBBOLedger(EBBOLedger):
    """Accepted calls are irreversible; outstanding expected costs remain held."""

    max_concurrency: int = 2
    _pending_costs: dict[str, float | None] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        EBBOLedger.__post_init__(self)
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be a positive integer")

    @property
    def outstanding(self) -> int:
        return len(self._reservations) + len(self._accepted_attempts)

    @property
    def expected_cost_held(self) -> float:
        return sum(x or 0.0 for x in (*self._reservations.values(), *self._pending_costs.values()))

    def reserve(self, request_id: str, expected_cost: float | None) -> None:
        if request_id in self._reservations or request_id in self._accepted_attempts.values():
            raise ValueError("request already reserved or accepted")
        if self.outstanding >= self.max_concurrency:
            raise EBBOBudgetExceeded("max_concurrency would be exceeded")
        if self.unknown_cost_attempt_ids:
            raise EBBOBudgetExceeded("unknown accepted cost closes scheduling")
        if self.max_oracle_calls is not None and (
            self.oracle_calls + len(self._reservations) + 1 > self.max_oracle_calls
        ):
            raise EBBOBudgetExceeded("oracle call budget would be exceeded")
        amount = _optional_cost(expected_cost, "expected_cost")
        if self.max_cost is not None:
            if amount is None:
                raise EBBOBudgetExceeded("unknown expected cost cannot enter limited budget")
            if self.known_cost + self.expected_cost_held + amount > self.max_cost:
                raise EBBOBudgetExceeded("expected cost budget would be exceeded")
        self._reservations[request_id] = amount

    def accept(self, request_id: str, attempt_id: str) -> None:
        amount = self._reservations[request_id]
        EBBOLedger.accept(self, request_id, attempt_id)
        self._pending_costs[attempt_id] = amount

    def settle(
        self,
        attempt_id: str,
        *,
        status: EvaluationStatus,
        actual_cost: float | None,
        failure_type: str | None = None,
    ) -> None:
        if attempt_id not in self._pending_costs:
            raise ValueError("attempt is not pending")
        if status is EvaluationStatus.CANCELLED_AFTER_ACCEPT:
            amount = _optional_cost(actual_cost, "actual_cost")
            if attempt_id not in self._accepted_attempts:
                raise ValueError("attempt is not accepted")
            del self._accepted_attempts[attempt_id]
            self._settled_attempts.add(attempt_id)
            if amount is None:
                self.unknown_cost_attempt_ids.append(attempt_id)
            else:
                self.known_cost += amount
            self.evaluations_failed += 1
            self.failure_breakdown[status.value] = self.failure_breakdown.get(status.value, 0) + 1
        else:
            EBBOLedger.settle(
                self, attempt_id, status=status, actual_cost=actual_cost, failure_type=failure_type
            )
        del self._pending_costs[attempt_id]

    def to_dict(self) -> dict[str, JsonValue]:
        value = EBBOLedger.to_dict(self)
        value["schema_version"] = ASYNC_LEDGER_VERSION
        value["max_concurrency"] = self.max_concurrency
        value["expected_cost_held"] = self.expected_cost_held
        value["outstanding"] = self.outstanding
        require_json_safe(value)
        return value

    def state(self) -> dict[str, JsonValue]:
        """Complete local checkpoint state, never an external ledger migration."""
        return {
            "schema_version": ASYNC_LEDGER_VERSION,
            "public": self.to_dict(),
            "reservations": dict(sorted(self._reservations.items())),
            "accepted_attempts": dict(sorted(self._accepted_attempts.items())),
            "pending_costs": dict(sorted(self._pending_costs.items())),
            "settled_attempt_ids": cast(list[JsonValue], sorted(self._settled_attempts)),
        }

    @classmethod
    def from_state(
        cls,
        state: dict[str, Any],
        *,
        max_oracle_calls: int,
        max_candidate_proposals: int,
        max_cost: float,
        cost_unit: str,
        max_concurrency: int,
    ) -> AsyncEBBOLedger:
        if (
            set(state)
            != {
                "schema_version",
                "public",
                "reservations",
                "accepted_attempts",
                "pending_costs",
                "settled_attempt_ids",
            }
            or state["schema_version"] != ASYNC_LEDGER_VERSION
        ):
            raise ValueError("async ledger state schema mismatch")
        public = state["public"]
        if not isinstance(public, dict):
            raise ValueError("async ledger public state must be an object")
        ledger = cls(
            max_oracle_calls,
            max_candidate_proposals,
            max_cost,
            cost_unit,
            max_concurrency=max_concurrency,
        )
        for key in ("reservations", "accepted_attempts", "pending_costs"):
            if not isinstance(state[key], dict):
                raise ValueError(f"invalid {key}")
            if any(not isinstance(item, str) or not item for item in state[key]):
                raise ValueError(f"invalid {key} ID")
        if any(
            not isinstance(value, str) or not value for value in state["accepted_attempts"].values()
        ):
            raise ValueError("invalid accepted request ID")
        settled = state["settled_attempt_ids"]
        if not isinstance(settled, list) or any(not isinstance(x, str) for x in settled):
            raise ValueError("invalid settled attempt IDs")
        ledger._reservations = {
            key: _optional_cost(value, "reserved cost")
            for key, value in state["reservations"].items()
        }
        ledger._accepted_attempts = dict(state["accepted_attempts"])
        ledger._pending_costs = {
            key: _optional_cost(value, "pending cost")
            for key, value in state["pending_costs"].items()
        }
        ledger._settled_attempts = set(settled)
        if len(ledger._settled_attempts) != len(settled):
            raise ValueError("duplicate settled attempt")
        evaluations = public.get("evaluations")
        cost = public.get("cost")
        tokens = public.get("tokens")
        if (
            not isinstance(evaluations, dict)
            or not isinstance(cost, dict)
            or not isinstance(tokens, dict)
        ):
            raise ValueError("invalid ledger counters")
        for attr, raw in (
            ("oracle_calls", public.get("oracle_calls")),
            ("candidate_proposals", public.get("candidate_proposals")),
            ("evaluations_succeeded", evaluations.get("succeeded")),
            ("evaluations_failed", evaluations.get("failed")),
            ("role_calls", public.get("llm_calls")),
            ("role_input_tokens", tokens.get("input")),
            ("role_output_tokens", tokens.get("output")),
        ):
            if type(raw) is not int or raw < 0:
                raise ValueError(f"invalid ledger {attr}")
            setattr(ledger, attr, raw)
        known_cost = cost.get("known_total")
        if type(known_cost) not in (int, float):
            raise ValueError("invalid known cost")
        known_cost = cast(float, known_cost)
        if not math.isfinite(known_cost) or known_cost < 0:
            raise ValueError("invalid known cost")
        ledger.known_cost = float(known_cost)
        breakdown = evaluations.get("failure_breakdown")
        unknown = cost.get("unknown_attempt_ids")
        if not isinstance(breakdown, dict) or not isinstance(unknown, list):
            raise ValueError("invalid failure or unknown cost state")
        if (
            any(
                not isinstance(key, str) or not key or type(value) is not int or value < 0
                for key, value in breakdown.items()
            )
            or sum(breakdown.values()) != ledger.evaluations_failed
        ):
            raise ValueError("invalid failure breakdown")
        if any(not isinstance(x, str) or not x for x in unknown) or len(set(unknown)) != len(
            unknown
        ):
            raise ValueError("invalid unknown cost attempt IDs")
        ledger.failure_breakdown = cast(dict[str, int], breakdown)
        ledger.unknown_cost_attempt_ids = cast(list[str], unknown)
        if ledger.to_dict() != public:
            raise ValueError("async ledger state does not match public accounting")
        if ledger.oracle_calls != len(ledger._accepted_attempts) + len(ledger._settled_attempts):
            raise ValueError("accepted oracle call count mismatch")
        if ledger.evaluations_total != len(ledger._settled_attempts):
            raise ValueError("settled evaluation count mismatch")
        if ledger.outstanding > max_concurrency or set(ledger._pending_costs) != set(
            ledger._accepted_attempts
        ):
            raise ValueError("pending ledger state mismatch")
        if ledger._settled_attempts & set(ledger._accepted_attempts):
            raise ValueError("settled attempt remains pending")
        if set(ledger._reservations) & set(ledger._accepted_attempts.values()):
            raise ValueError("reserved request is already accepted")
        if len(set(ledger._accepted_attempts.values())) != len(ledger._accepted_attempts):
            raise ValueError("two pending attempts refer to one request")
        return ledger
