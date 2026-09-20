"""Configuration loading for deterministic Stage 2--4 offline smoke runs."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from roco_ebbo.benchmarks import generate_symmetric_distance_matrix
from roco_ebbo.core import BudgetLedger
from roco_ebbo.evaluation import TSPCodeEvaluator
from roco_ebbo.evolution import EngineResumeState, EoHEngine, EoHRunResult, RoCoCollaborator
from roco_ebbo.llm import ROLE_TEMPERATURES, MockLLMProvider, RoCoRole
from roco_ebbo.memory import GenerationMemoryStore, MemoryRuntime, MemoryRuntimeConfig


class MemoryResumeError(RuntimeError):
    """Structured fail-closed error from an explicit memory resume request."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


@dataclass(frozen=True, slots=True)
class MemoryResumeAudit:
    recovered_memory_generation: int
    next_engine_generation: int
    artifact_hashes: dict[str, str]
    ignored_store_issues: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class SmokeSettings:
    seed: int
    objective: str
    max_valid_evals: int | None
    max_llm_calls: int | None
    max_tokens: int | None
    provider: str
    mode: str
    population_size: int
    generations: int
    candidates_per_operator: int
    collaboration_rounds: int
    elite_sampling_power: float
    role_temperatures: dict[RoCoRole, float]
    benchmark_name: str
    nodes: int
    instances: int
    evaluator_timeout_seconds: float
    memory_enabled: bool
    memory_recent_events: int
    memory_success_slots: int
    memory_failure_slots: int
    memory_elite_count: int
    memory_max_context_characters: int
    config_snapshot: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SmokeRun:
    result: EoHRunResult
    ledger: BudgetLedger
    provider_seed: int
    benchmark_seed: int
    collaboration_seed: int | None
    memory_root: Path | None = None
    resume_audit: MemoryResumeAudit | None = None


@dataclass(frozen=True, slots=True)
class MemoryAblationRun:
    """Paired offline runs that differ only at the memory opt-in boundary."""

    memory_off: SmokeRun
    memory_on: SmokeRun


