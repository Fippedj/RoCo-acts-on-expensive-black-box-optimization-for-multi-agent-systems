from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from roco_ebbo.memory import GenerationMemoryStore
from roco_ebbo.smoke import (
    MemoryResumeError,
    load_smoke_settings,
    resume_smoke,
    run_memory_ablation,
    run_smoke,
)


def _settings():
    root = Path(__file__).resolve().parents[2]
    return load_smoke_settings(root / "configs/smoke/tsp_memory_mock.yaml")


def _without_runtime_seconds(value: Any) -> Any:
    if isinstance(value, list):
        return [_without_runtime_seconds(item) for item in value]
    if isinstance(value, dict):
        return {
            key: (0.0 if key == "runtime_seconds" else _without_runtime_seconds(item))
            for key, item in value.items()
        }
    return value


def _commit_documents(root: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((root / "commits").glob("*.json"))
    ]


def test_interrupted_resume_is_hash_equivalent_without_recomputing_commits(
    tmp_path: Path,
) -> None:
    settings = _settings()
    run_id = "p4-recovery-equivalence"
    full_root = tmp_path / "full"
    resumed_root = tmp_path / "resumed"

    uninterrupted = run_smoke(settings, memory_root=full_root, run_id=run_id)
    interrupted = run_smoke(
        settings,
        memory_root=resumed_root,
        run_id=run_id,
        interrupt_after_committed_generation=1,
    )

    assert interrupted.result.interrupted_after_generation == 1
    assert interrupted.result.generations_completed == 1
    assert interrupted.ledger.llm_calls == 24
    assert interrupted.ledger.generated_candidates == interrupted.ledger.valid_evals == 16
    generation_zero_before = {
        path.relative_to(resumed_root).as_posix(): path.read_bytes()
        for directory in ("events", "summaries", "checkpoints", "commits")
        for path in (resumed_root / directory).glob("generation-000000*")
    }
    temporary = resumed_root / "events" / ".generation-000001.crash.tmp"
    orphan = resumed_root / "summaries" / "unrecognized-orphan"
    temporary.write_text("partial", encoding="utf-8")
    orphan.write_text("partial", encoding="utf-8")

    resumed = resume_smoke(settings, memory_root=resumed_root, run_id=run_id)

    assert resumed.result.resumed_from_generation == 1
    assert resumed.result.generations_completed == 2
    assert resumed.ledger.llm_calls == uninterrupted.ledger.llm_calls == 44
    assert resumed.ledger.generated_candidates == uninterrupted.ledger.generated_candidates == 28
    assert resumed.ledger.valid_evals == uninterrupted.ledger.valid_evals == 28
    resumed_budget = resumed.ledger.to_snapshot()
    uninterrupted_budget = uninterrupted.ledger.to_snapshot()
    resumed_budget["wall_time"] = uninterrupted_budget["wall_time"] = 0.0
    assert resumed_budget == uninterrupted_budget
    assert _without_runtime_seconds(resumed.result.population.to_snapshot()) == (
        _without_runtime_seconds(uninterrupted.result.population.to_snapshot())
    )
    assert resumed.resume_audit is not None
    assert resumed.resume_audit.recovered_memory_generation == 0
    assert resumed.resume_audit.next_engine_generation == 2
    assert {issue["code"] for issue in resumed.resume_audit.ignored_store_issues} == {
        "orphan_artifact",
        "temporary_artifact",
    }
    assert temporary.read_text(encoding="utf-8") == "partial"
    assert orphan.read_text(encoding="utf-8") == "partial"

    generation_zero_after = {
        path.relative_to(resumed_root).as_posix(): path.read_bytes()
        for directory in ("events", "summaries", "checkpoints", "commits")
        for path in (resumed_root / directory).glob("generation-000000*")
    }
    assert generation_zero_after == generation_zero_before

    full_store = GenerationMemoryStore(full_root)
    resumed_store = GenerationMemoryStore(resumed_root)
    for generation in (0, 1):
        full = full_store.read_generation(generation)
        recovered = resumed_store.read_generation(generation)
        assert recovered.events == full.events
        assert recovered.summaries == full.summaries
        assert recovered.checkpoint.to_dict() == full.checkpoint.to_dict()
        assert recovered.commit.to_dict() == full.commit.to_dict()
        if generation == 1:
            assert recovered.commit.population_ids == tuple(
                candidate.id for candidate in resumed.result.population.candidates
            )
    assert _commit_documents(resumed_root) == _commit_documents(full_root)
    final_checkpoint = resumed_store.read_generation(1).checkpoint
    assert (
        final_checkpoint.provider_snapshots
        == full_store.read_generation(1).checkpoint.provider_snapshots
    )
    assert (
        final_checkpoint.random_streams == full_store.read_generation(1).checkpoint.random_streams
    )


