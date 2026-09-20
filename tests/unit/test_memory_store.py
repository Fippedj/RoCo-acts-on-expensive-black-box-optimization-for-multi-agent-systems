from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pytest

from roco_ebbo.core import BudgetLedger, Candidate
from roco_ebbo.evolution import Population
from roco_ebbo.llm import MockLLMProvider
from roco_ebbo.memory.models import MemoryEvent, RoleMemorySummary
from roco_ebbo.memory.store import (
    GenerationMemoryStore,
    MemoryCheckpoint,
    StoreConflictError,
    StoreValidationError,
)


def _candidate(candidate_id: str, score: float) -> Candidate:
    return Candidate(
        id=candidate_id,
        description=f"candidate {candidate_id}",
        code="def heuristic(distance_matrix):\n    return list(range(len(distance_matrix)))\n",
        parents=("seed",),
        operator="explorer",
        generation=0,
        score=score,
        metadata={"evaluation": {"valid": True, "score": score}},
    )


def _population() -> Population:
    return Population(
        candidates=[_candidate("candidate-a", 4.0), _candidate("candidate-b", 5.0)],
        size=2,
        minimize=True,
    )


def _ledger() -> BudgetLedger:
    ledger = BudgetLedger(
        max_llm_calls=100,
        max_tokens=10_000,
        max_generated_candidates=50,
        max_valid_evals=50,
    )
    ledger.consume(
        llm_calls=3,
        input_tokens=12,
        output_tokens=6,
        generated_candidates=2,
        valid_evals=2,
    )
    return ledger


def _event(generation: int, *, selected: bool = True) -> MemoryEvent:
    return MemoryEvent.create(
        run_id="run-store",
        benchmark="tsp",
        objective="minimize",
        generation=generation,
        round_index=1,
        sequence=0,
        role="explorer",
        event_kind="mutation",
        source_trace_event_ids=(f"trace-{generation}",),
        parent_candidate_ids=("candidate-b",),
        output_candidate_id="candidate-a",
        before_score=5.0,
        after_score=4.0,
        success=True,
        selected_in_population=selected,
        feedback="keep the bounded change",
        budget_before={"llm_calls": 2, "valid_evals": 1},
        budget_after={"llm_calls": 3, "valid_evals": 2},
        prompt_version="roco-role-prompts-v1",
        provider_name="mock",
        model_name="deterministic",
    )


def _summaries(event: MemoryEvent) -> dict[str, RoleMemorySummary]:
    return {
        role: RoleMemorySummary.create(
            role=role,
            through_generation=event.generation,
            source_event_ids=(event.event_id,),
            prompt_version="ltreflect-v1",
            provider_name="mock",
            model_name="deterministic",
            useful_strategies=(f"{role} bounded change",),
            failure_patterns=(),
            applicability_conditions=("finite objective",),
            avoid_patterns=("unbounded loops",),
        )
        for role in ("explorer", "exploiter", "integrator")
    }


def _checkpoint(generation: int) -> MemoryCheckpoint:
    provider = MockLLMProvider(seed=31)
    return MemoryCheckpoint.create(
        generation,
        _population(),
        _ledger(),
        random_streams={"collaboration": {"seed": 17, "draws": 2}},
        provider_snapshots={"mock": provider.to_snapshot()},
    )


def _config_hash() -> str:
    return hashlib.sha256(b'{"memory":"v1"}').hexdigest()


def _commit(store: GenerationMemoryStore, generation: int):
    event = _event(generation)
    result = store.commit_generation(
        generation,
        (event,),
        _summaries(event),
        _checkpoint(generation),
        _config_hash(),
    )
    return result, event


def _artifact_path(root: Path, commit_path: Path, suffix: str) -> Path:
    marker = json.loads(commit_path.read_text(encoding="utf-8"))
    artifact = next(item for item in marker["artifacts"].values() if item["path"].endswith(suffix))
    return root / artifact["path"]


def test_generation_commit_writes_canonical_artifacts_and_reads_them_back(
    tmp_path: Path,
) -> None:
    store = GenerationMemoryStore(tmp_path)

    result, event = _commit(store, 0)
    record = store.read_generation(0)

    assert result.generation == 0
    assert result.idempotent is False
    assert result.commit_path.exists()
    assert record.events == (event,)
    assert record.summaries == _summaries(event)
    assert record.checkpoint.to_dict() == _checkpoint(0).to_dict()

    event_path = _artifact_path(tmp_path, result.commit_path, ".jsonl")
    event_bytes = event_path.read_bytes()
    assert event_bytes.endswith(b"\n")
    assert event_bytes.count(b"\n") == 1
    assert MemoryEvent.from_json(event_bytes.rstrip(b"\n")) == event

    marker = json.loads(result.commit_path.read_text(encoding="utf-8"))
    assert marker["generation"] == 0
    assert marker["event_count"] == 1
    assert marker["config_hash"] == _config_hash()
    assert len(marker["artifacts"]) == 5
    for artifact in marker["artifacts"].values():
        relative = Path(artifact["path"])
        assert not relative.is_absolute()
        assert ".." not in relative.parts
        content = (tmp_path / relative).read_bytes()
        assert artifact["byte_length"] == len(content)
        assert artifact["sha256"] == hashlib.sha256(content).hexdigest()


