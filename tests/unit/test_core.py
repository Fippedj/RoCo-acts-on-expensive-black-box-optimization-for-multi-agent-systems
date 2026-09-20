from __future__ import annotations

import json
from pathlib import Path

import pytest

from roco_ebbo.core import (
    BudgetExceededError,
    BudgetLedger,
    Candidate,
    EvaluationResult,
    RunManifest,
)


def test_candidate_and_evaluation_result_are_json_serializable() -> None:
    candidate = Candidate(
        id="candidate-1",
        description="identity tour",
        code="def heuristic(distance_matrix):\n    return list(range(len(distance_matrix)))\n",
        parents=("parent-1",),
        operator="E1",
        generation=2,
        score=3.5,
        metadata={"valid": True},
    )
    evaluation = EvaluationResult(score=3.5, valid=True, runtime_seconds=0.01)

    assert json.loads(candidate.to_json())["parents"] == ["parent-1"]
    assert json.loads(evaluation.to_json())["score"] == 3.5


def test_budget_ledger_rejects_after_limit_and_does_not_partially_commit() -> None:
    ledger = BudgetLedger(max_llm_calls=1, max_tokens=10, max_valid_evals=2)
    ledger.consume(llm_calls=1, input_tokens=2, output_tokens=3, generated_candidates=1)

    assert ledger.llm_calls == 1
    assert ledger.tokens == 5
    assert ledger.reached_limits == ("llm_calls",)
    with pytest.raises(BudgetExceededError, match="already reached"):
        ledger.consume(valid_evals=1)
    assert ledger.valid_evals == 0

    fresh = BudgetLedger(max_tokens=4)
    with pytest.raises(BudgetExceededError, match="would exceed"):
        fresh.consume(input_tokens=2, output_tokens=3)
    assert fresh.tokens == 0


def test_budget_ledger_settles_an_accepted_call_even_when_reported_usage_crosses_limit() -> None:
    ledger = BudgetLedger(max_llm_calls=1, max_tokens=5, max_cost=0.5)
    ledger.ensure_can_start(llm_calls=1, input_tokens=2, output_tokens=3, cost=0.5)

    ledger.settle_accepted_llm_call(
        input_tokens=3,
        output_tokens=3,
        cost=0.6,
    )

    assert ledger.llm_calls == 1
    assert ledger.tokens == 6
    assert ledger.cost == 0.6
    assert ledger.exceeded_limits == ("tokens", "cost")


def test_budget_ledger_does_not_fabricate_missing_accepted_usage() -> None:
    ledger = BudgetLedger(max_llm_calls=2)

    ledger.settle_accepted_llm_call()

    assert ledger.llm_calls == 1
    assert ledger.input_tokens == ledger.output_tokens == 0
    assert ledger.cost == 0.0


def test_run_manifest_serialization_and_write(tmp_path: Path) -> None:
    manifest = RunManifest(
        seed=7,
        git_sha=None,
        config_snapshot={"llm": {"provider": "mock"}},
        environment_information={"python": "3.11"},
        budget_snapshot=BudgetLedger(max_llm_calls=20).to_dict(),
    )
    output = tmp_path / "manifest.json"
    manifest.write_json(output)

    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded == json.loads(manifest.to_json())
    assert loaded["git_sha"] is None