def load_smoke_settings(path: str | Path) -> SmokeSettings:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("smoke config must contain a YAML mapping")
    try:
        run = _mapping(raw, "run")
        budgets = _mapping(run, "budgets")
        llm = _mapping(raw, "llm")
        evolution = _mapping(raw, "evolution")
        benchmark = _mapping(raw, "benchmark")
        memory = raw.get("memory", {})
        if not isinstance(memory, dict):
            raise TypeError("memory must be a mapping")
        configured_temperatures = llm.get("temperatures", {})
        if not isinstance(configured_temperatures, dict):
            raise TypeError("llm.temperatures must be a mapping")
        role_temperatures = {
            role: float(configured_temperatures.get(role.value, default))
            for role, default in ROLE_TEMPERATURES.items()
        }
        settings = SmokeSettings(
            seed=int(run["seed"]),
            objective=str(run["objective"]),
            max_valid_evals=_optional_int(budgets.get("max_valid_evals")),
            max_llm_calls=_optional_int(budgets.get("max_llm_calls")),
            max_tokens=_optional_int(budgets.get("max_tokens")),
            provider=str(llm["provider"]),
            mode=str(evolution.get("mode", "eoh")),
            population_size=int(evolution["population_size"]),
            generations=int(evolution["generations"]),
            candidates_per_operator=int(evolution["candidates_per_operator"]),
            collaboration_rounds=int(evolution.get("collaboration_rounds", 3)),
            elite_sampling_power=float(evolution.get("elite_sampling_power", 3.0)),
            role_temperatures=role_temperatures,
            benchmark_name=str(benchmark["name"]),
            nodes=int(benchmark["nodes"]),
            instances=int(benchmark["instances"]),
            evaluator_timeout_seconds=float(benchmark["evaluator_timeout_seconds"]),
            memory_enabled=_strict_bool(memory.get("enabled", False), "memory.enabled"),
            memory_recent_events=int(memory.get("recent_events", 5)),
            memory_success_slots=int(memory.get("success_slots", 3)),
            memory_failure_slots=int(memory.get("failure_slots", 2)),
            memory_elite_count=int(memory.get("elite_count", 1)),
            memory_max_context_characters=int(memory.get("max_context_characters", 16_000)),
            config_snapshot=raw,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid smoke config: {exc}") from exc
    _validate_settings(settings)
    return settings


def run_smoke(
    settings: SmokeSettings,
    *,
    memory_root: str | Path | None = None,
    run_id: str = "offline-memory-smoke",
    interrupt_after_committed_generation: int | None = None,
) -> SmokeRun:
    provider_seed = _derive_seed(settings.seed, "mock-provider")
    benchmark_seed = _derive_seed(settings.seed, "tsp-instance")
    collaboration_seed = (
        _derive_seed(settings.seed, "roco-collaboration") if settings.mode == "roco" else None
    )
    ledger = BudgetLedger(
        max_llm_calls=settings.max_llm_calls,
        max_tokens=settings.max_tokens,
        max_valid_evals=settings.max_valid_evals,
    )
    provider = MockLLMProvider(seed=provider_seed)
    evaluator = TSPCodeEvaluator(timeout_seconds=settings.evaluator_timeout_seconds)
    distance_matrix = generate_symmetric_distance_matrix(
        nodes=settings.nodes,
        seed=benchmark_seed,
    )
    collaborator = None
    if settings.mode == "roco":
        assert collaboration_seed is not None
        collaborator = RoCoCollaborator(
            provider=provider,
            evaluator=evaluator,
            distance_matrix=distance_matrix,
            ledger=ledger,
            rounds=settings.collaboration_rounds,
            elite_sampling_power=settings.elite_sampling_power,
            seed=collaboration_seed,
            temperatures=settings.role_temperatures,
            minimize=True,
        )
    resolved_memory_root: Path | None = None
    memory_runtime = None
    if settings.memory_enabled:
        if memory_root is None:
            raise ValueError("memory-enabled smoke runs require an explicit memory_root")
        assert collaborator is not None
        resolved_memory_root = Path(memory_root)
        memory_runtime = MemoryRuntime(
            provider=provider,
            evaluator=evaluator,
            distance_matrix=distance_matrix,
            ledger=ledger,
            store=GenerationMemoryStore(resolved_memory_root),
            collaborator=collaborator,
            run_id=run_id,
            benchmark=settings.benchmark_name,
            objective=settings.objective,
            config_hash=_config_hash(settings),
            config=MemoryRuntimeConfig(
                recent_events=settings.memory_recent_events,
                success_slots=settings.memory_success_slots,
                failure_slots=settings.memory_failure_slots,
                elite_count=settings.memory_elite_count,
                max_context_characters=settings.memory_max_context_characters,
            ),
        )
    engine = EoHEngine(
        provider=provider,
        evaluator=evaluator,
        distance_matrix=distance_matrix,
        ledger=ledger,
        population_size=settings.population_size,
        generations=settings.generations,
        candidates_per_operator=settings.candidates_per_operator,
        minimize=True,
        collaborator=collaborator,
        memory_runtime=memory_runtime,
    )
    return SmokeRun(
        result=engine.run(
            interrupt_after_committed_generation=interrupt_after_committed_generation
        ),
        ledger=ledger,
        provider_seed=provider_seed,
        benchmark_seed=benchmark_seed,
        collaboration_seed=collaboration_seed,
        memory_root=resolved_memory_root,
    )


def resume_smoke(
    settings: SmokeSettings,
    *,
    memory_root: str | Path,
    run_id: str,
) -> SmokeRun:
    """Resume only the explicitly named memory store from its last valid commit."""

    if not settings.memory_enabled or settings.mode != "roco":
        raise MemoryResumeError(
            "memory_disabled",
            "resume requires an opt-in memory-enabled RoCo configuration",
        )
    resolved_memory_root = Path(memory_root)
    store = GenerationMemoryStore(resolved_memory_root)
    report = store.scan()
    blocking_codes = {
        "bad_hash",
        "invalid_artifact",
        "invalid_commit",
        "missing_artifact",
        "noncontinuous_generation",
        "unsafe_path",
    }
    blocking = [issue for issue in report.issues if issue.code in blocking_codes]
    if blocking:
        issue = blocking[0]
        raise MemoryResumeError(
            issue.code,
            f"memory store is not safe to resume: {issue.message}",
            details={
                "generation": issue.generation,
                "path": issue.path,
                "issue_count": len(blocking),
            },
        )
    if report.latest is None:
        raise MemoryResumeError(
            "missing_commit",
            "the specified memory store has no valid committed generation",
            details={"memory_root": str(resolved_memory_root)},
        )

    recovery = store.recover()
    assert recovery is not None
    provider_seed = _derive_seed(settings.seed, "mock-provider")
    benchmark_seed = _derive_seed(settings.seed, "tsp-instance")
    collaboration_seed = _derive_seed(settings.seed, "roco-collaboration")
    provider_snapshot = recovery.provider_snapshots.get("mock")
    collaborator_snapshot = recovery.random_streams.get("collaboration")
    if not isinstance(provider_snapshot, dict) or not isinstance(collaborator_snapshot, dict):
        raise MemoryResumeError(
            "missing_runtime_state",
            "checkpoint is missing the mock provider or collaboration snapshot",
        )
    if provider_snapshot.get("seed") != provider_seed:
        raise MemoryResumeError(
            "seed_mismatch",
            "configured seed does not match the checkpoint provider stream",
            details={
                "expected_provider_seed": provider_seed,
                "checkpoint_provider_seed": provider_snapshot.get("seed"),
            },
        )
    if collaborator_snapshot.get("sampling_seed") != collaboration_seed:
        raise MemoryResumeError(
            "seed_mismatch",
            "configured seed does not match the checkpoint collaboration stream",
            details={
                "expected_collaboration_seed": collaboration_seed,
                "checkpoint_collaboration_seed": collaborator_snapshot.get("sampling_seed"),
            },
        )

    expected_config_hash = _config_hash(settings)
    if any(record.commit.config_hash != expected_config_hash for record in report.records):
        raise MemoryResumeError(
            "config_mismatch",
            "configured smoke settings do not match the committed memory config hash",
            details={"expected_config_hash": expected_config_hash},
        )
    if any(
        event.run_id != run_id
        or event.benchmark != settings.benchmark_name
        or event.objective != settings.objective
        for record in report.records
        for event in record.events
    ):
        raise MemoryResumeError(
            "scope_mismatch",
            "run_id, benchmark, or objective differs from committed memory events",
        )
    if recovery.generation >= settings.generations:
        raise MemoryResumeError(
            "generation_mismatch",
            "checkpoint generation exceeds the configured run length",
        )

    try:
        provider = MockLLMProvider.from_snapshot(provider_snapshot)
        ledger = recovery.budget_ledger
        evaluator = TSPCodeEvaluator(timeout_seconds=settings.evaluator_timeout_seconds)
        distance_matrix = generate_symmetric_distance_matrix(
            nodes=settings.nodes,
            seed=benchmark_seed,
        )
        collaborator = RoCoCollaborator(
            provider=provider,
            evaluator=evaluator,
            distance_matrix=distance_matrix,
            ledger=ledger,
            rounds=settings.collaboration_rounds,
            elite_sampling_power=settings.elite_sampling_power,
            seed=collaboration_seed,
            temperatures=settings.role_temperatures,
            minimize=True,
        )
        collaborator.restore_snapshot(collaborator_snapshot)
    except (TypeError, ValueError) as exc:
        raise MemoryResumeError(
            "incompatible_checkpoint",
            f"checkpoint runtime state is incompatible: {exc}",
        ) from exc

    runtime = MemoryRuntime(
        provider=provider,
        evaluator=evaluator,
        distance_matrix=distance_matrix,
        ledger=ledger,
        store=store,
        collaborator=collaborator,
        run_id=run_id,
        benchmark=settings.benchmark_name,
        objective=settings.objective,
        config_hash=expected_config_hash,
        config=MemoryRuntimeConfig(
            recent_events=settings.memory_recent_events,
            success_slots=settings.memory_success_slots,
            failure_slots=settings.memory_failure_slots,
            elite_count=settings.memory_elite_count,
            max_context_characters=settings.memory_max_context_characters,
        ),
    )
    engine = EoHEngine(
        provider=provider,
        evaluator=evaluator,
        distance_matrix=distance_matrix,
        ledger=ledger,
        population_size=settings.population_size,
        generations=settings.generations,
        candidates_per_operator=settings.candidates_per_operator,
        minimize=True,
        collaborator=collaborator,
        memory_runtime=runtime,
    )
    next_engine_generation = recovery.generation + 2
    result = engine.resume(
        EngineResumeState(
            population=recovery.population,
            next_generation=next_engine_generation,
        )
    )
    latest = recovery.scan_report.latest
    assert latest is not None
    ignored = tuple(
        {
            "code": issue.code,
            "message": issue.message,
            "generation": issue.generation,
            "path": issue.path,
        }
        for issue in recovery.scan_report.issues
        if issue.code in {"missing_commit", "orphan_artifact", "temporary_artifact"}
    )
    return SmokeRun(
        result=result,
        ledger=ledger,
        provider_seed=provider_seed,
        benchmark_seed=benchmark_seed,
        collaboration_seed=collaboration_seed,
        memory_root=resolved_memory_root,
        resume_audit=MemoryResumeAudit(
            recovered_memory_generation=recovery.generation,
            next_engine_generation=next_engine_generation,
            artifact_hashes={
                key: artifact.sha256 for key, artifact in latest.commit.artifacts.items()
            },
            ignored_store_issues=ignored,
        ),
    )


def run_memory_ablation(
    settings: SmokeSettings,
    *,
    memory_root: str | Path,
    run_id: str = "offline-memory-ablation",
) -> MemoryAblationRun:
    """Run the deterministic memory-off/on pair without making a quality claim."""

    if not settings.memory_enabled or settings.mode != "roco":
        raise ValueError("memory ablation requires a memory-enabled RoCo base configuration")
    memory_off = run_smoke(replace(settings, memory_enabled=False))
    memory_on = run_smoke(settings, memory_root=memory_root, run_id=run_id)
    return MemoryAblationRun(memory_off=memory_off, memory_on=memory_on)


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be a mapping")
    return value


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")
    return value


def _validate_settings(settings: SmokeSettings) -> None:
    if settings.objective != "minimize":
        raise ValueError("smoke runs support only objective=minimize")
    if settings.provider != "mock":
        raise ValueError("smoke runs support only the offline mock provider")
    if settings.mode not in {"eoh", "roco"}:
        raise ValueError("evolution.mode must be eoh or roco")
    if settings.memory_enabled and settings.mode != "roco":
        raise ValueError("memory runtime requires evolution.mode=roco")
    MemoryRuntimeConfig(
        recent_events=settings.memory_recent_events,
        success_slots=settings.memory_success_slots,
        failure_slots=settings.memory_failure_slots,
        elite_count=settings.memory_elite_count,
        max_context_characters=settings.memory_max_context_characters,
    )
    if settings.population_size < 2:
        raise ValueError("population_size must be at least 2")
    if settings.generations < 1:
        raise ValueError("generations must be at least 1")
    if settings.candidates_per_operator < 1:
        raise ValueError("candidates_per_operator must be at least 1")
    if settings.collaboration_rounds < 1:
        raise ValueError("collaboration_rounds must be at least 1")
    if not math.isfinite(settings.elite_sampling_power) or settings.elite_sampling_power <= 0:
        raise ValueError("elite_sampling_power must be finite and greater than zero")
    if any(
        not math.isfinite(temperature) or temperature < 0
        for temperature in settings.role_temperatures.values()
    ):
        raise ValueError("role temperatures must be finite and non-negative")
    if settings.benchmark_name != "tsp" or settings.nodes != 20 or settings.instances != 1:
        raise ValueError("smoke runs require one deterministic TSP-20 instance")
    if (
        not math.isfinite(settings.evaluator_timeout_seconds)
        or settings.evaluator_timeout_seconds <= 0
    ):
        raise ValueError("evaluator_timeout_seconds must be finite and greater than zero")
    hard_limits = (
        settings.max_valid_evals,
        settings.max_llm_calls,
        settings.max_tokens,
    )
    if all(limit is None for limit in hard_limits):
        raise ValueError("at least one hard budget must be configured")
    if any(limit is not None and limit < 0 for limit in hard_limits):
        raise ValueError("hard budgets must be non-negative or null")


def _derive_seed(seed: int, stream: str) -> int:
    payload = f"{seed}:{stream}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _config_hash(settings: SmokeSettings) -> str:
    return hashlib.sha256(
        json.dumps(
            settings.config_snapshot,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
