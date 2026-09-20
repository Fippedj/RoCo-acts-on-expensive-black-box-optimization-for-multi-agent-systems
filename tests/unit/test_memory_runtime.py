from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from roco_ebbo.benchmarks import generate_symmetric_distance_matrix
from roco_ebbo.core import BudgetLedger, Candidate
from roco_ebbo.evaluation import TSPCodeEvaluator
from roco_ebbo.evolution import EoHEngine, Population, RoCoCollaborator
from roco_ebbo.llm import (
    GeneratedHeuristic,
    MemoryMutationRequest,
    MemorySummaryRequest,
    MockLLMProvider,
    RoCoRole,
    RoleResponse,
)
from roco_ebbo.memory import (
    GenerationMemoryStore,
    MemoryCheckpoint,
    MemoryEvent,
    MemoryRuntime,
    RoleMemorySummary,
    assemble_memory_prompt,
    retrieve_committed_events,
)


def _candidate(candidate_id: str, score: float) -> Candidate:
    return Candidate(
        id=candidate_id,
        description=f"candidate {candidate_id}",
        code="def heuristic(distance_matrix):\n    return list(range(len(distance_matrix)))\n",
        parents=("seed",),
        operator="seed",
        generation=0,
        score=score,
        metadata={"evaluation": {"valid": True, "score": score}},
    )


def _event(
    sequence: int,
    *,
    role: str = "explorer",
    benchmark: str = "tsp",
    improved: bool = True,
) -> MemoryEvent:
    before = 10.0
    after = 9.0 if improved else 11.0
    return MemoryEvent.create(
        run_id="runtime-test",
        benchmark=benchmark,
        objective="minimize",
        generation=0,
        round_index=sequence,
        sequence=sequence,
        role=role,
        event_kind="mutation",
        source_trace_event_ids=(f"trace-{role}-{benchmark}-{sequence}",),
        parent_candidate_ids=("parent",),
        output_candidate_id=f"child-{role}-{benchmark}-{sequence}",
        before_score=before,
        after_score=after,
        success=True,
        selected_in_population=False,
        feedback="bounded evidence " + ("x" * 200),
        budget_before={"llm_calls": sequence},
        budget_after={"llm_calls": sequence + 1},
        prompt_version="test-v1",
        provider_name="mock",
        model_name="deterministic",
    )


def _summaries(generation: int) -> dict[str, RoleMemorySummary]:
    return {
        role: RoleMemorySummary.create(
            role=role,
            through_generation=generation,
            source_event_ids=(),
            prompt_version="roco-ltreflect-v1",
            provider_name="mock",
            model_name="deterministic",
        )
        for role in ("explorer", "exploiter", "integrator")
    }


def _commit_events(store: GenerationMemoryStore, events: tuple[MemoryEvent, ...]) -> None:
    population = Population([_candidate("a", 1.0), _candidate("b", 2.0)], 2)
    ledger = BudgetLedger(max_llm_calls=100, max_valid_evals=100)
    store.commit_generation(
        0,
        events,
        _summaries(0),
        MemoryCheckpoint.create(0, population, ledger),
        hashlib.sha256(b"runtime-test-config").hexdigest(),
    )


def test_retrieval_enforces_three_two_quota_supplement_and_scope(tmp_path: Path) -> None:
    store = GenerationMemoryStore(tmp_path)
    explorer = tuple(_event(index, improved=index < 4) for index in range(6))
    integrator = tuple(
        _event(index + 6, role="integrator", improved=index == 0) for index in range(5)
    )
    out_of_scope = (
        _event(11, role="exploiter"),
        _event(12, benchmark="cvrp"),
    )
    _commit_events(store, (*explorer, *integrator, *out_of_scope))

    selected, audit = retrieve_committed_events(
        store,
        generation=1,
        role="explorer",
        benchmark="tsp",
        objective="minimize",
    )

    assert len(selected) == 5
    assert sum(event.improved for event in selected) == 3
    assert [event.sort_key for event in selected] == sorted(event.sort_key for event in selected)
    assert audit.candidate_count == 6
    assert audit.positive_count == 4
    assert audit.other_count == 2
    assert audit.supplemented == 0

    supplemented, supplemented_audit = retrieve_committed_events(
        store,
        generation=1,
        role="integrator",
        benchmark="tsp",
        objective="minimize",
    )
    assert len(supplemented) == 5
    assert sum(event.improved for event in supplemented) == 1
    assert supplemented_audit.supplemented == 2

    empty, empty_audit = retrieve_committed_events(
        store,
        generation=1,
        role="explorer",
        benchmark="tsp",
        objective="maximize",
    )
    assert empty == ()
    assert empty_audit.candidate_count == 0


