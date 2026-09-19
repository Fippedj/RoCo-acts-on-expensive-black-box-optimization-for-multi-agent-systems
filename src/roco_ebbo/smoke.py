"""Configuration loading and deterministic orchestration for the Stage 2 smoke run."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from roco_ebbo.benchmarks import generate_symmetric_distance_matrix
from roco_ebbo.core import BudgetLedger
from roco_ebbo.evaluation import TSPCodeEvaluator
from roco_ebbo.evolution import EoHEngine, EoHRunResult
from roco_ebbo.llm import MockLLMProvider


@dataclass(frozen=True, slots=True)
class SmokeSettings:
    seed: int
    objective: str
    max_valid_evals: int | None
    max_llm_calls: int | None
    max_tokens: int | None
    provider: str
    population_size: int
    generations: int
    candidates_per_operator: int
    collaboration_rounds: int
    benchmark_name: str
    nodes: int
    instances: int
    evaluator_timeout_seconds: float
    config_snapshot: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SmokeRun:
    result: EoHRunResult
    ledger: BudgetLedger
    provider_seed: int
    benchmark_seed: int


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
        settings = SmokeSettings(
            seed=int(run["seed"]),
            objective=str(run["objective"]),
            max_valid_evals=_optional_int(budgets.get("max_valid_evals")),
            max_llm_calls=_optional_int(budgets.get("max_llm_calls")),
            max_tokens=_optional_int(budgets.get("max_tokens")),
            provider=str(llm["provider"]),
            population_size=int(evolution["population_size"]),
            generations=int(evolution["generations"]),
            candidates_per_operator=int(evolution["candidates_per_operator"]),
            collaboration_rounds=int(evolution["collaboration_rounds"]),
            benchmark_name=str(benchmark["name"]),
            nodes=int(benchmark["nodes"]),
            instances=int(benchmark["instances"]),
            evaluator_timeout_seconds=float(benchmark["evaluator_timeout_seconds"]),
            config_snapshot=raw,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid smoke config: {exc}") from exc
    _validate_settings(settings)
    return settings


def run_smoke(settings: SmokeSettings) -> SmokeRun:
    provider_seed = _derive_seed(settings.seed, "mock-provider")
    benchmark_seed = _derive_seed(settings.seed, "tsp-instance")
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
    engine = EoHEngine(
        provider=provider,
        evaluator=evaluator,
        distance_matrix=distance_matrix,
        ledger=ledger,
        population_size=settings.population_size,
        generations=settings.generations,
        candidates_per_operator=settings.candidates_per_operator,
        minimize=True,
    )
    return SmokeRun(
        result=engine.run(),
        ledger=ledger,
        provider_seed=provider_seed,
        benchmark_seed=benchmark_seed,
    )


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be a mapping")
    return value


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _validate_settings(settings: SmokeSettings) -> None:
    if settings.objective != "minimize":
        raise ValueError("Stage 2 smoke supports only objective=minimize")
    if settings.provider != "mock":
        raise ValueError("Stage 2 smoke supports only the offline mock provider")
    if settings.population_size < 2:
        raise ValueError("population_size must be at least 2")
    if settings.generations < 1:
        raise ValueError("generations must be at least 1")
    if settings.candidates_per_operator < 1:
        raise ValueError("candidates_per_operator must be at least 1")
    if settings.collaboration_rounds < 1:
        raise ValueError("collaboration_rounds must be at least 1")
    if settings.benchmark_name != "tsp" or settings.nodes != 20 or settings.instances != 1:
        raise ValueError("Stage 2 smoke requires one deterministic TSP-20 instance")
    if settings.evaluator_timeout_seconds <= 0:
        raise ValueError("evaluator_timeout_seconds must be greater than zero")
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
