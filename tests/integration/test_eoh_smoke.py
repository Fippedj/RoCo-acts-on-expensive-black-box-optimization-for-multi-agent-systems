from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from roco_ebbo.benchmarks import generate_symmetric_distance_matrix
from roco_ebbo.core import BudgetLedger, Candidate
from roco_ebbo.evaluation import TSPCodeEvaluator
from roco_ebbo.evolution import EoHEngine, EoHOperator
from roco_ebbo.llm import GeneratedHeuristic, MockLLMProvider
from roco_ebbo.smoke import load_smoke_settings, run_smoke


class _OneInvalidOffspringProvider(MockLLMProvider):
    def generate(
        self,
        operator: EoHOperator,
        generation: int,
        parents: Sequence[Candidate],
        ledger: BudgetLedger,
    ) -> GeneratedHeuristic:
        generated = super().generate(operator, generation, parents, ledger)
        if generated.request_index == 4:
            return GeneratedHeuristic(
                description=generated.description,
                code="def heuristic(distance_matrix):\n    return [0, 0]\n",
                request_index=generated.request_index,
            )
        return generated


def test_eoh_smoke_is_reproducible_and_within_budget() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    settings = load_smoke_settings(repository_root / "configs" / "smoke" / "tsp_mock.yaml")

    first = run_smoke(settings)
    second = run_smoke(settings)

    first_ids = [candidate.id for candidate in first.result.population.candidates]
    second_ids = [candidate.id for candidate in second.result.population.candidates]
    first_scores = [candidate.score for candidate in first.result.population.candidates]
    second_scores = [candidate.score for candidate in second.result.population.candidates]
    assert first_ids == second_ids
    assert first_scores == second_scores
    assert len(first.result.population.candidates) == settings.population_size == 4
    assert first.result.generations_completed == settings.generations == 2
    assert first.ledger.llm_calls == second.ledger.llm_calls == 12
    assert first.ledger.generated_candidates == second.ledger.generated_candidates == 12
    assert first.ledger.valid_evals == second.ledger.valid_evals == 12
    assert first.ledger.tokens == second.ledger.tokens
    assert not first.ledger.budget_reached
    assert all(
        candidate.metadata["evaluation"]["valid"] for candidate in first.result.all_candidates
    )
    assert first.result.population.best.score == min(first_scores)


def test_invalid_offspring_does_not_stop_the_population_run() -> None:
    ledger = BudgetLedger(max_llm_calls=20, max_tokens=20_000, max_valid_evals=20)
    engine = EoHEngine(
        provider=_OneInvalidOffspringProvider(seed=5),
        evaluator=TSPCodeEvaluator(timeout_seconds=2),
        distance_matrix=generate_symmetric_distance_matrix(nodes=20, seed=9),
        ledger=ledger,
        population_size=4,
        generations=1,
    )

    result = engine.run()

    assert result.generations_completed == 1
    assert len(result.population.candidates) == 4
    assert ledger.llm_calls == ledger.generated_candidates == 8
    assert ledger.valid_evals == 7
    invalid = [
        candidate
        for candidate in result.all_candidates
        if not candidate.metadata["evaluation"]["valid"]
    ]
    assert len(invalid) == 1


def test_missing_provider_defaults_to_the_unchanged_offline_mock_path(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source = repository_root / "configs" / "smoke" / "tsp_mock.yaml"
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    del raw["llm"]["provider"]
    config = tmp_path / "default-provider.yaml"
    config.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    settings = load_smoke_settings(config)
    smoke_run = run_smoke(settings)

    assert settings.provider == "mock"
    assert smoke_run.ledger.llm_calls == smoke_run.ledger.valid_evals == 12


def test_smoke_cli_configuration_rejects_real_provider_selection(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source = repository_root / "configs" / "smoke" / "tsp_mock.yaml"
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    raw["llm"]["provider"] = "openai-compatible"
    config = tmp_path / "network-provider.yaml"
    config.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="only the offline mock provider"):
        load_smoke_settings(config)
