"""Deterministic, network-free Mock provider for the MKP engineering dry-run."""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import TYPE_CHECKING

from roco_ebbo.core import BudgetLedger, Candidate
from roco_ebbo.llm.prompts import RoCoRole
from roco_ebbo.llm.provider import GeneratedHeuristic, RoleRequest, RoleResponse

if TYPE_CHECKING:
    from roco_ebbo.evolution.operators import EoHOperator

MKP_MOCK_PROVIDER_VERSION = "mkp-mock-provider-v1"


class MKPMockLLMProvider:
    """Seeded Mock that emits only the frozen MKP candidate signature."""

    def __init__(self, seed: int, base_prompt: str) -> None:
        if not base_prompt.strip():
            raise ValueError("MKP Mock base prompt must be non-empty")
        self.seed = seed
        self.base_prompt = base_prompt
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
        code = _render_strategy_code(operator.value, start_hint)
        parent_ids = ",".join(parent.id for parent in parents) or "none"
        description = (
            f"Offline MKP Mock {operator.value} for generation {generation}; "
            f"parents={parent_ids}; seeded-start={start_hint}."
        )
        ledger.consume(
            llm_calls=1,
            input_tokens=max(1, len((self.base_prompt + " " + description).split())),
            output_tokens=max(1, len(code.split())),
            generated_candidates=1,
            cost=0.0,
        )
        self._request_index += 1
        return GeneratedHeuristic(description, code, request_index)

    def generate_role(self, request: RoleRequest, ledger: BudgetLedger) -> RoleResponse:
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
            feedback = _critic_feedback(request)
            ledger.consume(
                llm_calls=1,
                input_tokens=max(1, len(input_text.split())),
                output_tokens=max(1, len(feedback.split())),
                cost=0.0,
            )
            self._request_index += 1
            return RoleResponse(request_index=request_index, feedback=feedback)

        start_hint = self._rng.randrange(10_000)
        strategy = {
            RoCoRole.EXPLORER: "E2",
            RoCoRole.EXPLOITER: "E1",
            RoCoRole.INTEGRATOR: "M1",
        }[request.role]
        code = _render_strategy_code(strategy, start_hint)
        parent_ids = ",".join(candidate.id for candidate in request.candidates) or "none"
        description = (
            f"Offline MKP Mock {request.role.value} {request.action} for generation "
            f"{request.generation}, round {request.round_index}; parents={parent_ids}; "
            f"seeded-start={start_hint}."
        )
        ledger.consume(
            llm_calls=1,
            input_tokens=max(1, len(input_text.split())),
            output_tokens=max(1, len((description + code).split())),
            generated_candidates=1,
            cost=0.0,
        )
        self._request_index += 1
        return RoleResponse(
            request_index=request_index,
            candidate=GeneratedHeuristic(description, code, request_index),
        )


def _critic_feedback(request: RoleRequest) -> str:
    scored = [candidate for candidate in request.candidates if candidate.score is not None]
    if not scored:
        return (
            f"Offline MKP Mock critic {request.action} round {request.round_index}: "
            "no valid candidate score; retain the preceding feasible assignment."
        )
    best = min(scored, key=_scored_candidate_key)
    best_score = best.score
    assert best_score is not None
    return (
        f"Offline MKP Mock critic {request.action} round {request.round_index}: "
        f"best={best.id} score={best_score}; keep capacity feasibility and one-bag-per-item."
    )


def _scored_candidate_key(candidate: Candidate) -> tuple[float, str]:
    score = candidate.score
    assert score is not None
    return score, candidate.id


def _render_strategy_code(strategy: str, start_hint: int) -> str:
    if strategy == "E1":
        order_setup = f"""    start = {start_hint} % len(weights)
    order = list(range(len(weights)))
    order = order[start:] + order[:start]
"""
        comparison = "weights[item] <= remaining[bag]"
    elif strategy == "E2":
        order_setup = f"""    start = {start_hint} % len(weights)
    order = list(range(len(weights)))
    order.reverse()
    order = order[start:] + order[:start]
"""
        comparison = "weights[item] <= remaining[bag]"
    elif strategy == "M1":
        order_setup = """    available = list(range(len(weights)))
    order = []
    while available:
        best = available[0]
        for item in available:
            if profits[item] > profits[best]:
                best = item
        order.append(best)
        available.remove(best)
"""
        comparison = "weights[item] <= remaining[bag]"
    else:
        order_setup = """    available = list(range(len(weights)))
    order = []
    while available:
        best = available[0]
        for item in available:
            if weights[item] < weights[best]:
                best = item
        order.append(best)
        available.remove(best)
"""
        comparison = "weights[item] <= remaining[bag]"
    return f"""def heuristic(capacities, weights, profits):
    bags = []
    for bag in range(len(capacities)):
        bags.append([])
    remaining = list(capacities)
{order_setup}    for item in order:
        for bag in range(len(capacities)):
            if {comparison}:
                bags[bag].append(item)
                remaining[bag] = remaining[bag] - weights[item]
                break
    return bags
"""
