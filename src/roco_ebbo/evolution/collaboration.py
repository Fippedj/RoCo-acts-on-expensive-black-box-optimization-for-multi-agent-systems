"""Stage 3 RoCo four-role, generation-local collaboration state machine."""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from typing import Any, Literal

from roco_ebbo.benchmarks import DistanceMatrix
from roco_ebbo.core import BudgetExceededError, BudgetLedger, Candidate
from roco_ebbo.evaluation import TSPCodeEvaluator
from roco_ebbo.llm import (
    PROMPT_VERSION,
    ROLE_TEMPERATURES,
    GeneratedHeuristic,
    RoCoRole,
    RoleLLMProvider,
    RoleRequest,
    RoleResponse,
    prompt_for,
)

TraceStatus = Literal[
    "success",
    "invalid_output",
    "invalid_candidate",
    "provider_error",
    "budget_exhausted",
]


@dataclass(frozen=True, slots=True)
class CollaborationEvent:
    """One auditable role transition with immutable inputs and budget deltas."""

    event_id: str
    role: RoCoRole
    action: str
    round_index: int
    target_branch: str
    temperature: float
    prompt_version: str
    input_candidates: tuple[dict[str, Any], ...]
    input_feedback: tuple[str, ...]
    output_candidate: dict[str, Any] | None
    output_feedback: str | None
    evaluation: dict[str, Any] | None
    budget_before: dict[str, int | float]
    budget_after: dict[str, int | float]
    status: TraceStatus
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "role": self.role.value,
            "action": self.action,
            "round": self.round_index,
            "target_branch": self.target_branch,
            "temperature": self.temperature,
            "prompt_version": self.prompt_version,
            "input_candidates": list(self.input_candidates),
            "input_feedback": list(self.input_feedback),
            "output_candidate": self.output_candidate,
            "output_feedback": self.output_feedback,
            "evaluation": self.evaluation,
            "budget_before": self.budget_before,
            "budget_after": self.budget_after,
            "budget_delta": {
                name: self.budget_after[name] - value for name, value in self.budget_before.items()
            },
            "status": self.status,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass(slots=True)
class CollaborationTrace:
    """Serializable trace for one generation; deliberately not long-term memory."""

    generation: int
    elite_pair: tuple[dict[str, Any], dict[str, Any]]
    elite_pair_ranks: tuple[int, int]
    sampling_power: float
    sampling_seed: int
    sampling_weights: tuple[float, ...]
    rounds_requested: int
    events: list[CollaborationEvent] = field(default_factory=list)
    rounds_completed: int = 0
    stopped_on_budget: bool = False
    selected_candidate_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "roco-collaboration-trace-v1",
            "scope": "generation-local",
            "generation": self.generation,
            "elite_pair": list(self.elite_pair),
            "elite_pair_ranks": list(self.elite_pair_ranks),
            "sampling_power": self.sampling_power,
            "sampling_seed": self.sampling_seed,
            "sampling_weights": list(self.sampling_weights),
            "rounds_requested": self.rounds_requested,
            "rounds_completed": self.rounds_completed,
            "stopped_on_budget": self.stopped_on_budget,
            "selected_candidate_ids": list(self.selected_candidate_ids),
            "events": [event.to_dict() for event in self.events],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), allow_nan=False, sort_keys=True)


@dataclass(frozen=True, slots=True)
class CollaborationOutcome:
    candidates: tuple[Candidate, ...]
    trace: CollaborationTrace
    stopped_on_budget: bool


