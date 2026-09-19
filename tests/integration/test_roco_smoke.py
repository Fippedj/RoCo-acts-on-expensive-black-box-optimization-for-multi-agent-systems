from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from roco_ebbo.smoke import load_smoke_settings, run_smoke


def test_roco_mock_smoke_writes_generation_trace(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    config = repository_root / "configs" / "smoke" / "tsp_roco_mock.yaml"
    settings = load_smoke_settings(config)
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
        env={**os.environ, "PYTHONPATH": str(repository_root / "src")},
        text=True,
        timeout=60,
    )

    output = dict(line.split("=", 1) for line in completed.stdout.strip().splitlines())
    assert settings.mode == "roco"
    assert settings.collaboration_rounds == 2
    assert output["mode"] == "roco"
    assert output["valid_evaluations"] == "13"
    assert output["llm_calls"] == "18"
    assert output["budget_reached"] == "false"

    run_directory = runs_dir / output["run_id"]
    summary = json.loads((run_directory / "summary.json").read_text(encoding="utf-8"))
    trace_path = run_directory / summary["collaboration_trace"]
    trace_lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert summary["scope"] == "stage3-generation-local-roco-mock"
    assert summary["collaboration_generations"] == 1
    assert Path(output["collaboration_trace"]) == trace_path
    assert len(trace_lines) == 1

    trace = json.loads(trace_lines[0])
    counts = Counter(event["role"] for event in trace["events"])
    assert trace["schema_version"] == "roco-collaboration-trace-v1"
    assert trace["scope"] == "generation-local"
    assert trace["rounds_requested"] == 2
    assert trace["rounds_completed"] == 2
    assert not trace["stopped_on_budget"]
    assert len(trace["elite_pair"]) == 2
    assert len(trace["selected_candidate_ids"]) == settings.population_size
    assert counts == {"explorer": 2, "exploiter": 2, "critic": 5, "integrator": 1}
    assert all(event["status"] == "success" for event in trace["events"])


def test_legacy_smoke_config_keeps_explicit_stage2_dispatch() -> None:
    repository_root = Path(__file__).resolve().parents[2]

    settings = load_smoke_settings(repository_root / "configs" / "smoke" / "tsp_mock.yaml")

    # The existing Stage 2 integration/CLI tests execute this path; keep this check cheap here.
    assert settings.mode == "eoh"
    assert settings.collaboration_rounds == 1


def test_two_generation_roco_trace_and_sampling_are_replayable() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    base = load_smoke_settings(repository_root / "configs" / "smoke" / "tsp_roco_mock.yaml")
    settings = replace(base, generations=2)

    first = run_smoke(settings)
    second = run_smoke(settings)

    assert first.result.generations_completed == second.result.generations_completed == 2
    assert first.ledger.llm_calls == second.ledger.llm_calls == 32
    assert first.ledger.generated_candidates == second.ledger.generated_candidates == 22
    assert first.ledger.valid_evals == second.ledger.valid_evals == 22
    assert len(first.result.collaboration_traces) == 2
    assert [trace.generation for trace in first.result.collaboration_traces] == [1, 2]
    assert [trace.elite_pair_ranks for trace in first.result.collaboration_traces] == [
        trace.elite_pair_ranks for trace in second.result.collaboration_traces
    ]
    assert [
        tuple(candidate["id"] for candidate in trace.elite_pair)
        for trace in first.result.collaboration_traces
    ] == [
        tuple(candidate["id"] for candidate in trace.elite_pair)
        for trace in second.result.collaboration_traces
    ]
    event_ids = [
        event.event_id for trace in first.result.collaboration_traces for event in trace.events
    ]
    assert len(event_ids) == len(set(event_ids)) == 20
    assert all(
        event.event_id.startswith(f"g{trace.generation}-")
        for trace in first.result.collaboration_traces
        for event in trace.events
    )
    assert all(
        len(trace.selected_candidate_ids) == settings.population_size
        for trace in first.result.collaboration_traces
    )
    assert [candidate.id for candidate in first.result.population.candidates] == [
        candidate.id for candidate in second.result.population.candidates
    ]


@pytest.mark.parametrize(
    ("max_llm_calls", "max_valid_evals", "expected_calls", "expected_valid_evals"),
    [
        (9, 40, 9, 8),
        (50, 9, 10, 9),
    ],
)
def test_roco_smoke_stops_safely_on_different_mid_collaboration_budgets(
    max_llm_calls: int,
    max_valid_evals: int,
    expected_calls: int,
    expected_valid_evals: int,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    base = load_smoke_settings(repository_root / "configs" / "smoke" / "tsp_roco_mock.yaml")
    settings = replace(
        base,
        max_llm_calls=max_llm_calls,
        max_valid_evals=max_valid_evals,
    )

    smoke_run = run_smoke(settings)

    assert smoke_run.result.stopped_on_budget
    assert smoke_run.result.generations_completed == 1
    assert smoke_run.ledger.llm_calls == expected_calls
    assert smoke_run.ledger.valid_evals == expected_valid_evals
    assert len(smoke_run.result.collaboration_traces) == 1
    trace = smoke_run.result.collaboration_traces[0]
    assert trace.stopped_on_budget
    assert trace.events[-1].status == "budget_exhausted"
    assert len(trace.selected_candidate_ids) == settings.population_size


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("evolution", "elite_sampling_power"), float("nan"), "elite_sampling_power"),
        (("llm", "temperatures", "explorer"), float("inf"), "role temperatures"),
        (("benchmark", "evaluator_timeout_seconds"), float("nan"), "timeout_seconds"),
    ],
)
def test_roco_config_rejects_non_finite_values(
    tmp_path: Path,
    path: tuple[str, ...],
    value: float,
    message: str,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source = repository_root / "configs" / "smoke" / "tsp_roco_mock.yaml"
    raw: dict[str, Any] = yaml.safe_load(source.read_text(encoding="utf-8"))
    target = raw
    for key in path[:-1]:
        nested = target[key]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value
    config = tmp_path / "invalid.yaml"
    config.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_smoke_settings(config)