def test_prompt_truncation_removes_old_text_then_events_then_summary() -> None:
    elite = _candidate("elite", 3.0)
    evidence = (_event(0), _event(1))
    summary = RoleMemorySummary.create(
        role="explorer",
        through_generation=0,
        source_event_ids=tuple(event.event_id for event in evidence),
        prompt_version="roco-ltreflect-v1",
        provider_name="mock",
        model_name="deterministic",
        useful_strategies=("u" * 200,),
        failure_patterns=("f" * 200,),
        applicability_conditions=("a" * 200,),
        avoid_patterns=("x" * 200,),
    )

    _, full = assemble_memory_prompt(
        role="explorer", elite=elite, summary=summary, evidence=evidence, limit=100_000
    )
    prompt, shallow = assemble_memory_prompt(
        role="explorer",
        elite=elite,
        summary=summary,
        evidence=evidence,
        limit=full.original_size - 1,
    )
    assert shallow.truncated_fields == (f"event:{evidence[0].event_id}:feedback",)
    assert shallow.dropped_event_ids == ()
    assert len(prompt) <= shallow.limit

    irreducible_prompt, deep = assemble_memory_prompt(
        role="explorer", elite=elite, summary=summary, evidence=evidence, limit=1
    )
    assert deep.dropped_event_ids == tuple(event.event_id for event in evidence)
    assert deep.truncated_fields[:2] == tuple(
        f"event:{event.event_id}:feedback" for event in evidence
    )
    assert any(field.startswith("role_summary:") for field in deep.truncated_fields)
    assert summary.source_hash in irreducible_prompt
    assert deep.reason == "irreducible_required_fields"


class _RecordingProvider(MockLLMProvider):
    def __init__(self, seed: int, *, invalid_second_summary: bool = False) -> None:
        super().__init__(seed)
        self.invalid_second_summary = invalid_second_summary
        self.summary_roles: list[tuple[int, RoCoRole]] = []
        self.mutation_roles: list[tuple[int, RoCoRole]] = []

    def summarize_memory(self, request: MemorySummaryRequest, ledger: BudgetLedger) -> Any:
        self.summary_roles.append((request.generation, request.role))
        if (
            self.invalid_second_summary
            and request.generation == 1
            and request.role is RoCoRole.EXPLORER
        ):
            ledger.consume(llm_calls=1, input_tokens=1, output_tokens=1)
            return {"not": "a structured summary"}
        return super().summarize_memory(request, ledger)

    def generate_memory_mutation(
        self, request: MemoryMutationRequest, ledger: BudgetLedger
    ) -> RoleResponse:
        self.mutation_roles.append((request.generation, request.role))
        return super().generate_memory_mutation(request, ledger)


class _MutationFailureProvider(MockLLMProvider):
    def generate_memory_mutation(
        self, request: MemoryMutationRequest, ledger: BudgetLedger
    ) -> RoleResponse:
        request_index = self._request_index
        if request.role is RoCoRole.EXPLORER:
            ledger.consume(llm_calls=1, input_tokens=1, output_tokens=1)
            self._request_index += 1
            raise RuntimeError("API_TOKEN=provider-secret")
        if request.role is RoCoRole.EXPLOITER:
            ledger.consume(llm_calls=1, input_tokens=1, output_tokens=1)
            self._request_index += 1
            return RoleResponse(request_index=request_index)
        ledger.consume(
            llm_calls=1,
            input_tokens=1,
            output_tokens=1,
            generated_candidates=1,
        )
        self._request_index += 1
        generated = GeneratedHeuristic(
            "deterministic timeout",
            "def heuristic(distance_matrix):\n    while True:\n        pass\n",
            request_index,
        )
        return RoleResponse(request_index=request_index, candidate=generated)


