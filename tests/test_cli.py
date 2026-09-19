from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from roco_ebbo import __version__


def test_package_version() -> None:
    assert __version__ == "0.1.0"


def test_cli_smoke_writes_ignored_run_artifacts(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = repository_root / "configs" / "smoke" / "tsp_mock.yaml"
    runs_dir = tmp_path / "runs"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "roco_ebbo",
            "smoke",
            "--config",
            str(config),
            "--runs-dir",
            str(runs_dir),
        ],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    output = dict(line.split("=", 1) for line in completed.stdout.strip().splitlines())
    assert output["valid_evaluations"] == "12"
    assert output["llm_calls"] == "12"
    assert output["budget_reached"] == "false"

    run_directory = runs_dir / output["run_id"]
    manifest = json.loads((run_directory / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_directory / "summary.json").read_text(encoding="utf-8"))
    events = (run_directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert manifest["seed"] == 7
    assert manifest["budget_snapshot"]["valid_evals"] == 12
    assert summary["population_size"] == 4
    assert len(events) == 2
