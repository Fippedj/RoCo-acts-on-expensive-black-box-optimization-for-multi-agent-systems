from __future__ import annotations

import json

import pytest

from roco_ebbo.benchmarks import generate_symmetric_distance_matrix
from roco_ebbo.core import BudgetLedger, Candidate
from roco_ebbo.evaluation import TSPCodeEvaluator
from roco_ebbo.evolution import EoHOperator, Population, RoCoCollaborator
from roco_ebbo.llm import MockLLMProvider


def _candidate(candidate_id: str, score: float) -> Candidate:
    return Candidate(
        id=candidate_id,
        description="checkpoint candidate",
        code="def heuristic(distance_matrix):\n    return list(range(len(distance_matrix)))\n",
        parents=(),
        operator="E1",
        generation=0,
        score=score,
        metadata={"evaluation": {"valid": True, "score": score}},
    )


def test_population_and_ledger_snapshots_round_trip_as_plain_json() -> None:
    population = Population([_candidate("a", 1.0), _candidate("b", 2.0)], size=2)
    ledger = BudgetLedger(max_llm_calls=20, max_tokens=1000)
    ledger.consume(llm_calls=2, input_tokens=3, output_tokens=4, generated_candidates=1)

    population_snapshot = json.loads(json.dumps(population.to_snapshot(), allow_nan=False))
    ledger_snapshot = json.loads(json.dumps(ledger.to_snapshot(), allow_nan=False))

    assert Population.from_snapshot(population_snapshot).to_snapshot() == population_snapshot
    assert BudgetLedger.from_snapshot(ledger_snapshot).to_snapshot() == ledger_snapshot


def test_snapshot_boundaries_reject_non_json_and_non_finite_values() -> None:
    candidate = _candidate("bad", 1.0)
    candidate.metadata["not_json"] = object()
    with pytest.raises(ValueError, match="non-JSON"):
        candidate.to_snapshot()

    ledger = BudgetLedger().to_snapshot()
    ledger["cost"] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        BudgetLedger.from_snapshot(ledger)


def test_mock_provider_snapshot_replays_next_output_without_private_random_state() -> None:
    first = MockLLMProvider(seed=73)
    first_ledger = BudgetLedger(max_llm_calls=20, max_tokens=20_000)
    first.generate(EoHOperator.E1, 0, (), first_ledger)
    first.generate(EoHOperator.E2, 0, (), first_ledger)
    snapshot = json.loads(json.dumps(first.to_snapshot(), allow_nan=False))

    restored = MockLLMProvider.from_snapshot(snapshot)
    restored_ledger = BudgetLedger(max_llm_calls=20, max_tokens=20_000)

    expected = first.generate(EoHOperator.M1, 1, (), first_ledger)
    actual = restored.generate(EoHOperator.M1, 1, (), restored_ledger)

    assert actual == expected
    assert set(snapshot) == {"schema_version", "seed", "request_index", "rng_draws"}


def test_collaborator_snapshot_replays_logical_sampling_cursor() -> None:
    matrix = generate_symmetric_distance_matrix(nodes=20, seed=23)
    population = [_candidate(str(index), float(index + 1)) for index in range(4)]
    first_provider = MockLLMProvider(seed=79)
    first_ledger = BudgetLedger(max_llm_calls=100, max_tokens=100_000, max_valid_evals=100)
    first = RoCoCollaborator(
        provider=first_provider,
        evaluator=TSPCodeEvaluator(timeout_seconds=3),
        distance_matrix=matrix,
        ledger=first_ledger,
        rounds=1,
        seed=83,
    )
    first.run(population, generation=1)

    provider_snapshot = first_provider.to_snapshot()
    ledger_snapshot = first_ledger.to_snapshot()
    collaborator_snapshot = json.loads(json.dumps(first.to_snapshot(), allow_nan=False))
    second_provider = MockLLMProvider.from_snapshot(provider_snapshot)
    second_ledger = BudgetLedger.from_snapshot(ledger_snapshot)
    second = RoCoCollaborator(
        provider=second_provider,
        evaluator=TSPCodeEvaluator(timeout_seconds=3),
        distance_matrix=matrix,
        ledger=second_ledger,
        rounds=1,
        seed=0,
    )
    second.restore_snapshot(collaborator_snapshot)

    first_next = first.run(population, generation=2)
    second_next = second.run(population, generation=2)

    assert second_next.trace.elite_pair_ranks == first_next.trace.elite_pair_ranks
    assert [event.event_id for event in second_next.trace.events] == [
        event.event_id for event in first_next.trace.events
    ]
    assert [candidate.id for candidate in second_next.candidates] == [
        candidate.id for candidate in first_next.candidates
    ]