def test_resume_ignores_half_written_next_generation_without_deleting_it(tmp_path: Path) -> None:
    settings = _settings()
    memory_root = tmp_path / "memory"
    run_smoke(
        settings,
        memory_root=memory_root,
        run_id="half-write",
        interrupt_after_committed_generation=1,
    )
    half_written = memory_root / "events" / "generation-000001.jsonl.partial.tmp"
    half_written.write_text("partial", encoding="utf-8")

    resumed = resume_smoke(settings, memory_root=memory_root, run_id="half-write")

    assert resumed.ledger.llm_calls == 44
    assert half_written.read_text(encoding="utf-8") == "partial"
    assert resumed.resume_audit is not None
    assert any(
        issue["code"] == "temporary_artifact" for issue in resumed.resume_audit.ignored_store_issues
    )


def test_resume_rejects_missing_commit_bad_hash_and_generation_gap(tmp_path: Path) -> None:
    settings = _settings()
    source = tmp_path / "source"
    run_smoke(
        settings,
        memory_root=source,
        run_id="damaged",
        interrupt_after_committed_generation=1,
    )

    missing = tmp_path / "missing"
    shutil.copytree(source, missing)
    (missing / "commits" / "generation-000000.json").unlink()
    with pytest.raises(MemoryResumeError) as missing_error:
        resume_smoke(settings, memory_root=missing, run_id="damaged")
    assert missing_error.value.code == "missing_commit"

    bad_hash = tmp_path / "bad-hash"
    shutil.copytree(source, bad_hash)
    event_path = bad_hash / "events" / "generation-000000.jsonl"
    event_path.write_bytes(event_path.read_bytes() + b"{}\n")
    with pytest.raises(MemoryResumeError) as hash_error:
        resume_smoke(settings, memory_root=bad_hash, run_id="damaged")
    assert hash_error.value.code == "bad_hash"
    assert hash_error.value.to_dict()["details"]["path"].endswith(".jsonl")

    complete = tmp_path / "complete"
    run_smoke(settings, memory_root=complete, run_id="damaged")
    (complete / "commits" / "generation-000000.json").unlink()
    with pytest.raises(MemoryResumeError) as gap_error:
        resume_smoke(settings, memory_root=complete, run_id="damaged")
    assert gap_error.value.code == "noncontinuous_generation"


def test_resume_rejects_incompatible_seed_and_config(tmp_path: Path) -> None:
    settings = _settings()
    memory_root = tmp_path / "memory"
    run_smoke(
        settings,
        memory_root=memory_root,
        run_id="compatibility",
        interrupt_after_committed_generation=1,
    )

    with pytest.raises(MemoryResumeError) as seed_error:
        resume_smoke(
            replace(settings, seed=settings.seed + 1),
            memory_root=memory_root,
            run_id="compatibility",
        )
    assert seed_error.value.code == "seed_mismatch"

    changed_snapshot = json.loads(json.dumps(settings.config_snapshot))
    changed_snapshot["memory"]["max_context_characters"] += 1
    changed = replace(
        settings,
        memory_max_context_characters=settings.memory_max_context_characters + 1,
        config_snapshot=changed_snapshot,
    )
    with pytest.raises(MemoryResumeError) as config_error:
        resume_smoke(changed, memory_root=memory_root, run_id="compatibility")
    assert config_error.value.code == "config_mismatch"


def test_memory_ablation_preserves_roco_off_boundary_and_records_budget(tmp_path: Path) -> None:
    paired = run_memory_ablation(
        _settings(),
        memory_root=tmp_path / "memory-on",
        run_id="p4-ablation",
    )

    off = paired.memory_off
    on = paired.memory_on
    assert (off.ledger.llm_calls, off.ledger.generated_candidates, off.ledger.valid_evals) == (
        32,
        22,
        22,
    )
    assert (on.ledger.llm_calls, on.ledger.generated_candidates, on.ledger.valid_evals) == (
        44,
        28,
        28,
    )
    assert off.memory_root is None
    assert off.result.memory_traces == ()
    assert not any(
        candidate.operator.startswith("memory_") for candidate in off.result.all_candidates
    )
    assert len(on.result.memory_traces) == 2
    assert any(candidate.operator.startswith("memory_") for candidate in on.result.all_candidates)
    assert GenerationMemoryStore(tmp_path / "memory-on").scan().visible_generations == (0, 1)
