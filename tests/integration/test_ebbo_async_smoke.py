"""P9c offline end-to-end replay, explicit interruption, and CLI evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from roco_ebbo.ebbo.async_runtime import load_async_smoke_settings, run_async_smoke
from roco_ebbo.ebbo.oracle import MockOracleOutcome

P9C_REPLAY = "085fac4aa00ca567f055ab87b87084c896cfd463d5eb7a51741ccbae84e0e47f"


def _settings() -> tuple[Path, object]:
    root = Path(__file__).resolve().parents[2]
    return root, load_async_smoke_settings(root / "configs/smoke/ebbo_async_mock.yaml")


def test_uninterrupted_and_all_checkpoint_boundary_resumes_are_identical(tmp_path: Path) -> None:
    _, settings = _settings()
    full = run_async_smoke(settings, output_dir=tmp_path / "full")
    assert full.complete
    assert full.replay_checksum == P9C_REPLAY
    assert full.summary()["network"] == "unused"
    assert full.ledger.oracle_calls == 5
    assert full.ledger.evaluations_succeeded == 3
    assert full.ledger.evaluations_failed == 2
    assert full.ledger.failure_breakdown == {
        "cancelled_after_accept": 1,
        "mock_timeout": 1,
    }
    assert full.ledger.candidate_proposals == 20
    assert full.ledger.known_cost == 5.0
    assert full.ledger.llm_calls == full.ledger.tokens == 0
    assert [o.logical_evaluation_index for o in full.scheduler.store.observations] != list(range(5))
    assert all(
        o.objective is None
        for o in full.scheduler.store.observations
        if o.status.value != "succeeded"
    )

    for boundary in (1, 2, 3, 4, 5, 8, 12):
        directory = tmp_path / f"resume-{boundary}"
        partial = run_async_smoke(settings, output_dir=directory, interrupt_after=boundary)
        assert not partial.complete
        assert (directory / "checkpoint.json").is_file()
        resumed = run_async_smoke(settings, output_dir=directory, resume=True)
        assert resumed.complete
        assert resumed.replay_checksum == full.replay_checksum
        assert (
            resumed.scheduler.store.semantic_snapshot() == full.scheduler.store.semantic_snapshot()
        )
        assert resumed.ledger.replay_dict() == full.ledger.replay_dict()
        assert [p.to_dict() for p in resumed.scheduler.pools] == [
            p.to_dict() for p in full.scheduler.pools
        ]
        assert [r.replay_dict() for r in resumed.scheduler.requests] == [
            r.replay_dict() for r in full.scheduler.requests
        ]
        assert [r.replay_dict() for r in resumed.scheduler.results] == [
            r.replay_dict() for r in full.scheduler.results
        ]
        assert [e.replay_dict() for e in resumed.scheduler.store.events] == [
            e.replay_dict() for e in full.scheduler.store.events
        ]
        assert (
            len([e for e in resumed.scheduler.store.events if e.kind == "async_oracle_accepted"])
            == 5
        )
        assert not resumed.scheduler.pending


def test_runtime_stops_new_admission_at_mock_cost_ceiling_and_drains_pending(
    tmp_path: Path,
) -> None:
    _, settings = _settings()
    baseline_snapshot = deepcopy(settings.baseline.config_snapshot)
    run = baseline_snapshot["run"]
    assert isinstance(run, dict)
    budgets = run["budgets"]
    assert isinstance(budgets, dict)
    budgets["max_cost"] = 2.0
    baseline = replace(settings.baseline, max_cost=2.0, config_snapshot=baseline_snapshot)
    outcomes = {x: MockOracleOutcome("success", actual_cost=2.0) for x in range(-5, 6)}
    changed = replace(settings, baseline=baseline, outcomes=outcomes)
    result = run_async_smoke(changed, output_dir=tmp_path / "overrun")
    assert result.complete
    assert result.ledger.oracle_calls == 2
    assert result.ledger.evaluations_total == 2
    assert result.ledger.known_cost == 4.0
    assert result.ledger.exceeded_limits == ("cost",)
    assert not result.scheduler.pending


def test_p9c_cli_emits_only_mock_ledgers_and_replay(tmp_path: Path) -> None:
    root, _ = _settings()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "roco_ebbo",
            "ebbo-async-smoke",
            "--config",
            str(root / "configs/smoke/ebbo_async_mock.yaml"),
            "--output-dir",
            str(tmp_path / "cli"),
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
    assert output["evaluations_succeeded"] == "3"
    assert output["evaluations_failed"] == "2"
    assert output["llm_calls"] == output["tokens"] == "0"
    assert output["network"] == "unused"
    assert output["replay_checksum"] == P9C_REPLAY
    summary = json.loads((tmp_path / "cli/summary.json").read_text(encoding="utf-8"))
    assert summary["scope"] == "offline-fake-async-engineering-only-not-performance-evidence"
    assert summary["financial_cost"] == 0.0
