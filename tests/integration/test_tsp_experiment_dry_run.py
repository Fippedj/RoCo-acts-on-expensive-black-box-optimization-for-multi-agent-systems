from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

from roco_ebbo.experiments import load_dataset_manifest, read_results_jsonl


def test_tsp_protocol_cli_covers_sizes_splits_seeds_methods_and_visibility(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    config = repository_root / "configs/experiments/tsp_mock_dry_run.yaml"
    output_dir = tmp_path / "protocol-run"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "roco_ebbo",
            "tsp-dry-run",
            "--config",
            str(config),
            "--output-dir",
            str(output_dir),
        ],
        cwd=repository_root,
        check=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(repository_root / "src")},
        text=True,
        timeout=180,
    )

    output = dict(line.split("=", 1) for line in completed.stdout.strip().splitlines())
    assert output["results"] == "72"
    assert output["summaries"] == "72"
    assert output["provider"] == "mock"
    assert output["network"] == "unused"
    assert Path(output["output_dir"]) == output_dir

    dataset = load_dataset_manifest(output_dir / "dataset_manifest.json")
    results = read_results_jsonl(output_dir / "results.jsonl")
    assert output["dataset_manifest_checksum"] == dataset.checksum
    assert len(dataset.instances) == 6
    assert len(results) == 72
    assert {result.instance["nodes"] for result in results} == {50, 100, 200}
    assert {result.split for result in results} == {"train", "test"}
    assert {result.seed for result in results} == {101, 202, 303}
    assert {result.method for result in results} == {"eoh", "roco"}
    assert {result.prompt_visibility["condition"] for result in results} == {
        "white_box",
        "black_box",
    }
    assert all(result.prompt_visibility["mock_metadata_only"] for result in results)
    assert all(
        result.provider == {"name": "mock", "model": "deterministic", "network": "unused"}
        for result in results
    )
    assert all(result.status == "completed" and result.best_score is not None for result in results)
    assert all(result.budget["hard_limits"]["max_llm_calls"] == 24 for result in results)
    assert {result.llm_calls for result in results if result.method == "eoh"} == {8}
    assert {result.llm_calls for result in results if result.method == "roco"} == {18}

    with (output_dir / "results.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    with (output_dir / "summary.csv").open(encoding="utf-8", newline="") as stream:
        summaries = list(csv.DictReader(stream))
    assert len(rows) == len(results)
    assert len(summaries) == 72
    assert {row["method"] for row in summaries} == {"eoh", "roco"}
    assert {row["split"] for row in summaries} == {"train", "test"}
