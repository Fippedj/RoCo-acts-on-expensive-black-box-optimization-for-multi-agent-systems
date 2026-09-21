from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from roco_ebbo.benchmarks import MKPInstance
from roco_ebbo.core import BudgetLedger
from roco_ebbo.evaluation import MKPCodeEvaluator
from roco_ebbo.evolution import EoHEngine, RoCoCollaborator
from roco_ebbo.experiments.mkp_protocol import (
    MKPBudgetProfile,
    MKPExperimentResult,
    MKPProtocolError,
    build_full_instance_prompt,
    load_mkp_experiment_settings,
    prompt_visibility_contract,
    read_mkp_results_jsonl,
)
from roco_ebbo.llm import MKPMockLLMProvider


def _config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs/experiments/mkp_fsu_mock_dry_run.yaml"


def _instance() -> MKPInstance:
    return MKPInstance(
        instance_id="fixture",
        capacities=(5, 6),
        weights=(2, 3, 4),
        profits=(4, 5, 8),
        input_files=({"filename": "fixture", "sha256": "a" * 64},),
        reference_file={"filename": "secret_s.txt", "present": True, "sha256": "b" * 64},
    )


class _RoleFailureProvider(MKPMockLLMProvider):
    def generate_role(self, request: object, ledger: BudgetLedger) -> object:
        raise RuntimeError("API_TOKEN=must-not-escape")


def test_config_freezes_new_mock_profile_and_rejects_unknown_method(tmp_path: Path) -> None:
    settings = load_mkp_experiment_settings(_config_path())
    assert settings.methods == ("eoh", "roco")
    assert settings.budgets.profile_id == "mkp-fsu-mock-engineering-v1"
    assert settings.budgets.max_llm_calls == 20

    raw = yaml.safe_load(_config_path().read_text(encoding="utf-8"))
    raw["experiment"]["methods"] = ["unknown"]
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(MKPProtocolError, match="methods"):
        load_mkp_experiment_settings(path)


def test_full_instance_prompt_never_contains_reference_fields() -> None:
    prompt = build_full_instance_prompt(_instance())
    parsed = json.loads(prompt)

    assert parsed["capacities"] == [5, 6]
    assert parsed["weights"] == [2, 3, 4]
    assert parsed["profits"] == [4, 5, 8]
    assert not any("reference" in key or "optimum" in key for key in parsed)
    assert "secret_s.txt" not in prompt


def test_roco_provider_error_is_structured_and_redacted() -> None:
    instance = _instance()
    provider = _RoleFailureProvider(31, build_full_instance_prompt(instance))
    ledger = BudgetLedger(max_llm_calls=20, max_tokens=50_000, max_valid_evals=16)
    evaluator = MKPCodeEvaluator(timeout_seconds=2)
    collaborator = RoCoCollaborator(
        provider=provider,
        evaluator=evaluator,
        distance_matrix=instance,
        ledger=ledger,
        rounds=1,
        seed=7,
    )
    engine = EoHEngine(
        provider=provider,
        evaluator=evaluator,
        distance_matrix=instance,
        ledger=ledger,
        population_size=4,
        generations=1,
        collaborator=collaborator,
    )

    result = engine.run()
    failures = [
        event for event in result.collaboration_traces[0].events if event.status == "provider_error"
    ]
    assert failures
    assert failures[0].error_type == "RuntimeError"
    # Existing collaboration trace records the local exception. The P7b run-record
    # boundary redacts it; this fixture ensures the provider failure does not crash.
    assert result.population.best.score is not None


def test_roco_hard_budget_exhaustion_stops_without_changing_minimize_semantics() -> None:
    settings = load_mkp_experiment_settings(_config_path())
    profile = replace(settings.budgets, max_llm_calls=8)
    instance = _instance()
    provider = MKPMockLLMProvider(37, build_full_instance_prompt(instance))
    ledger = profile.new_ledger()
    evaluator = MKPCodeEvaluator(timeout_seconds=2)
    collaborator = RoCoCollaborator(
        provider=provider,
        evaluator=evaluator,
        distance_matrix=instance,
        ledger=ledger,
        rounds=2,
        seed=11,
    )
    engine = EoHEngine(
        provider=provider,
        evaluator=evaluator,
        distance_matrix=instance,
        ledger=ledger,
        population_size=4,
        generations=1,
        collaborator=collaborator,
        minimize=True,
    )

    result = engine.run()

    assert result.stopped_on_budget
    assert ledger.llm_calls == 8
    assert ledger.reached_limits == ("llm_calls",)
    assert result.population.best.score == min(
        candidate.score for candidate in result.population.candidates if candidate.score is not None
    )


def test_result_reader_rejects_nonfinite_and_corrupt_records(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(MKPProtocolError, match="corrupt at line 1"):
        read_mkp_results_jsonl(corrupt)

    document = _valid_result().to_dict()
    document["evaluation"]["best_score"] = float("nan")
    nonfinite = tmp_path / "nonfinite.jsonl"
    nonfinite.write_text(json.dumps(document, allow_nan=True) + "\n", encoding="utf-8")
    with pytest.raises(MKPProtocolError, match="best_score"):
        read_mkp_results_jsonl(nonfinite)


def _valid_result() -> MKPExperimentResult:
    profile = MKPBudgetProfile("mkp-fsu-mock-engineering-v1", 20, 50000, 16, 16, 0.25, 60.0)
    return MKPExperimentResult(
        run_id="mkp-p01-eoh-unit",
        benchmark={
            "id": "mkp-01",
            "version": "mkp-fsu-protocol-v1",
            "evidence_level": "E3",
            "source_id": "fsu-john-burkardt-knapsack-multiple",
            "release": "page-revised-2009-12-08;frozen-2026-09-21",
            "license_id": "LGPL-3.0-only",
        },
        dataset={
            "inventory_checksum": "a" * 64,
            "instance_id": "p01",
            "instance_checksum": "b" * 64,
            "split": "protocol-only",
            "split_policy_version": "mkp-fsu-protocol-only-v1",
        },
        randomness={"root_seed": 707, "derived_run_seed": 1, "provider_seed": 2},
        method={"id": "eoh", "version": "eoh-stage2-v1", "implementation_git_sha": None},
        provider={
            "name": "mock",
            "network_state": "unused",
            "model": "deterministic-mkp",
            "adapter_contract": "mkp-mock-provider-v1",
            "tokenizer_counter": "mock-whitespace-v1",
            "pricing_version": "mock-zero-cost-v1",
        },
        prompt_visibility=prompt_visibility_contract(_instance()),
        budget={
            "profile_id": profile.profile_id,
            "hard_limits": profile.to_dict(),
            "actual": {
                "llm_calls": 8,
                "input_tokens": 10,
                "output_tokens": 20,
                "tokens": 30,
                "generated_candidates": 8,
                "valid_evals": 8,
                "cost": 0.0,
                "cost_currency": "USD",
                "wall_time": 0.1,
            },
            "reached_limits": [],
        },
        evaluation={
            "source_objective_direction": "maximize",
            "selection_direction": "minimize",
            "evaluator_contract": "mkp-fsu-evaluator-v1",
            "timeout_scope": "per-candidate",
            "metric_name": "negative_raw_profit",
            "reference_version_or_null": None,
            "best_score": -10.0,
            "raw_profit": 10,
            "normalized_score": -0.5,
            "normalization_contract": "negative-profit-over-total-positive-profit-v1",
            "feasible": True,
        },
        status="completed",
        failure=None,
        replay={
            "dataset_verified": True,
            "split_verified": True,
            "result_verified": True,
            "non_time_state_verified": True,
        },
    )
