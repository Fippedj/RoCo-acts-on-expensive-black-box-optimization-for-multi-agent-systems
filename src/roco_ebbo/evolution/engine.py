"""Deterministic serial EoH engine with an optional Stage 3 RoCo branch."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any

from roco_ebbo.benchmarks import DistanceMatrix
from roco_ebbo.core import BudgetExceededError, BudgetLedger, Candidate
from roco_ebbo.evaluation import TSPCodeEvaluator
from roco_ebbo.evolution.collaboration import CollaborationTrace, RoCoCollaborator
from roco_ebbo.evolution.operators import EOH_OPERATORS, EoHOperator
from roco_ebbo.llm import LLMProvider


@dataclass(slots=True)
class Population:
    """A scored population with deterministic Top-N selection."""

    candidates: list[Candidate]
    size: int
    minimize: bool = True

    def __post_init__(self) -> None:
        if self.size < 2:
            raise ValueError("population size must be at least 2")
        if len(self.candidates) > self.size:
            raise ValueError("population contains more candidates than its configured size")

    @classmethod
    def select_top_n(
        cls,
        candidates: list[Candidate],
        size: int,
        *,
        minimize: bool = True,
    ) -> Population:
        valid = [
            candidate
            for candidate in candidates
            if candidate.score is not None and math.isfinite(candidate.score)
        ]

        def ranking_key(candidate: Candidate) -> tuple[float, str]:
            score = candidate.score
            assert score is not None
            return (score if minimize else -score, candidate.id)

        ranked = sorted(valid, key=ranking_key)
        return cls(candidates=ranked[:size], size=size, minimize=minimize)

    @property
    def best(self) -> Candidate:
        if not self.candidates:
            raise ValueError("population is empty")
        return self.candidates[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "minimize": self.minimize,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "minimize": self.minimize,
            "candidates": [candidate.to_snapshot() for candidate in self.candidates],
        }

    @classmethod
    def from_snapshot(cls, value: dict[str, Any]) -> Population:
        if set(value) != {"size", "minimize", "candidates"}:
            raise ValueError("population snapshot keys do not match its schema")
        if type(value["size"]) is not int or value["size"] < 2:
            raise ValueError("population snapshot size must be an integer of at least 2")
        if type(value["minimize"]) is not bool or not isinstance(value["candidates"], list):
            raise ValueError("population snapshot has invalid field types")
        return cls(
            candidates=[Candidate.from_snapshot(item) for item in value["candidates"]],
            size=value["size"],
            minimize=value["minimize"],
        )


@dataclass(frozen=True, slots=True)
class EoHRunResult:
    population: Population
    all_candidates: tuple[Candidate, ...]
    initial_scores: tuple[float, ...]
    generations_completed: int
    stopped_on_budget: bool
    collaboration_traces: tuple[CollaborationTrace, ...] = ()


class EoHEngine:
    """Generate one candidate per configured E1/E2/M1/M2 operation and select Top-N."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        evaluator: TSPCodeEvaluator,
        distance_matrix: DistanceMatrix,
        ledger: BudgetLedger,
        population_size: int,
        generations: int,
        candidates_per_operator: int = 1,
        minimize: bool = True,
        collaborator: RoCoCollaborator | None = None,
    ) -> None:
        if population_size < 2:
            raise ValueError("population_size must be at least 2")
        if generations < 1:
            raise ValueError("generations must be at least 1")
        if candidates_per_operator < 1:
            raise ValueError("candidates_per_operator must be at least 1")
        self.provider = provider
        self.evaluator = evaluator
        self.distance_matrix = distance_matrix
        self.ledger = ledger
        self.population_size = population_size
        self.generations = generations
        self.candidates_per_operator = candidates_per_operator
        self.minimize = minimize
        self.collaborator = collaborator
        self._started = 0.0
        self._all_candidates: list[Candidate] = []
        self._collaboration_traces: list[CollaborationTrace] = []

    def run(self) -> EoHRunResult:
        self._started = time.perf_counter()
        stopped_on_budget = False
        generations_completed = 0
        population: Population | None = None
        initial_scores: tuple[float, ...] = ()
        try:
            initial_candidates: list[Candidate] = []
            initialization_attempts = 0
            initialization_attempt_limit = self.population_size * len(EOH_OPERATORS)
            while len(initial_candidates) < self.population_size:
                if initialization_attempts >= initialization_attempt_limit:
                    raise RuntimeError(
                        "could not initialize a full valid population within the attempt limit"
                    )
                operator = EOH_OPERATORS[initialization_attempts % len(EOH_OPERATORS)]
                candidate = self._produce(operator, generation=0, parents=())
                initialization_attempts += 1
                if candidate.score is not None:
                    initial_candidates.append(candidate)
            population = Population.select_top_n(
                initial_candidates,
                self.population_size,
                minimize=self.minimize,
            )
            initial_scores = tuple(
                float(candidate.score)
                for candidate in population.candidates
                if candidate.score is not None
            )

            for generation in range(1, self.generations + 1):
                offspring: list[Candidate] = []
                for operator in EOH_OPERATORS:
                    parents = self._parents_for(operator, population)
                    for _ in range(self.candidates_per_operator):
                        offspring.append(self._produce(operator, generation, parents))
                collaboration_stopped = False
                if self.collaborator is not None:
                    outcome = self.collaborator.run(population.candidates, generation)
                    offspring.extend(outcome.candidates)
                    self._all_candidates.extend(outcome.candidates)
                    self._collaboration_traces.append(outcome.trace)
                    collaboration_stopped = outcome.stopped_on_budget
                population = Population.select_top_n(
                    [*population.candidates, *offspring],
                    self.population_size,
                    minimize=self.minimize,
                )
                if self._collaboration_traces:
                    self._collaboration_traces[-1].selected_candidate_ids = tuple(
                        candidate.id for candidate in population.candidates
                    )
                generations_completed = generation
                if collaboration_stopped:
                    stopped_on_budget = True
                    break
        except BudgetExceededError:
            stopped_on_budget = True
            if population is None:
                raise RuntimeError(
                    "budget was exhausted before population initialization"
                ) from None
        finally:
            self._refresh_wall_time()

        return EoHRunResult(
            population=population,
            all_candidates=tuple(self._all_candidates),
            initial_scores=initial_scores,
            generations_completed=generations_completed,
            stopped_on_budget=stopped_on_budget,
            collaboration_traces=tuple(self._collaboration_traces),
        )

    def _produce(
        self,
        operator: EoHOperator,
        generation: int,
        parents: tuple[Candidate, ...],
    ) -> Candidate:
        self._refresh_wall_time()
        self.ledger.ensure_can_start()
        generated = self.provider.generate(operator, generation, parents, self.ledger)
        candidate_id = _candidate_id(
            operator=operator,
            generation=generation,
            parents=parents,
            description=generated.description,
            code=generated.code,
            request_index=generated.request_index,
        )
        candidate = Candidate(
            id=candidate_id,
            description=generated.description,
            code=generated.code,
            parents=tuple(parent.id for parent in parents),
            operator=operator.value,
            generation=generation,
            metadata={"mock_request_index": generated.request_index},
        )
        self._all_candidates.append(candidate)

        self._refresh_wall_time()
        self.ledger.ensure_can_start()
        evaluation = self.evaluator.evaluate(candidate.code, self.distance_matrix)
        candidate.metadata["evaluation"] = evaluation.to_dict()
        self._refresh_wall_time()
        if evaluation.valid:
            self.ledger.consume(valid_evals=1)
            candidate.score = evaluation.score
        return candidate

    def _parents_for(
        self,
        operator: EoHOperator,
        population: Population,
    ) -> tuple[Candidate, ...]:
        if operator is EoHOperator.E1:
            return ()
        if operator is EoHOperator.E2:
            return tuple(population.candidates[:2])
        if operator is EoHOperator.M1:
            return (population.candidates[0],)
        parent_index = 1 if len(population.candidates) > 1 else 0
        return (population.candidates[parent_index],)

    def _refresh_wall_time(self) -> None:
        if self._started:
            self.ledger.observe_wall_time(time.perf_counter() - self._started)


def _candidate_id(
    *,
    operator: EoHOperator,
    generation: int,
    parents: tuple[Candidate, ...],
    description: str,
    code: str,
    request_index: int,
) -> str:
    payload = json.dumps(
        {
            "operator": operator.value,
            "generation": generation,
            "parents": [parent.id for parent in parents],
            "description": description,
            "code": code,
            "request_index": request_index,
        },
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()[:16]
    return f"g{generation}-{operator.value.lower()}-{digest}"
