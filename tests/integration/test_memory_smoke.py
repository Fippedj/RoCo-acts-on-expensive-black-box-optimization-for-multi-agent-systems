from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from roco_ebbo.memory import GenerationMemoryStore
from roco_ebbo.smoke import load_smoke_settings, run_smoke


def test_two_generation_memory_smoke_commits_and_replays_deterministically(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    settings = load_smoke_settings(repository_root / "configs/smoke/tsp_memory_mock.yaml")

    first = run_smoke(
        settings,
        memory_root=tmp_path / "first-memory",
        run_id="deterministic-memory-smoke",
    )
    second = run_smoke(
        settings,
        memory_root=tmp_path / "second-memory",
        run_id="deterministic-memory-smoke",
    )

    assert first.ledger.llm_calls == second.ledger.llm_calls == 44
    assert first.ledger.generated_candidates == second.ledger.generated_candidates == 28
    assert first.ledger.valid_evals == second.ledger.valid_evals == 28
    assert [candidate.id for candidate in first.result.population.candidates] == [
        candidate.id for candidate in second.result.population.candidates
    ]
    assert len(first.result.memory_traces) == len(second.result.memory_traces) == 2
    assert [trace.to_dict()["final_event_ids"] for trace in first.result.memory_traces] == [
        trace.to_dict()["final_event_ids"] for trace in second.result.memory_traces
    ]

    store = GenerationMemoryStore(tmp_path / "first-memory")
    report = store.scan()
    assert report.visible_generations == (0, 1)
    assert report.issues == ()
    assert len(report.records) == 2
    assert all(len(record.summaries) == 3 for record in report.records)
    assert all(record.commit.event_count == len(record.events) for record in report.records)

    first_trace, second_trace = first.result.memory_traces
    assert all(audit.selected_event_ids == () for audit in first_trace.retrieval_audits)
    for audit in second_trace.retrieval_audits:
        assert len(audit.selected_event_ids) <= 5
        selected = [
            event
            for event in report.records[0].events
            if event.event_id in audit.selected_event_ids
        ]
        assert all(event.role == audit.role for event in selected)
        assert all(event.benchmark == "tsp" and event.objective == "minimize" for event in selected)
    assert len(first_trace.truncation_audits) == len(second_trace.truncation_audits) == 3
    assert all(audit.final_size <= audit.limit for audit in first_trace.truncation_audits)
    assert all(audit.final_size <= audit.limit for audit in second_trace.truncation_audits)

    latest = report.records[-1]
    population_by_id = {item["id"]: item for item in latest.checkpoint.population["candidates"]}
    for event in latest.events:
        if event.success and event.output_candidate_id in population_by_id:
            metadata = population_by_id[event.output_candidate_id]["metadata"]
            if "memory_role" in metadata:
                summary = latest.summary(metadata["memory_role"])
                assert metadata["committed_summary_hash"] == summary.source_hash
                assert metadata["committed_summary_source_event_ids"] == list(
                    summary.source_event_ids
                )


def test_memory_cli_records_segment_summary_commit_retrieval_and_truncation(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    config = repository_root / "configs/smoke/tsp_memory_mock.yaml"
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
    assert output["llm_calls"] == "44"
    assert output["valid_evaluations"] == "28"
    assert output["budget_reached"] == "false"

    run_directory = runs_dir / output["run_id"]
    summary = json.loads((run_directory / "summary.json").read_text(encoding="utf-8"))
    assert summary["scope"] == "stage4-offline-reflection-memory-mock"
    assert summary["memory_enabled"] is True
    assert summary["memory_generations"] == 2
    trace_lines = (
        (run_directory / summary["memory_runtime_trace"]).read_text(encoding="utf-8").splitlines()
    )
    assert len(trace_lines) == 2
    traces = [json.loads(line) for line in trace_lines]
    assert all(len(trace["summary_attempts"]) == 3 for trace in traces)
    assert all(len(trace["retrieval"]) == 3 for trace in traces)
    assert all(len(trace["truncation"]) == 3 for trace in traces)

    memory_root = run_directory / summary["memory_root"]
    assert len(list((memory_root / "events").glob("*.jsonl"))) == 2
    assert len(list((memory_root / "summaries").glob("*.json"))) == 6
    assert len(list((memory_root / "checkpoints").glob("*.json"))) == 2
    assert len(list((memory_root / "commits").glob("*.json"))) == 2