class _InvalidFirstSummaryProvider(MockLLMProvider):
    def summarize_memory(self, request: MemorySummaryRequest, ledger: BudgetLedger) -> Any:
        if request.role is RoCoRole.EXPLORER:
            ledger.consume(llm_calls=1, input_tokens=1, output_tokens=1)
            return {"not": "a structured summary"}
        return super().summarize_memory(request, ledger)


class _SummaryProviderErrorProvider(MockLLMProvider):
    def summarize_memory(self, request: MemorySummaryRequest, ledger: BudgetLedger) -> Any:
        if request.role is RoCoRole.EXPLORER:
            ledger.consume(llm_calls=1, input_tokens=1, output_tokens=1)
            raise RuntimeError("ACCESS_TOKEN=summary-secret")
        return super().summarize_memory(request, ledger)


class _EvaluationErrorProvider(MockLLMProvider):
    def generate_memory_mutation(
        self, request: MemoryMutationRequest, ledger: BudgetLedger
    ) -> RoleResponse:
        if request.role is not RoCoRole.INTEGRATOR:
            return super().generate_memory_mutation(request, ledger)
        request_index = self._request_index
        ledger.consume(
            llm_calls=1,
            input_tokens=1,
            output_tokens=1,
            generated_candidates=1,
        )
        self._request_index += 1
        generated = GeneratedHeuristic(
            "deterministic runtime error",
            "def heuristic(distance_matrix):\n    return 1 / 0\n",
            request_index,
        )
        return RoleResponse(request_index=request_index, candidate=generated)


def _run_memory_engine(
    tmp_path: Path,
    *,
    provider: MockLLMProvider,
    generations: int = 1,
    max_llm_calls: int = 100,
    timeout: float = 2.0,
) -> tuple[Any, BudgetLedger, GenerationMemoryStore]:
    ledger = BudgetLedger(
        max_llm_calls=max_llm_calls,
        max_tokens=200_000,
        max_generated_candidates=100,
        max_valid_evals=100,
    )
    evaluator = TSPCodeEvaluator(timeout_seconds=timeout)
    matrix = generate_symmetric_distance_matrix(nodes=20, seed=41)
    collaborator = RoCoCollaborator(
        provider=provider,
        evaluator=evaluator,
        distance_matrix=matrix,
        ledger=ledger,
        rounds=1,
        seed=43,
    )
    store = GenerationMemoryStore(tmp_path / "memory")
    runtime = MemoryRuntime(
        provider=provider,
        evaluator=evaluator,
        distance_matrix=matrix,
        ledger=ledger,
        store=store,
        collaborator=collaborator,
        run_id="runtime-engine-test",
        benchmark="tsp",
        objective="minimize",
        config_hash=hashlib.sha256(b"engine-config").hexdigest(),
    )
    engine = EoHEngine(
        provider=provider,
        evaluator=evaluator,
        distance_matrix=matrix,
        ledger=ledger,
        population_size=4,
        generations=generations,
        collaborator=collaborator,
        memory_runtime=runtime,
    )
    return engine.run(), ledger, store


