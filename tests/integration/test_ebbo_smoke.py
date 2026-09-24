from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from roco_ebbo.ebbo import load_ebbo_smoke_settings, run_ebbo_smoke


def test_ebbo_mock_smoke_replays_non_time_state_and_writes_auditable_artifacts(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    settings = load_ebbo_smoke_settings(root / "configs/smoke/ebbo_mock.yaml")

    first = run_ebbo_smoke(settings, output_dir=tmp_path / "first")
    second = run_ebbo_smoke(settings, output_dir=tmp_path / "second")

    assert first.replay_checksum == second.replay_checksum
    assert [pool.to_dict() for pool in first.pools] == [pool.to_dict() for pool in second.pools]
    assert [item.replay_dict() for item in first.scheduler.requests] == [
        item.replay_dict() for item in second.scheduler.requests
    ]
    assert [item.replay_dict() for item in first.scheduler.results] == [
        item.replay_dict() for item in second.scheduler.results
    ]
    assert [item.replay_dict() for item in first.observations] == [
        item.replay_dict() for item in second.observations
    ]
    assert first.ledger.replay_dict() == second.ledger.replay_dict()
    assert first.ledger.oracle_calls == first.ledger.evaluations_succeeded == 5
    assert first.ledger.evaluations_failed == 0
    assert first.ledger.candidate_proposals == 20
    assert first.ledger.known_cost == 5.0
    assert first.ledger.llm_calls == first.ledger.tokens == 0
    assert len(first.store.events) == 20
    assert len(first.store.observations) == 5

    expected = {
        "audit.jsonl",
        "candidate_pools.jsonl",
        "ledger.json",
        "manifest.json",
        "observations.jsonl",
        "posterior.json",
        "replay.json",
        "requests.jsonl",
        "results.jsonl",
        "summary.json",
    }
    assert {path.name for path in (tmp_path / "first").iterdir()} == expected
    manifest = json.loads((tmp_path / "first/manifest.json").read_text(encoding="utf-8"))
    assert manifest["network"] == "unused"
    assert manifest["financial_cost"] == 0.0


def test_ebbo_smoke_cli_reports_the_exact_separate_ledgers(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "roco_ebbo",
            "ebbo-smoke",
            "--config",
            str(root / "configs/smoke/ebbo_mock.yaml"),
            "--output-dir",
            str(tmp_path / "cli-ebbo"),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        text=True,
        timeout=30,
    )
    output = dict(line.split("=", 1) for line in completed.stdout.strip().splitlines())
    assert output["oracle_calls"] == "5"
    assert output["evaluations_succeeded"] == "5"
    assert output["evaluations_failed"] == "0"
    assert output["candidate_proposals"] == "20"
    assert output["known_cost"] == "5"
    assert output["cost_unit"] == "mock-evaluation-unit"
    assert output["llm_calls"] == output["tokens"] == output["financial_cost"] == "0"
    assert output["network"] == "unused"
    assert len(output["replay_checksum"]) == 64
