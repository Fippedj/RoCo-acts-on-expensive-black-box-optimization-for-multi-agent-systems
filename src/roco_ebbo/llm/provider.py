"""Offline provider protocol and deterministic Stage 2 mock implementation."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from roco_ebbo.core import BudgetLedger, Candidate

if TYPE_CHECKING:
    from roco_ebbo.evolution.operators import EoHOperator


@dataclass(frozen=True, slots=True)
class GeneratedHeuristic:
    """Structured provider response; Stage 2 never parses free-form model text."""

    description: str
    code: str
    request_index: int


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


def _render_code(operator: EoHOperator, start_hint: int) -> str:
    if operator.value == "E1":
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
    if operator.value == "E2":
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
    if operator.value == "M1":
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
