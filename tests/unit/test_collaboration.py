from __future__ import annotations

from collections import Counter
from typing import Literal

import pytest

from roco_ebbo.benchmarks import generate_symmetric_distance_matrix
from roco_ebbo.core import BudgetLedger, Candidate
from roco_ebbo.evaluation import TSPCodeEvaluator
from roco_ebbo.evolution import CollaborationOutcome, RoCoCollaborator
from roco_ebbo.llm import (
    GeneratedHeuristic,
    MockLLMProvider,
    RoCoRole,
    RoleRequest,
    RoleResponse,
)


class _RecordingProvider(MockLLMProvider):
    def __init__(self, seed: int) -> None:
        super().__init__(seed)
        self.role_requests: list[RoleRequest] = []

    def generate_role(self, request: RoleRequest, ledger: BudgetLedger) -> RoleResponse:
        self.role_requests.append(request)
        return super().generate_role(request, ledger)


class _FaultInjectingProvider(_RecordingProvider):
    def __init__(
        self,
        seed: int,
        failure: Literal["invalid_output", "wrong_type", "invalid_candidate"],
    ) -> None:
        super().__init__(seed)
        self.failure = failure
        self._fault_used = False

    def generate_role(self, request: RoleRequest, ledger: BudgetLedger) -> RoleResponse:
        response = super().generate_role(request, ledger)
        if self._fault_used or request.role is not RoCoRole.EXPLORER:
            return response
        self._fault_used = True
        if self.failure == "invalid_output":
            return RoleResponse(
                request_index=response.request_index,
                feedback="Explorer returned feedback instead of a candidate.",
            )
        if self.failure == "wrong_type":
            return {"description": "not a RoleResponse"}  # type: ignore[return-value]

        assert response.candidate is not None
        invalid = GeneratedHeuristic(
            description=response.candidate.description,
            code="def heuristic(distance_matrix):\n    return [0, 0]\n",
            request_index=response.request_index,
        )
        return RoleResponse(request_index=response.request_index, candidate=invalid)


class _ProviderErrorProvider(_RecordingProvider):
    def __init__(self, seed: int) -> None:
        super().__init__(seed)
        self._fault_used = False

    def generate_role(self, request: RoleRequest, ledger: BudgetLedger) -> RoleResponse:
        if not self._fault_used and request.role is RoCoRole.EXPLORER:
            self.role_requests.append(request)
            self._fault_used = True
            ledger.consume(llm_calls=1, input_tokens=1, output_tokens=1)
            raise RuntimeError("injected provider failure")
        return super().generate_role(request, ledger)


class _FailingIntegratorProvider(_RecordingProvider):
    def generate_role(self, request: RoleRequest, ledger: BudgetLedger) -> RoleResponse:
        response = super().generate_role(request, ledger)
        if request.role is RoCoRole.INTEGRATOR:
            return RoleResponse(
                request_index=response.request_index,
                feedback="Integrator returned feedback instead of a candidate.",
            )
        return response


class _TimeoutExplorerProvider(_RecordingProvider):
    def __init__(self, seed: int) -> None:
        super().__init__(seed)
        self._fault_used = False

    def generate_role(self, request: RoleRequest, ledger: BudgetLedger) -> RoleResponse:
        response = super().generate_role(request, ledger)
        if self._fault_used or request.role is not RoCoRole.EXPLORER:
            return response
        self._fault_used = True
        assert response.candidate is not None
        timeout_candidate = GeneratedHeuristic(
            description=response.candidate.description,
            code="def heuristic(distance_matrix):\n    while True:\n        pass\n",
            request_index=response.request_index,
        )
        return RoleResponse(request_index=response.request_index, candidate=timeout_candidate)


def _population() -> list[Candidate]:
    code = "def heuristic(distance_matrix):\n    return list(range(len(distance_matrix)))\n"
    return [
        Candidate(
            id=f"seed-{index}",
            description=f"evaluated seed {index}",
            code=code,
            parents=(),
            operator="seed",
            generation=0,
            score=10.0 + index,
        )
        for index in range(4)
    ]