def test_checkpoint_round_trip_restores_population_ledger_and_portable_cursors() -> None:
    checkpoint = _checkpoint(4)
    encoded = json.dumps(checkpoint.to_dict(), allow_nan=False, sort_keys=True)

    restored_checkpoint = MemoryCheckpoint.from_json(encoded)
    restored_population, restored_ledger = restored_checkpoint.restore()

    assert restored_checkpoint == checkpoint
    assert restored_population.to_snapshot() == _population().to_snapshot()
    assert restored_ledger.to_snapshot() == _ledger().to_snapshot()
    assert restored_checkpoint.random_streams == {"collaboration": {"seed": 17, "draws": 2}}
    assert restored_checkpoint.provider_snapshots["mock"] == MockLLMProvider(seed=31).to_snapshot()

    with pytest.raises(ValueError, match="JSON|non-finite|non-JSON"):
        MemoryCheckpoint.create(
            4,
            _population(),
            _ledger(),
            random_streams={"private_random_state": random.Random(1).getstate()},
        )


def test_repeated_commit_is_idempotent_but_changed_content_conflicts(tmp_path: Path) -> None:
    store = GenerationMemoryStore(tmp_path)
    first, event = _commit(store, 0)

    repeated = store.commit_generation(
        0,
        (event,),
        _summaries(event),
        _checkpoint(0),
        _config_hash(),
    )

    assert repeated.idempotent is True
    assert repeated.commit_path == first.commit_path

    changed = _event(0, selected=False)
    with pytest.raises(StoreConflictError):
        store.commit_generation(
            0,
            (changed,),
            _summaries(changed),
            _checkpoint(0),
            _config_hash(),
        )


def test_event_id_collision_fails_closed_before_any_commit_is_published(
    tmp_path: Path,
) -> None:
    store = GenerationMemoryStore(tmp_path)
    first = _event(0)
    different_content = _event(0, selected=False)
    object.__setattr__(different_content, "event_id", first.event_id)

    with pytest.raises(StoreConflictError, match="collision"):
        store.commit_generation(
            0,
            (first, different_content),
            _summaries(first),
            _checkpoint(0),
            _config_hash(),
        )

    assert not (tmp_path / "commits" / "generation-000000.json").exists()


def test_tampered_single_event_fails_before_any_commit_is_published(tmp_path: Path) -> None:
    store = GenerationMemoryStore(tmp_path)
    event = _event(0)
    object.__setattr__(event, "event_id", "mem-00000000000000000000")

    with pytest.raises(ValueError, match="event_id"):
        store.commit_generation(
            0,
            (event,),
            _summaries(_event(0)),
            _checkpoint(0),
            _config_hash(),
        )

    assert not (tmp_path / "commits" / "generation-000000.json").exists()


def test_missing_commit_hides_orphan_artifacts_and_reports_them(tmp_path: Path) -> None:
    store = GenerationMemoryStore(tmp_path)
    result, _ = _commit(store, 0)
    result.commit_path.unlink()

    report = store.scan()

    assert report.visible_generations == ()
    assert report.records == ()
    rendered = " ".join(str(issue).lower() for issue in report.issues)
    assert "commit" in rendered
    assert "orphan" in rendered or "artifact" in rendered


def test_hash_mismatch_makes_generation_invisible_and_is_reported(tmp_path: Path) -> None:
    store = GenerationMemoryStore(tmp_path)
    result, _ = _commit(store, 0)
    event_path = _artifact_path(tmp_path, result.commit_path, ".jsonl")
    event_path.write_bytes(event_path.read_bytes() + b"{}\n")

    report = store.scan()

    assert report.visible_generations == ()
    assert report.records == ()
    assert "hash" in " ".join(str(issue).lower() for issue in report.issues)


def test_temp_file_is_ignored_and_reported_without_becoming_visible(tmp_path: Path) -> None:
    store = GenerationMemoryStore(tmp_path)
    temp_path = tmp_path / "events" / "generation-000000.jsonl.crash.tmp"
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_text("partial", encoding="utf-8")

    report = store.scan()

    assert report.visible_generations == ()
    assert "tmp" in " ".join(str(issue).lower() for issue in report.issues)


def test_scan_stops_at_first_gap_and_recovery_uses_last_contiguous_checkpoint(
    tmp_path: Path,
) -> None:
    store = GenerationMemoryStore(tmp_path)
    first, _ = _commit(store, 0)
    second, _ = _commit(store, 1)
    third, _ = _commit(store, 2)
    assert first.commit_path.exists() and third.commit_path.exists()
    second.commit_path.unlink()

    report = store.scan()
    recovery = store.recover()

    assert report.visible_generations == (0,)
    assert [record.generation for record in report.records] == [0]
    rendered = " ".join(str(issue).lower() for issue in report.issues)
    assert "generation" in rendered and ("gap" in rendered or "continuous" in rendered)
    assert recovery is not None
    assert recovery.next_generation == 1
    assert recovery.population.to_snapshot() == _population().to_snapshot()
    assert recovery.budget_ledger.to_snapshot() == _ledger().to_snapshot()
    assert recovery.provider_snapshots == {"mock": MockLLMProvider(seed=31).to_snapshot()}

    with pytest.raises(StoreValidationError, match="not visible"):
        store.read_generation(2)


def test_recover_returns_none_when_no_generation_is_committed(tmp_path: Path) -> None:
    store = GenerationMemoryStore(tmp_path)

    assert store.recover() is None
