"""Offline provider protocols and deterministic role-aware mock implementation."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from roco_ebbo.core import BudgetLedger, Candidate
from roco_ebbo.llm.prompts import RoCoRole

if TYPE_CHECKING:
    from roco_ebbo.evolution.operators import EoHOperator


@dataclass(frozen=True, slots=True)
class GeneratedHeuristic:
    """Structured provider response; Stage 2 never parses free-form model text."""

    description: str
    code: str
    request_index: int


@dataclass(frozen=True, slots=True)
class RoleRequest:
    """Complete input envelope for one role call."""

    role: RoCoRole
    action: Literal["initial_compare", "propose", "compare", "integrate"]
    generation: int
    round_index: int
    target_branch: Literal["explorer", "exploiter", "both"]
    prompt: str
    temperature: float
    candidates: tuple[Candidate, ...]
    feedback: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RoleResponse:
    """Structured role output; exactly one of candidate or feedback is expected."""

    request_index: int
    candidate: GeneratedHeuristic | None = None
    feedback: str | None = None
    metadata: dict[str, Any] | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Small generation contract shared by mock and future provider adapters."""

    def generate(
        self,
        operator: EoHOperator,
        generation: int,
        parents: Sequence[Candidate],
        ledger: BudgetLedger,
    ) -> GeneratedHeuristic:
        """Generate exactly one structured heuristic and account for the call."""


@runtime_checkable
class RoleLLMProvider(Protocol):
    """Additional provider capability required by the RoCo collaboration path."""

    def generate_role(self, request: RoleRequest, ledger: BudgetLedger) -> RoleResponse:
        """Execute one role contract and account for the call."""


class MockLLMProvider:
    """Seeded, fully offline provider with one distinct strategy per EoH operator."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._rng = random.Random(seed)
        self._request_index = 0

    def generate(
        self,
        operator: EoHOperator,
        generation: int,
        parents: Sequence[Candidate],
        ledger: BudgetLedger,
    ) -> GeneratedHeuristic:
        request_index = self._request_index
        start_hint = self._rng.randrange(10_000)
        code = _render_code(operator, start_hint)
        parent_ids = ",".join(parent.id for parent in parents) or "none"
        description = (
            f"Mock {operator.value} heuristic for generation {generation}; "
            f"parents={parent_ids}; seeded-start={start_hint}."
        )
        input_tokens = max(1, len(description.split()))
        output_tokens = max(1, len(code.split()))

        # The mock response is already a parsed candidate, so call, tokens, and
        # generated-candidate counters form one atomic logical operation.
        ledger.consume(
            llm_calls=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            generated_candidates=1,
            cost=0.0,
        )
        self._request_index += 1
        return GeneratedHeuristic(
            description=description,
            code=code,
            request_index=request_index,
        )

    def generate_role(self, request: RoleRequest, ledger: BudgetLedger) -> RoleResponse:
        """Return deterministic role-specific code or feedback without network access."""

        request_index = self._request_index
        input_text = " ".join(
            [
                request.prompt,
                request.action,
                *(candidate.to_json() for candidate in request.candidates),
                *request.feedback,
            ]
        )
        if request.role is RoCoRole.CRITIC:
            feedback = _mock_critic_feedback(request)
            ledger.consume(
                llm_calls=1,
                input_tokens=max(1, len(input_text.split())),
                output_tokens=max(1, len(feedback.split())),
                cost=0.0,
            )
            self._request_index += 1
            return RoleResponse(request_index=request_index, feedback=feedback)

        start_hint = self._rng.randrange(10_000)
        code = _render_role_code(request.role, start_hint)
        parent_ids = ",".join(candidate.id for candidate in request.candidates) or "none"
        description = (
            f"Mock {request.role.value} {request.action} for generation {request.generation}, "
            f"round {request.round_index}; parents={parent_ids}; seeded-start={start_hint}."
        )
        ledger.consume(
            llm_calls=1,
            input_tokens=max(1, len(input_text.split())),
            output_tokens=max(1, len((description + code).split())),
            generated_candidates=1,
            cost=0.0,
        )
        self._request_index += 1
        generated = GeneratedHeuristic(description, code, request_index)
        return RoleResponse(request_index=request_index, candidate=generated)


def _render_code(operator: EoHOperator, start_hint: int) -> str:
    return _render_strategy_code(operator.value, start_hint)


def _render_strategy_code(strategy: str, start_hint: int) -> str:
    if strategy == "E1":
        return f"""def heuristic(distance_matrix):
    n = len(distance_matrix)
    start = {start_hint} % n
    tour = [start]
    unvisited = list(range(n))
    unvisited.remove(start)
    while unvisited:
        current = tour[-1]
        best = unvisited[0]
        best_distance = distance_matrix[current][best]
        for node in unvisited:
            if distance_matrix[current][node] < best_distance:
                best = node
                best_distance = distance_matrix[current][node]
        tour.append(best)
        unvisited.remove(best)
    return tour
"""
    if strategy == "E2":
        return f"""def heuristic(distance_matrix):
    n = len(distance_matrix)
    start = {start_hint} % n
    tour = [start]
    unvisited = list(range(n))
    unvisited.remove(start)
    while unvisited:
        current = tour[-1]
        best = unvisited[0]
        best_distance = distance_matrix[current][best]
        for node in unvisited:
            if distance_matrix[current][node] > best_distance:
                best = node
                best_distance = distance_matrix[current][node]
        tour.append(best)
        unvisited.remove(best)
    return tour
"""
    if strategy == "M1":
        return f"""def heuristic(distance_matrix):
    n = len(distance_matrix)
    shift = {start_hint} % n
    tour = list(range(n))
    tour.reverse()
    return tour[shift:] + tour[:shift]
"""
    return f"""def heuristic(distance_matrix):
    n = len(distance_matrix)
    start = {start_hint} % n
    tour = [start]
    unvisited = list(range(n))
    unvisited.remove(start)
    while unvisited:
        best = unvisited[0]
        best_distance = distance_matrix[start][best]
        for node in unvisited:
            if distance_matrix[start][node] < best_distance:
                best = node
                best_distance = distance_matrix[start][node]
        tour.append(best)
        unvisited.remove(best)
    return tour
"""


def _mock_critic_feedback(request: RoleRequest) -> str:
    scored = [candidate for candidate in request.candidates if candidate.score is not None]
    if not scored:
        return (
            f"Mock critic {request.action} round {request.round_index}: no valid new score; "
            "retain the last valid candidate and repair validity before changing strategy."
        )
    ordered = sorted(scored, key=_scored_candidate_key)
    best_score = ordered[0].score
    assert best_score is not None
    return (
        f"Mock critic {request.action} round {request.round_index}: best={ordered[0].id} "
        f"score={best_score:.12f}; preserve its useful structure and test one bounded change."
    )


def _scored_candidate_key(candidate: Candidate) -> tuple[float, str]:
    score = candidate.score
    assert score is not None
    return score, candidate.id


def _render_role_code(role: RoCoRole, start_hint: int) -> str:
    if role is RoCoRole.EXPLORER:
        return _render_strategy_code("E2", start_hint)
    if role is RoCoRole.EXPLOITER:
        return _render_strategy_code("E1", start_hint)
    return _render_strategy_code("M2", start_hint)
