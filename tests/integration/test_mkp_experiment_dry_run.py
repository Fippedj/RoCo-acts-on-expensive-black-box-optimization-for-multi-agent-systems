from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

import pytest

from roco_ebbo.benchmarks import load_fsu_mkp_dataset
from roco_ebbo.experiments import (
    execute_mkp_experiment,
    load_mkp_experiment_settings,
    read_mkp_results_jsonl,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPOSITORY_ROOT / "data/raw/mkp/fsu-knapsack-multiple"
pytestmark = pytest.mark.skipif(not DATA_ROOT.is_dir(), reason="authorized frozen MKP data absent")


def test_mkp_protocol_cli_covers_frozen_instances_methods_ledgers_and_replay(
    tmp_path: Path,
) -> None:
    config = REPOSITORY_ROOT / "configs/experiments/mkp_fsu_mock_dry_run.yaml"
    output_dir = tmp_path / "mkp-protocol-run"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "roco_ebbo",
            "mkp-dry-run",
            "--config",
            str(config),
            "--data-root",
            str(DATA_ROOT),
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY_ROOT / "src")},
        text=True,
        timeout=180,
    )

    output = dict(line.split("=", 1) for line in completed.stdout.strip().splitlines())
    assert output["results"] == "12"
    assert output["split"] == "protocol-only"
    assert output["provider"] == "mock"
    assert output["network"] == "unused"
    assert output["statistics"] == "disabled"

    dataset = load_fsu_mkp_dataset(DATA_ROOT)
    results = read_mkp_results_jsonl(output_dir / "results.jsonl")
    assert output["dataset_manifest_checksum"] == dataset.checksum
    assert {result.dataset["instance_id"] for result in results} == {
        "p01",
        "p02",
        "p03",
        "p04",
        "p05",
        "p06",
    }
    assert {result.dataset["split"] for result in results} == {"protocol-only"}
    assert {result.method["id"] for result in results} == {"eoh", "roco"}
    assert all(result.status == "completed" for result in results)
    assert all(result.provider["network_state"] == "unused" for result in results)
    assert all(result.prompt_visibility["reference_visible"] is False for result in results)
    assert all(result.evaluation["raw_profit"] is not None for result in results)
    assert all(
        result.evaluation["best_score"] == -result.evaluation["raw_profit"] for result in results
    )
    assert {
        result.budget["actual"]["llm_calls"] for result in results if result.method["id"] == "eoh"
    } == {8}
    assert {
        result.budget["actual"]["valid_evals"] for result in results if result.method["id"] == "eoh"
    } == {8}
    assert {
        result.budget["actual"]["llm_calls"] for result in results if result.method["id"] == "roco"
    } == {18}
    assert {
        result.budget["actual"]["valid_evals"]
        for result in results
        if result.method["id"] == "roco"
    } == {13}
    assert not (output_dir / "summary.jsonl").exists()
    assert not (output_dir / "summary.csv").exists()

    with (output_dir / "results.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 12
    assert {row["budget_profile"] for row in rows} == {"mkp-fsu-mock-engineering-v1"}

    replay = execute_mkp_experiment(load_mkp_experiment_settings(config), data_root=DATA_ROOT)
    assert [result.replay_checksum for result in results] == [
        result.replay_checksum for result in replay.results
    ]
    assert [result.evaluation for result in results] == [
        result.evaluation for result in replay.results
    ]
