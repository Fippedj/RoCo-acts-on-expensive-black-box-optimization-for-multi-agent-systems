"""Offline P9b four-path control-flow and replay regression."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from roco_ebbo.ebbo.role_runtime import load_role_smoke_settings, run_role_smoke

P9A_REPLAY = "7d4b4da802d2cd4e29742b74fa9e3866b4ab319a27d207e1ce4c8e79fac5da01"


def test_four_paths_share_mock_contract_and_replay_exact_non_time_state(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    settings = load_role_smoke_settings(root / "configs/smoke/ebbo_role_mock.yaml")
    first = run_role_smoke(settings, output_dir=tmp_path / "first")
    second = run_role_smoke(settings, output_dir=tmp_path / "second")
    assert set(first) == {"full", "no_roles", "no_critic", "no_integrator"}
    assert first["no_roles"].replay_checksum == P9A_REPLAY
    expected_calls = {"full": 20, "no_roles": 0, "no_critic": 15, "no_integrator": 15}
    for mode in first:
        left, right = first[mode], second[mode]
        assert left.replay_checksum == right.replay_checksum
        assert [p.to_dict() for p in left.pools] == [p.to_dict() for p in right.pools]
        assert [r.replay_dict() for r in left.scheduler.requests] == [
            r.replay_dict() for r in right.scheduler.requests
        ]
        assert [r.replay_dict() for r in left.scheduler.results] == [
            r.replay_dict() for r in right.scheduler.results
        ]
        assert [o.replay_dict() for o in left.observations] == [
            o.replay_dict() for o in right.observations
        ]
        assert left.ledger.replay_dict() == right.ledger.replay_dict()
        assert left.ledger.oracle_calls == 5
        assert left.ledger.evaluations_succeeded == 5
        assert left.ledger.evaluations_failed == 0
        assert left.ledger.candidate_proposals == 20
        assert left.ledger.known_cost == 5.0
        assert left.ledger.llm_calls == expected_calls[mode]
        assert left.ledger.tokens == right.ledger.tokens
        assert left.ledger.max_oracle_calls == 5
        assert len(left.store.observations) == 5
        assert (tmp_path / "first" / mode / "role_summary.json").exists()
        assert (tmp_path / "first" / mode / "posterior.json").exists()
    matrix = json.loads((tmp_path / "first/matrix.json").read_text(encoding="utf-8"))
    assert matrix["network"] == "unused"
    assert matrix["modes"]["full"]["financial_cost"] == 0.0


def test_p9b_cli_exposes_only_offline_mock_matrix(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "roco_ebbo",
            "ebbo-role-smoke",
            "--config",
            str(root / "configs/smoke/ebbo_role_mock.yaml"),
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
    assert "mode=full oracle_calls=5" in completed.stdout
    assert "mode=no_roles oracle_calls=5" in completed.stdout
    assert "mode=no_critic oracle_calls=5" in completed.stdout
    assert "mode=no_integrator oracle_calls=5" in completed.stdout
    assert "financial_cost=0 network=unused" in completed.stdout
    assert P9A_REPLAY in completed.stdout