def _run_collaboration(
    provider: _RecordingProvider,
    *,
    rounds: int = 2,
    collaboration_seed: int = 29,
    max_llm_calls: int = 100,
    evaluator_timeout_seconds: float = 3,
) -> tuple[CollaborationOutcome, BudgetLedger]:
    ledger = BudgetLedger(
        max_llm_calls=max_llm_calls,
        max_tokens=100_000,
        max_generated_candidates=100,
        max_valid_evals=100,
    )
    collaborator = RoCoCollaborator(
        provider=provider,
        evaluator=TSPCodeEvaluator(timeout_seconds=evaluator_timeout_seconds),
        distance_matrix=generate_symmetric_distance_matrix(nodes=20, seed=17),
        ledger=ledger,
        rounds=rounds,
        seed=collaboration_seed,
    )
    return collaborator.run(_population(), generation=1), ledger


def _without_runtime(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_runtime(item) for key, item in value.items() if key != "runtime_seconds"
        }
    if isinstance(value, list):
        return [_without_runtime(item) for item in value]
    return value


def test_two_rounds_call_all_roles_the_expected_number_of_times() -> None:
    provider = _RecordingProvider(seed=101)

    outcome, ledger = _run_collaboration(provider, rounds=2)

    counts = Counter(request.role for request in provider.role_requests)
    assert counts[RoCoRole.EXPLORER] == 2
    assert counts[RoCoRole.EXPLOITER] == 2
    assert counts[RoCoRole.CRITIC] == 5
    assert counts[RoCoRole.INTEGRATOR] == 1
    assert len(provider.role_requests) == 10
    assert [request.role for request in provider.role_requests] == [
        RoCoRole.CRITIC,
        RoCoRole.EXPLORER,
        RoCoRole.EXPLOITER,
        RoCoRole.CRITIC,
        RoCoRole.CRITIC,
        RoCoRole.EXPLORER,
        RoCoRole.EXPLOITER,
        RoCoRole.CRITIC,
        RoCoRole.CRITIC,
        RoCoRole.INTEGRATOR,
    ]
    assert outcome.trace.rounds_requested == 2
    assert outcome.trace.rounds_completed == 2
    assert not outcome.stopped_on_budget
    assert len(outcome.candidates) == 5
    assert ledger.llm_calls == 10
    assert ledger.generated_candidates == ledger.valid_evals == 5
    assert {request.role: request.temperature for request in provider.role_requests} == {
        RoCoRole.EXPLORER: 1.3,
        RoCoRole.EXPLOITER: 0.8,
        RoCoRole.CRITIC: 1.0,
        RoCoRole.INTEGRATOR: 1.0,
    }
    assert len({request.prompt for request in provider.role_requests}) == 4


def test_same_seeds_replay_mock_outputs_candidate_ids_and_role_sequence() -> None:
    first_provider = _RecordingProvider(seed=103)
    second_provider = _RecordingProvider(seed=103)

    first, first_ledger = _run_collaboration(first_provider, collaboration_seed=31)
    second, second_ledger = _run_collaboration(second_provider, collaboration_seed=31)

    assert [request.role for request in first_provider.role_requests] == [
        request.role for request in second_provider.role_requests
    ]
    assert [candidate.id for candidate in first.candidates] == [
        candidate.id for candidate in second.candidates
    ]
    assert [
        (candidate.description, candidate.code, candidate.parents, candidate.score)
        for candidate in first.candidates
    ] == [
        (candidate.description, candidate.code, candidate.parents, candidate.score)
        for candidate in second.candidates
    ]
    assert _without_runtime(first.trace.to_dict()) == _without_runtime(second.trace.to_dict())
    assert first_ledger.to_dict() == second_ledger.to_dict()


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_error_type"),
    [
        ("invalid_output", "invalid_output", "role_output_error"),
        ("wrong_type", "invalid_output", "role_output_error"),
        ("invalid_candidate", "invalid_candidate", "invalid_tour"),
    ],
)
def test_invalid_role_result_is_traced_and_collaboration_continues(
    failure: Literal["invalid_output", "wrong_type", "invalid_candidate"],
    expected_status: str,
    expected_error_type: str,
) -> None:
    provider = _FaultInjectingProvider(seed=107, failure=failure)

    outcome, _ = _run_collaboration(provider, rounds=1)

    failed_events = [event for event in outcome.trace.events if event.status == expected_status]
    assert len(failed_events) == 1
    assert failed_events[0].role is RoCoRole.EXPLORER
    assert failed_events[0].error_type == expected_error_type
    assert outcome.trace.rounds_completed == 1
    assert not outcome.stopped_on_budget
    assert provider.role_requests[-1].role is RoCoRole.INTEGRATOR
    assert outcome.trace.events[-1].status == "success"
    assert outcome.trace.events[-1].role is RoCoRole.INTEGRATOR


