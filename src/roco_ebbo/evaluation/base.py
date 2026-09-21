"""Structural evaluator contract shared by offline benchmark runtimes."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar


class CandidateEvaluation(Protocol):
    """Minimum result surface consumed by the existing evolution runtime."""

    @property
    def score(self) -> float | None: ...

    @property
    def valid(self) -> bool: ...

    @property
    def runtime_seconds(self) -> float: ...

    @property
    def error_type(self) -> str | None: ...

    @property
    def error_message(self) -> str | None: ...

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe audit record for the candidate evaluation."""


EvaluationInputT = TypeVar("EvaluationInputT", contravariant=True)


class CodeEvaluator(Protocol[EvaluationInputT]):
    """Evaluate trusted local/mock candidate code against one explicit input."""

    def evaluate(self, code: str, evaluation_input: EvaluationInputT, /) -> CandidateEvaluation:
        """Return a structured result without raising for candidate failures."""