def test_three_role_summaries_and_mutations_use_fallback_lineage_and_unified_top_n(
    tmp_path: Path,
) -> None:
    provider = _RecordingProvider(seed=47, invalid_second_summary=True)
    result, ledger, store = _run_memory_engine(
        tmp_path,
        provider=provider,
        generations=2,
    )

    assert provider.summary_roles == [
        (generation, role)
        for generation in (0, 1)
        for role in (RoCoRole.EXPLORER, RoCoRole.EXPLOITER, RoCoRole.INTEGRATOR)
    ]
    assert provider.mutation_roles == [
        (generation, role)
        for generation in (1, 2)
        for role in (RoCoRole.EXPLORER, RoCoRole.EXPLOITER, RoCoRole.INTEGRATOR)
    ]
    assert len(result.memory_traces) == 2
    fallback = result.memory_traces[1].summary_attempts[0]
    assert fallback.status == "fallback_invalid_output"
    assert fallback.fallback == "previous"
    first_summary = store.read_generation(0).summary("explorer")
    second_summary = store.read_generation(1).summary("explorer")
    assert second_summary.useful_strategies == first_summary.useful_strategies
    assert second_summary.source_event_ids == first_summary.source_event_ids

    memory_candidates = [
        candidate for candidate in result.all_candidates if candidate.operator.startswith("memory_")
    ]
    assert len(memory_candidates) == 6
    assert all(
        candidate.metadata["elite_id"] == candidate.parents[0] for candidate in memory_candidates
    )
    assert all("summary_hash" in candidate.metadata for candidate in memory_candidates)
    assert all("memory_event_ids" in candidate.metadata for candidate in memory_candidates)
    selected_ids = {candidate.id for candidate in result.population.candidates}
    committed = store.read_generation(1)
    assert all(
        event.selected_in_population == (event.output_candidate_id in selected_ids)
        for event in committed.events
        if event.success
    )
    assert ledger.generated_candidates == ledger.valid_evals


def test_memory_mutation_failures_are_structured_and_do_not_retry(tmp_path: Path) -> None:
    result, _, store = _run_memory_engine(
        tmp_path,
        provider=_MutationFailureProvider(seed=53),
        timeout=0.05,
    )

    trace = result.memory_traces[0]
    assert [event.role for event in trace.mutation_events] == [
        "explorer",
        "exploiter",
        "integrator",
    ]
    assert [event.failure_type for event in trace.mutation_events] == [
        "provider_error",
        "invalid_output",
        "evaluation_timeout",
    ]
    assert "provider-secret" not in trace.mutation_events[0].to_json()
    assert trace.mutation_events[0].failure_message == "API_TOKEN=[REDACTED]"
    assert store.scan().visible_generations == (0,)


def test_first_generation_summary_failure_uses_empty_fallback(tmp_path: Path) -> None:
    result, _, store = _run_memory_engine(
        tmp_path,
        provider=_InvalidFirstSummaryProvider(seed=57),
    )

    attempt = result.memory_traces[0].summary_attempts[0]
    summary = store.read_generation(0).summary("explorer")
    assert attempt.status == "fallback_invalid_output"
    assert attempt.fallback == "empty"
    assert summary.source_event_ids == ()
    assert summary.useful_strategies == ()


def test_summary_provider_error_is_redacted_and_does_not_block_other_roles(
    tmp_path: Path,
) -> None:
    result, _, store = _run_memory_engine(
        tmp_path,
        provider=_SummaryProviderErrorProvider(seed=57),
    )

    trace = result.memory_traces[0]
    assert [attempt.status for attempt in trace.summary_attempts] == [
        "fallback_provider_error",
        "success",
        "success",
    ]
    assert trace.summary_attempts[0].error_message == "ACCESS_TOKEN=[REDACTED]"
    assert len(trace.mutation_events) == 3
    assert store.scan().visible_generations == (0,)


def test_non_timeout_evaluation_error_is_structured_and_later_commit_survives(
    tmp_path: Path,
) -> None:
    result, _, store = _run_memory_engine(
        tmp_path,
        provider=_EvaluationErrorProvider(seed=58),
    )

    integrator = result.memory_traces[0].mutation_events[-1]
    assert integrator.role == "integrator"
    assert integrator.event_kind == "evaluation_failure"
    assert integrator.failure_type == "evaluation_error"
    assert integrator.after_score is None
    assert integrator.delta_g is None
    assert store.scan().visible_generations == (0,)


def test_memory_budget_exhaustion_stops_later_consuming_actions_and_commits(tmp_path: Path) -> None:
    result, ledger, store = _run_memory_engine(
        tmp_path,
        provider=MockLLMProvider(seed=59),
        max_llm_calls=18,
    )

    trace = result.memory_traces[0]
    assert result.stopped_on_budget
    assert trace.stopped_on_budget
    assert ledger.llm_calls == 18
    assert len(trace.mutation_events) == 1
    assert trace.mutation_events[0].failure_type == "budget_exhausted"
    assert store.scan().visible_generations == (0,)