def test_role_budget_exhaustion_stops_safely_with_structured_trace() -> None:
    provider = _RecordingProvider(seed=109)

    outcome, ledger = _run_collaboration(provider, rounds=2, max_llm_calls=1)

    assert outcome.stopped_on_budget
    assert outcome.trace.stopped_on_budget
    assert outcome.trace.rounds_completed == 0
    assert ledger.llm_calls == 1
    assert ledger.reached_limits == ("llm_calls",)
    assert [request.role for request in provider.role_requests] == [
        RoCoRole.CRITIC,
        RoCoRole.EXPLORER,
    ]
    exhausted = [event for event in outcome.trace.events if event.status == "budget_exhausted"]
    assert len(exhausted) == 1
    assert exhausted[0].role is RoCoRole.EXPLORER
    assert exhausted[0].error_type == "BudgetExceededError"
    assert exhausted[0].budget_before["llm_calls"] == 1
    assert exhausted[0].budget_after["llm_calls"] == 1
    assert exhausted[0].output_candidate is None


def test_provider_exception_is_traced_and_collaboration_continues() -> None:
    provider = _ProviderErrorProvider(seed=113)

    outcome, ledger = _run_collaboration(provider, rounds=1)

    failures = [event for event in outcome.trace.events if event.status == "provider_error"]
    assert len(failures) == 1
    assert failures[0].role is RoCoRole.EXPLORER
    assert failures[0].error_type == "RuntimeError"
    assert failures[0].budget_after["llm_calls"] - failures[0].budget_before["llm_calls"] == 1
    assert outcome.trace.rounds_completed == 1
    assert not outcome.stopped_on_budget
    assert outcome.trace.events[-1].role is RoCoRole.INTEGRATOR
    assert outcome.trace.events[-1].status == "success"
    assert ledger.llm_calls == 6


def test_integrator_invalid_output_is_traced_without_losing_round_candidates() -> None:
    provider = _FailingIntegratorProvider(seed=127)

    outcome, _ = _run_collaboration(provider, rounds=1)

    final_event = outcome.trace.events[-1]
    assert final_event.role is RoCoRole.INTEGRATOR
    assert final_event.status == "invalid_output"
    assert final_event.error_type == "role_output_error"
    assert outcome.trace.rounds_completed == 1
    assert not outcome.stopped_on_budget
    assert len(outcome.candidates) == 2
    assert {candidate.operator for candidate in outcome.candidates} == {"explorer", "exploiter"}


def test_roco_candidate_timeout_is_traced_and_collaboration_continues() -> None:
    provider = _TimeoutExplorerProvider(seed=131)

    outcome, _ = _run_collaboration(
        provider,
        rounds=1,
        evaluator_timeout_seconds=0.1,
    )

    failures = [event for event in outcome.trace.events if event.error_type == "timeout"]
    assert len(failures) == 1
    assert failures[0].role is RoCoRole.EXPLORER
    assert failures[0].status == "invalid_candidate"
    assert failures[0].evaluation is not None
    assert failures[0].evaluation["valid"] is False
    assert outcome.trace.rounds_completed == 1
    assert outcome.trace.events[-1].role is RoCoRole.INTEGRATOR
    assert outcome.trace.events[-1].status == "success"


def test_collaborator_defaults_to_three_rounds() -> None:
    provider = _RecordingProvider(seed=137)
    ledger = BudgetLedger(
        max_llm_calls=20,
        max_tokens=100_000,
        max_generated_candidates=20,
        max_valid_evals=20,
    )
    collaborator = RoCoCollaborator(
        provider=provider,
        evaluator=TSPCodeEvaluator(timeout_seconds=3),
        distance_matrix=generate_symmetric_distance_matrix(nodes=20, seed=19),
        ledger=ledger,
        seed=37,
    )

    outcome = collaborator.run(_population(), generation=1)

    assert outcome.trace.rounds_requested == 3
    assert outcome.trace.rounds_completed == 3
    assert len(outcome.trace.events) == 14
    assert len(outcome.candidates) == 7
    assert ledger.llm_calls == 14
    assert ledger.generated_candidates == ledger.valid_evals == 7


def test_collaborator_rejects_maximize_mode() -> None:
    with pytest.raises(ValueError, match="only minimize=True"):
        RoCoCollaborator(
            provider=MockLLMProvider(seed=139),
            evaluator=TSPCodeEvaluator(timeout_seconds=3),
            distance_matrix=generate_symmetric_distance_matrix(nodes=20, seed=23),
            ledger=BudgetLedger(max_llm_calls=20),
            minimize=False,
        )