class RoCoCollaborator:
    """Run initial critique, ``T`` refinement rounds, and final integration."""

    def __init__(
        self,
        *,
        provider: RoleLLMProvider,
        evaluator: TSPCodeEvaluator,
        distance_matrix: DistanceMatrix,
        ledger: BudgetLedger,
        rounds: int = 3,
        elite_sampling_power: float = 3.0,
        seed: int = 0,
        temperatures: dict[RoCoRole, float] | None = None,
        minimize: bool = True,
    ) -> None:
        if rounds < 1:
            raise ValueError("collaboration rounds must be at least 1")
        if not math.isfinite(elite_sampling_power) or elite_sampling_power <= 0:
            raise ValueError("elite_sampling_power must be finite and greater than zero")
        if not minimize:
            raise ValueError("Stage 3 RoCo collaboration supports only minimize=True")
        resolved_temperatures = {**ROLE_TEMPERATURES, **(temperatures or {})}
        if any(not math.isfinite(value) or value < 0 for value in resolved_temperatures.values()):
            raise ValueError("role temperatures must be finite and non-negative")
        self.provider = provider
        self.evaluator = evaluator
        self.distance_matrix = distance_matrix
        self.ledger = ledger
        self.rounds = rounds
        self.elite_sampling_power = elite_sampling_power
        self.temperatures = resolved_temperatures
        self.minimize = minimize
        self.sampling_seed = seed
        self._rng = random.Random(seed)
        self._event_sequence = 0

    def run(self, population: list[Candidate], generation: int) -> CollaborationOutcome:
        """Execute a complete collaboration while converting role failures into trace data."""

        if len(population) < 2:
            raise ValueError("RoCo collaboration requires at least two evaluated candidates")
        ranked = sorted(population, key=self._ranking_key)
        first_rank, second_rank, sampling_weights = self._sample_elite_pair(len(ranked))
        first = ranked[first_rank]
        second = ranked[second_rank]
        trace = CollaborationTrace(
            generation=generation,
            elite_pair=(first.to_dict(), second.to_dict()),
            elite_pair_ranks=(first_rank, second_rank),
            sampling_power=self.elite_sampling_power,
            sampling_seed=self.sampling_seed,
            sampling_weights=sampling_weights,
            rounds_requested=self.rounds,
        )
        produced: list[Candidate] = []

        initial_feedback, exhausted = self._critic(
            generation=generation,
            round_index=0,
            action="initial_compare",
            candidates=(first, second),
            feedback=(),
            target_branch="both",
            trace=trace,
        )
        if exhausted:
            return self._finish(produced, trace, stopped=True)

        better, worse = sorted((first, second), key=self._ranking_key)
        explorer_current = worse
        exploiter_current = better
        explorer_feedback = initial_feedback or "No valid initial Critic feedback was available."
        exploiter_feedback = explorer_feedback

        for round_index in range(1, self.rounds + 1):
            explorer_new, exhausted = self._propose(
                role=RoCoRole.EXPLORER,
                generation=generation,
                round_index=round_index,
                current=explorer_current,
                feedback=(explorer_feedback,),
                target_branch="explorer",
                trace=trace,
            )
            if explorer_new is not None:
                produced.append(explorer_new)
            if exhausted:
                return self._finish(produced, trace, stopped=True)

            exploiter_new, exhausted = self._propose(
                role=RoCoRole.EXPLOITER,
                generation=generation,
                round_index=round_index,
                current=exploiter_current,
                feedback=(exploiter_feedback,),
                target_branch="exploiter",
                trace=trace,
            )
            if exploiter_new is not None:
                produced.append(exploiter_new)
            if exhausted:
                return self._finish(produced, trace, stopped=True)

            explorer_compared = explorer_new or explorer_current
            explorer_feedback_new, exhausted = self._critic(
                generation=generation,
                round_index=round_index,
                action="compare",
                candidates=(explorer_current, explorer_compared),
                feedback=(explorer_feedback,),
                target_branch="explorer",
                trace=trace,
            )
            if exhausted:
                return self._finish(produced, trace, stopped=True)
            exploiter_compared = exploiter_new or exploiter_current
            exploiter_feedback_new, exhausted = self._critic(
                generation=generation,
                round_index=round_index,
                action="compare",
                candidates=(exploiter_current, exploiter_compared),
                feedback=(exploiter_feedback,),
                target_branch="exploiter",
                trace=trace,
            )
            if exhausted:
                return self._finish(produced, trace, stopped=True)

            if explorer_new is not None and explorer_new.score is not None:
                explorer_current = explorer_new
            if exploiter_new is not None and exploiter_new.score is not None:
                exploiter_current = exploiter_new
            explorer_feedback = explorer_feedback_new or explorer_feedback
            exploiter_feedback = exploiter_feedback_new or exploiter_feedback
            trace.rounds_completed = round_index

        integrated, exhausted = self._propose(
            role=RoCoRole.INTEGRATOR,
            generation=generation,
            round_index=self.rounds,
            current=(explorer_current, exploiter_current),
            feedback=(explorer_feedback, exploiter_feedback),
            target_branch="both",
            trace=trace,
        )
        if integrated is not None:
            produced.append(integrated)
        return self._finish(produced, trace, stopped=exhausted)

    def _critic(
        self,
        *,
        generation: int,
        round_index: int,
        action: Literal["initial_compare", "compare"],
        candidates: tuple[Candidate, ...],
        feedback: tuple[str, ...],
        target_branch: Literal["explorer", "exploiter", "both"],
        trace: CollaborationTrace,
    ) -> tuple[str | None, bool]:
        request = self._request(
            RoCoRole.CRITIC,
            action,
            generation,
            round_index,
            candidates,
            feedback,
            target_branch,
        )
        before = _budget_counters(self.ledger)
        try:
            response = self.provider.generate_role(request, self.ledger)
        except BudgetExceededError as exc:
            self._failure_event(trace, request, before, "budget_exhausted", exc)
            return None, True
        except Exception as exc:  # provider failures are data, not run failures
            self._failure_event(trace, request, before, "provider_error", exc)
            return None, False
        if not _valid_critic_response(response):
            self._invalid_output_event(trace, request, response, before)
            return None, False
        assert response.feedback is not None
        self._success_event(trace, request, response, before)
        return response.feedback, False

    def _propose(
        self,
        *,
        role: RoCoRole,
        generation: int,
        round_index: int,
        current: Candidate | tuple[Candidate, Candidate],
        feedback: tuple[str, ...],
        target_branch: Literal["explorer", "exploiter", "both"],
        trace: CollaborationTrace,
    ) -> tuple[Candidate | None, bool]:
        candidates = current if isinstance(current, tuple) else (current,)
        action: Literal["propose", "integrate"] = (
            "integrate" if role is RoCoRole.INTEGRATOR else "propose"
        )
        request = self._request(
            role,
            action,
            generation,
            round_index,
            candidates,
            feedback,
            target_branch,
        )
        before = _budget_counters(self.ledger)
        try:
            response = self.provider.generate_role(request, self.ledger)
        except BudgetExceededError as exc:
            self._failure_event(trace, request, before, "budget_exhausted", exc)
            return None, True
        except Exception as exc:  # provider failures are data, not run failures
            self._failure_event(trace, request, before, "provider_error", exc)
            return None, False
        if not _valid_candidate_response(response):
            self._invalid_output_event(trace, request, response, before)
            return None, False

        assert response.candidate is not None
        candidate = Candidate(
            id=_role_candidate_id(request, response),
            description=response.candidate.description,
            code=response.candidate.code,
            parents=tuple(parent.id for parent in candidates),
            operator=role.value,
            generation=generation,
            metadata={
                "role": role.value,
                "round": round_index,
                "prompt_version": PROMPT_VERSION,
                "temperature": self.temperatures[role],
                "mock_request_index": response.request_index,
            },
        )
        try:
            self.ledger.ensure_can_start()
        except BudgetExceededError as exc:
            self._candidate_event(
                trace, request, response, candidate, before, None, "budget_exhausted", exc
            )
            return candidate, True

        try:
            evaluation = self.evaluator.evaluate(candidate.code, self.distance_matrix)
        except Exception as exc:  # evaluator implementation failures are also contained
            self._candidate_event(
                trace, request, response, candidate, before, None, "invalid_candidate", exc
            )
            return candidate, False
        candidate.metadata["evaluation"] = evaluation.to_dict()
        if evaluation.valid:
            try:
                self.ledger.consume(valid_evals=1)
            except BudgetExceededError as exc:
                self._candidate_event(
                    trace,
                    request,
                    response,
                    candidate,
                    before,
                    evaluation.to_dict(),
                    "budget_exhausted",
                    exc,
                )
                return candidate, True
            candidate.score = evaluation.score
            self._candidate_event(
                trace, request, response, candidate, before, evaluation.to_dict(), "success"
            )
        else:
            error = ValueError(evaluation.error_message or "candidate evaluation failed")
            self._candidate_event(
                trace,
                request,
                response,
                candidate,
                before,
                evaluation.to_dict(),
                "invalid_candidate",
                error,
                error_type=evaluation.error_type,
            )
        return candidate, False

    def _request(
        self,
        role: RoCoRole,
        action: Literal["initial_compare", "propose", "compare", "integrate"],
        generation: int,
        round_index: int,
        candidates: tuple[Candidate, ...],
        feedback: tuple[str, ...],
        target_branch: Literal["explorer", "exploiter", "both"],
    ) -> RoleRequest:
        return RoleRequest(
            role=role,
            action=action,
            generation=generation,
            round_index=round_index,
            target_branch=target_branch,
            prompt=prompt_for(role),
            temperature=self.temperatures[role],
            candidates=candidates,
            feedback=feedback,
        )

    def _sample_elite_pair(self, population_size: int) -> tuple[int, int, tuple[float, ...]]:
        weights = [
            1.0 / ((rank + 1) ** self.elite_sampling_power) for rank in range(population_size)
        ]
        first = self._rng.choices(range(population_size), weights=weights, k=1)[0]
        if first == 0:
            second = 1
        elif first == population_size - 1:
            second = population_size - 2
        else:
            second = first + self._rng.choice((-1, 1))
        return first, second, tuple(weights)

    def _ranking_key(self, candidate: Candidate) -> tuple[float, str]:
        if candidate.score is None or not math.isfinite(candidate.score):
            return (math.inf, candidate.id)
        return (candidate.score if self.minimize else -candidate.score, candidate.id)

    def _finish(
        self,
        candidates: list[Candidate],
        trace: CollaborationTrace,
        *,
        stopped: bool,
    ) -> CollaborationOutcome:
        trace.stopped_on_budget = stopped
        return CollaborationOutcome(tuple(candidates), trace, stopped)

    def _success_event(
        self,
        trace: CollaborationTrace,
        request: RoleRequest,
        response: RoleResponse,
        before: dict[str, int | float],
    ) -> None:
        self._append_event(
            trace,
            request,
            before,
            response=response,
            output_feedback=response.feedback,
            status="success",
        )

    def _invalid_output_event(
        self,
        trace: CollaborationTrace,
        request: RoleRequest,
        response: object,
        before: dict[str, int | float],
    ) -> None:
        self._append_event(
            trace,
            request,
            before,
            response=response if isinstance(response, RoleResponse) else None,
            status="invalid_output",
            error_type="role_output_error",
            error_message="role response did not satisfy its structured output contract",
        )

    def _failure_event(
        self,
        trace: CollaborationTrace,
        request: RoleRequest,
        before: dict[str, int | float],
        status: Literal["provider_error", "budget_exhausted"],
        error: Exception,
    ) -> None:
        self._append_event(
            trace,
            request,
            before,
            status=status,
            error_type=type(error).__name__,
            error_message=str(error),
        )

    def _candidate_event(
        self,
        trace: CollaborationTrace,
        request: RoleRequest,
        response: RoleResponse,
        candidate: Candidate,
        before: dict[str, int | float],
        evaluation: dict[str, Any] | None,
        status: TraceStatus,
        error: Exception | None = None,
        *,
        error_type: str | None = None,
    ) -> None:
        self._append_event(
            trace,
            request,
            before,
            response=response,
            output_candidate=candidate.to_dict(),
            evaluation=evaluation,
            status=status,
            error_type=error_type or (type(error).__name__ if error else None),
            error_message=str(error) if error else None,
        )

    def _append_event(
        self,
        trace: CollaborationTrace,
        request: RoleRequest,
        before: dict[str, int | float],
        *,
        response: RoleResponse | None = None,
        output_candidate: dict[str, Any] | None = None,
        output_feedback: str | None = None,
        evaluation: dict[str, Any] | None = None,
        status: TraceStatus,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        request_index = response.request_index if response is not None else -1
        event_id = (
            f"g{request.generation}-r{request.round_index}-{request.role.value}-"
            f"{request.action}-{self._event_sequence:03d}-{request_index}"
        )
        self._event_sequence += 1
        trace.events.append(
            CollaborationEvent(
                event_id=event_id,
                role=request.role,
                action=request.action,
                round_index=request.round_index,
                target_branch=request.target_branch,
                temperature=request.temperature,
                prompt_version=PROMPT_VERSION,
                input_candidates=tuple(candidate.to_dict() for candidate in request.candidates),
                input_feedback=request.feedback,
                output_candidate=output_candidate,
                output_feedback=output_feedback,
                evaluation=evaluation,
                budget_before=before,
                budget_after=_budget_counters(self.ledger),
                status=status,
                error_type=error_type,
                error_message=error_message,
            )
        )


def _valid_critic_response(response: object) -> bool:
    return (
        isinstance(response, RoleResponse)
        and type(response.request_index) is int
        and response.request_index >= 0
        and response.candidate is None
        and isinstance(response.feedback, str)
        and bool(response.feedback.strip())
    )


def _valid_candidate_response(response: object) -> bool:
    return (
        isinstance(response, RoleResponse)
        and type(response.request_index) is int
        and response.request_index >= 0
        and response.feedback is None
        and isinstance(response.candidate, GeneratedHeuristic)
        and response.candidate.request_index == response.request_index
        and isinstance(response.candidate.description, str)
        and bool(response.candidate.description.strip())
        and isinstance(response.candidate.code, str)
        and bool(response.candidate.code.strip())
    )


def _role_candidate_id(request: RoleRequest, response: RoleResponse) -> str:
    assert response.candidate is not None
    payload = json.dumps(
        {
            "role": request.role.value,
            "action": request.action,
            "generation": request.generation,
            "round": request.round_index,
            "parents": [candidate.id for candidate in request.candidates],
            "description": response.candidate.description,
            "code": response.candidate.code,
            "request_index": response.request_index,
        },
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()[:16]
    return f"g{request.generation}-{request.role.value}-r{request.round_index}-{digest}"


def _budget_counters(ledger: BudgetLedger) -> dict[str, int | float]:
    """Return replay-stable counters; wall time remains in the run manifest."""

    return {
        "llm_calls": ledger.llm_calls,
        "input_tokens": ledger.input_tokens,
        "output_tokens": ledger.output_tokens,
        "tokens": ledger.tokens,
        "generated_candidates": ledger.generated_candidates,
        "valid_evals": ledger.valid_evals,
        "cost": ledger.cost,
    }
