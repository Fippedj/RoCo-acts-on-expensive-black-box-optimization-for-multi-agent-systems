from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from roco_ebbo.experiments.tsp_protocol import (
    ExperimentBudgets,
    TSPDatasetManifest,
    TSPDatasetSpec,
    TSPExperimentResult,
    TSPInstance,
    TSPProtocolError,
    create_dataset_manifest,
    execute_tsp_experiment,
    load_dataset_manifest,
    load_tsp_experiment_settings,
    read_results_jsonl,
)


def _config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs/experiments/tsp_mock_dry_run.yaml"


def _valid_result() -> TSPExperimentResult:
    instance = TSPInstance(
        instance_id="train-tsp-50-000",
        nodes=50,
        split="train",
        seed=7,
        generator_rule="python-random-mt19937-uniform-unit-square-v1",
        coordinates=tuple((index / 100.0, (index + 1) / 100.0) for index in range(50)),
    )
    budgets = ExperimentBudgets(24, 120000, 24, 24, 1.0, 120.0)
    return TSPExperimentResult(
        run_id="tsp-unit-result",
        seed=101,
        split="train",
        instance={
            "instance_id": instance.instance_id,
            "nodes": instance.nodes,
            "split": instance.split,
            "seed": instance.seed,
            "generator_rule": instance.generator_rule,
            "checksum": instance.checksum,
        },
        method="eoh",
        provider={"name": "mock", "model": "deterministic", "network": "unused"},
        prompt_visibility={
            "schema_version": "roco-prompt-visibility-v1",
            "condition": "black_box",
            "semantics": (
                "prompt must not expose coordinates, distance matrix, or evaluator internals"
            ),
            "mock_metadata_only": True,
        },
        llm_calls=8,
        input_tokens=20,
        output_tokens=30,
        cost=0.0,
        cost_currency="USD",
        valid_evals=8,
        generated_candidates=8,
        wall_time=0.01,
        best_score=3.0,
        status="completed",
        failure=None,
        budget={"hard_limits": budgets.to_dict(), "reached_limits": [], "budget_reached": False},
    )


def test_dataset_inventory_is_deterministic_and_split_separated(tmp_path: Path) -> None:
    spec = TSPDatasetSpec(master_seed=9, sizes=(50, 100, 200), train_instances=1, test_instances=1)
    first = create_dataset_manifest(spec)
    second = create_dataset_manifest(spec)

    assert first.to_dict() == second.to_dict()
    assert len(first.instances) == 6
    assert {instance.nodes for instance in first.instances} == {50, 100, 200}
    assert {instance.split for instance in first.instances} == {"train", "test"}
    assert len({instance.checksum for instance in first.instances}) == 6
    assert first.instances[0].distance_matrix()[0][0] == 0.0

    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(first.to_dict()), encoding="utf-8")
    assert load_dataset_manifest(path).to_dict() == first.to_dict()


def test_protocol_rejects_invalid_instances_checksum_mismatch_and_split_overlap(
    tmp_path: Path,
) -> None:
    with pytest.raises(TSPProtocolError, match="coordinate count"):
        TSPInstance(
            instance_id="broken",
            nodes=50,
            split="train",
            seed=1,
            generator_rule="python-random-mt19937-uniform-unit-square-v1",
            coordinates=((0.0, 0.0),),
        )

    manifest = create_dataset_manifest(
        TSPDatasetSpec(master_seed=9, sizes=(50,), train_instances=1, test_instances=1)
    )
    tampered = manifest.to_dict()
    tampered["instances"][0]["checksum"] = "0" * 64
    tampered["manifest_checksum"] = "0" * 64
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(TSPProtocolError, match="instance checksum mismatch"):
        load_dataset_manifest(path)

    train = manifest.instances[0]
    duplicate_as_test = replace(train, instance_id="test-duplicate", split="test")
    with pytest.raises(TSPProtocolError, match="split overlap|duplicate instance checksum"):
        TSPDatasetManifest(
            master_seed=manifest.master_seed,
            generator_rule=manifest.generator_rule,
            instances=(train, duplicate_as_test),
        )


def test_unknown_method_and_nonfinite_result_are_rejected(tmp_path: Path) -> None:
    raw = yaml.safe_load(_config_path().read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["experiment"]["methods"] = ["not-a-method"]
    config = tmp_path / "unknown-method.yaml"
    config.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(TSPProtocolError, match="methods"):
        load_tsp_experiment_settings(config)

    document = _valid_result().to_dict()
    document["best_score"] = float("nan")
    with pytest.raises(TSPProtocolError, match="best_score"):
        TSPExperimentResult.from_dict(document)


def test_jsonl_reader_rejects_corrupt_and_nonfinite_aggregation_input(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(TSPProtocolError, match="corrupt at line 1"):
        read_results_jsonl(corrupt)

    nonfinite = _valid_result().to_dict()
    nonfinite["best_score"] = float("inf")
    nonfinite_path = tmp_path / "nonfinite.jsonl"
    nonfinite_path.write_text(json.dumps(nonfinite, allow_nan=True) + "\n", encoding="utf-8")
    with pytest.raises(TSPProtocolError, match="schema failure at line 1"):
        read_results_jsonl(nonfinite_path)


def test_budget_exhaustion_is_recorded_without_changing_shared_limit_definition() -> None:
    base = load_tsp_experiment_settings(_config_path())
    tiny_dataset = TSPDatasetSpec(master_seed=11, sizes=(50,), train_instances=1, test_instances=1)
    limited = replace(
        base,
        dataset=tiny_dataset,
        methods=("roco",),
        prompt_visibilities=("black_box",),
        budgets=ExperimentBudgets(8, 120000, 24, 24, 1.0, 120.0),
    )

    run = execute_tsp_experiment(limited)

    assert len(run.results) == 6
    assert all(result.status == "budget_exhausted" for result in run.results)
    assert all(result.llm_calls == 8 for result in run.results)
    assert {json.dumps(result.budget["hard_limits"], sort_keys=True) for result in run.results} == {
        json.dumps(limited.budgets.to_dict(), sort_keys=True)
    }


def test_replay_checksum_is_stable_when_only_wall_time_changes() -> None:
    first = _valid_result()
    second = replace(first, wall_time=9.99)

    assert first.replay_checksum == second.replay_checksum
    assert first.to_dict()["wall_time"] != second.to_dict()["wall_time"]


def test_small_mock_protocol_replays_dataset_and_non_time_results() -> None:
    base = load_tsp_experiment_settings(_config_path())
    replay_settings = replace(
        base,
        dataset=TSPDatasetSpec(master_seed=13, sizes=(50,), train_instances=1, test_instances=1),
        methods=("eoh",),
        prompt_visibilities=("black_box",),
    )

    first = execute_tsp_experiment(replay_settings)
    second = execute_tsp_experiment(replay_settings)

    assert first.dataset.to_dict() == second.dataset.to_dict()
    assert [result.replay_checksum for result in first.results] == [
        result.replay_checksum for result in second.results
    ]
    assert [result.best_score for result in first.results] == [
        result.best_score for result in second.results
    ]
