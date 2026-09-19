"""Typed, JSON-serializable models shared by the Stage 2 baseline."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class BudgetExceededError(RuntimeError):
    """Raised before starting work that would violate a configured hard budget."""


@dataclass(slots=True)
class Candidate:
    """An executable heuristic candidate and its deterministic lineage."""

    id: str
    description: str
    code: str
    parents: tuple[str, ...]
    operator: str
    generation: int
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "code": self.code,
            "parents": list(self.parents),
            "operator": self.operator,
            "generation": self.generation,
            "score": self.score,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, sort_keys=True)


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Structured outcome from validating and executing one candidate."""

    score: float | None
    valid: bool
    runtime_seconds: float
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "valid": self.valid,
            "runtime_seconds": self.runtime_seconds,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, sort_keys=True)


@dataclass(slots=True)
class BudgetLedger:
    """Run-scoped, monotonic budget counters with fail-closed hard limits.

    A call that exactly reaches a limit is allowed to finish. Every subsequent
    operation is rejected because at least one configured hard limit is then
    reached. Counters from one logical operation are committed atomically.
    """

    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    generated_candidates: int = 0
    valid_evals: int = 0
    cost: float = 0.0
    wall_time: float = 0.0
    cost_currency: str = "USD"
    max_llm_calls: int | None = None
    max_tokens: int | None = None
    max_generated_candidates: int | None = None
    max_valid_evals: int | None = None
    max_cost: float | None = None
    max_wall_time: float | None = None

    def __post_init__(self) -> None:
        integer_values: dict[str, int] = {
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "generated_candidates": self.generated_candidates,
            "valid_evals": self.valid_evals,
        }
        integer_limits: dict[str, int | None] = {
            "max_llm_calls": self.max_llm_calls,
            "max_tokens": self.max_tokens,
            "max_generated_candidates": self.max_generated_candidates,
            "max_valid_evals": self.max_valid_evals,
        }
        for name, integer_value in integer_values.items():
            if integer_value < 0:
                raise ValueError(f"{name} must be non-negative")
        for name, limit_value in integer_limits.items():
            if limit_value is not None and limit_value < 0:
                raise ValueError(f"{name} must be non-negative or null")
        float_values: dict[str, float | None] = {
            "cost": self.cost,
            "wall_time": self.wall_time,
            "max_cost": self.max_cost,
            "max_wall_time": self.max_wall_time,
        }
        for name, float_value in float_values.items():
            if float_value is not None and (not math.isfinite(float_value) or float_value < 0):
                raise ValueError(f"{name} must be finite and non-negative")

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def reached_limits(self) -> tuple[str, ...]:
        pairs: tuple[tuple[str, float, float | None], ...] = (
            ("llm_calls", self.llm_calls, self.max_llm_calls),
            ("tokens", self.tokens, self.max_tokens),
            (
                "generated_candidates",
                self.generated_candidates,
                self.max_generated_candidates,
            ),
            ("valid_evals", self.valid_evals, self.max_valid_evals),
            ("cost", self.cost, self.max_cost),
            ("wall_time", self.wall_time, self.max_wall_time),
        )
        return tuple(
            name for name, current, limit in pairs if limit is not None and current >= limit
        )

    @property
    def budget_reached(self) -> bool:
        return bool(self.reached_limits)

    def ensure_can_start(
        self,
        *,
        llm_calls: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        generated_candidates: int = 0,
        valid_evals: int = 0,
        cost: float = 0.0,
    ) -> None:
        """Reject work after a limit is reached or if increments would exceed one."""

        increments = {
            "llm_calls": llm_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "generated_candidates": generated_candidates,
            "valid_evals": valid_evals,
            "cost": cost,
        }
        if any(value < 0 for value in increments.values()):
            raise ValueError("budget increments must be non-negative")
        if reached := self.reached_limits:
            raise BudgetExceededError(f"hard budget already reached: {', '.join(reached)}")

        projected: tuple[tuple[str, float, float | None], ...] = (
            ("llm_calls", self.llm_calls + llm_calls, self.max_llm_calls),
            ("tokens", self.tokens + input_tokens + output_tokens, self.max_tokens),
            (
                "generated_candidates",
                self.generated_candidates + generated_candidates,
                self.max_generated_candidates,
            ),
            ("valid_evals", self.valid_evals + valid_evals, self.max_valid_evals),
            ("cost", self.cost + cost, self.max_cost),
        )
        exceeded = [name for name, value, limit in projected if limit is not None and value > limit]
        if exceeded:
            raise BudgetExceededError(f"operation would exceed hard budget: {', '.join(exceeded)}")

    def consume(
        self,
        *,
        llm_calls: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        generated_candidates: int = 0,
        valid_evals: int = 0,
        cost: float = 0.0,
    ) -> None:
        """Atomically validate and commit counters for one completed operation."""

        self.ensure_can_start(
            llm_calls=llm_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            generated_candidates=generated_candidates,
            valid_evals=valid_evals,
            cost=cost,
        )
        self.llm_calls += llm_calls
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.generated_candidates += generated_candidates
        self.valid_evals += valid_evals
        self.cost += cost

    def observe_wall_time(self, elapsed_seconds: float) -> None:
        """Record measured elapsed time; callers check limits before starting work."""

        if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError("wall time must be finite and non-negative")
        self.wall_time = max(self.wall_time, elapsed_seconds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tokens": self.tokens,
            "generated_candidates": self.generated_candidates,
            "valid_evals": self.valid_evals,
            "cost": self.cost,
            "cost_currency": self.cost_currency,
            "wall_time": self.wall_time,
            "limits": {
                "max_llm_calls": self.max_llm_calls,
                "max_tokens": self.max_tokens,
                "max_generated_candidates": self.max_generated_candidates,
                "max_valid_evals": self.max_valid_evals,
                "max_cost": self.max_cost,
                "max_wall_time": self.max_wall_time,
            },
            "reached_limits": list(self.reached_limits),
            "budget_reached": self.budget_reached,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, sort_keys=True)


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Portable record needed to inspect or replay a Stage 2 run."""

    seed: int
    git_sha: str | None
    config_snapshot: dict[str, Any]
    environment_information: dict[str, Any]
    budget_snapshot: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "git_sha": self.git_sha,
            "config_snapshot": self.config_snapshot,
            "environment_information": self.environment_information,
            "budget_snapshot": self.budget_snapshot,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, indent=2, sort_keys=True)

    def write_json(self, path: str | Path) -> None:
        output_path = Path(path)
        output_path.write_text(f"{self.to_json()}\n", encoding="utf-8")
