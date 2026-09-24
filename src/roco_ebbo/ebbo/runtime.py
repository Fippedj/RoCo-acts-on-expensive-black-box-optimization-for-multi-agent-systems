"""Configuration, execution, and artifacts for the offline P9a EBBO smoke."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from roco_ebbo.ebbo.baseline import (
    ACQUISITION_VERSION,
    SURROGATE_VERSION,
    CandidatePool,
    MockSearchSpace,
    NearestObservationSurrogate,
    SurrogateSample,
    build_candidate_pool,
)
from roco_ebbo.ebbo.contracts import (
    JsonValue,
    Observation,
    canonical_json,
    require_json_safe,
    stable_id,
)
from roco_ebbo.ebbo.ledger import EBBOLedger
from roco_ebbo.ebbo.oracle import MOCK_COST_UNIT, MOCK_ORACLE_VERSION, MockExpensiveOracle
from roco_ebbo.ebbo.scheduler import SerialScheduler
from roco_ebbo.ebbo.store import ObservationStore

EBBO_SMOKE_CONFIG_VERSION = "ebbo-mock-smoke-config-v1"
EBBO_SMOKE_RUN_VERSION = "ebbo-mock-smoke-run-v1"


@dataclass(frozen=True, slots=True)
class EBBOSmokeSettings:
    root_seed: int
    max_oracle_calls: int
    max_candidate_proposals: int
    max_cost: float
    lower: int
    upper: int
    iterations: int
    pool_size: int
    prior_mean: float
    beta: float
    config_snapshot: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class EBBOSmokeRun:
    run_id: str
    observations: tuple[Observation, ...]
    pools: tuple[CandidatePool, ...]
    scheduler: SerialScheduler
    ledger: EBBOLedger
    store: ObservationStore
    replay_checksum: str
    best_observation_id: str | None
    best_objective: float | None


def load_ebbo_smoke_settings(path: str | Path) -> EBBOSmokeSettings:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("EBBO smoke config must be a mapping")
    _exact_keys(raw, {"protocol", "run", "search_space", "baseline", "oracle"}, "config")
    protocol = _mapping(raw, "protocol")
    run = _mapping(raw, "run")
    search_space = _mapping(raw, "search_space")
    baseline = _mapping(raw, "baseline")
    oracle = _mapping(raw, "oracle")
    _exact_keys(protocol, {"schema_version", "scope"}, "protocol")
    _exact_keys(run, {"root_seed", "iterations", "budgets"}, "run")
    budgets = _mapping(run, "budgets")
    _exact_keys(
        budgets,
        {"max_oracle_calls", "max_candidate_proposals", "max_cost", "cost_unit"},
        "run.budgets",
    )
    _exact_keys(search_space, {"version", "lower", "upper"}, "search_space")
    _exact_keys(
        baseline,
        {"surrogate", "acquisition", "prior_mean", "beta", "pool_size", "max_concurrency"},
        "baseline",
    )
    _exact_keys(oracle, {"adapter", "network", "financial_cost"}, "oracle")
    if protocol["schema_version"] != EBBO_SMOKE_CONFIG_VERSION:
        raise ValueError("unsupported EBBO smoke config version")
    if protocol["scope"] != "engineering-mock-only":
        raise ValueError("EBBO smoke scope must be engineering-mock-only")
    if search_space["version"] != "ebbo-mock-integer-space-v1":
        raise ValueError("unsupported Mock search-space version")
    if baseline["surrogate"] != SURROGATE_VERSION:
        raise ValueError("unsupported P9a surrogate")
    if baseline["acquisition"] != ACQUISITION_VERSION:
        raise ValueError("unsupported P9a acquisition")
    if baseline["max_concurrency"] != 1:
        raise ValueError("P9a requires max_concurrency=1")
    if oracle != {
        "adapter": MOCK_ORACLE_VERSION,
        "network": "unused",
        "financial_cost": 0,
    } and oracle != {
        "adapter": MOCK_ORACLE_VERSION,
        "network": "unused",
        "financial_cost": 0.0,
    }:
        raise ValueError("P9a smoke permits only the zero-fee offline Mock oracle")
    if budgets["cost_unit"] != MOCK_COST_UNIT:
        raise ValueError("unsupported Mock cost unit")
    settings = EBBOSmokeSettings(
        root_seed=_integer(run["root_seed"], "run.root_seed", minimum=0),
        max_oracle_calls=_integer(
            budgets["max_oracle_calls"], "run.budgets.max_oracle_calls", minimum=1
        ),
        max_candidate_proposals=_integer(
            budgets["max_candidate_proposals"],
            "run.budgets.max_candidate_proposals",
            minimum=1,
        ),
        max_cost=_number(budgets["max_cost"], "run.budgets.max_cost", minimum=0),
        lower=_integer(search_space["lower"], "search_space.lower"),
        upper=_integer(search_space["upper"], "search_space.upper"),
        iterations=_integer(run["iterations"], "run.iterations", minimum=1),
        pool_size=_integer(baseline["pool_size"], "baseline.pool_size", minimum=1),
        prior_mean=_number(baseline["prior_mean"], "baseline.prior_mean"),
        beta=_number(baseline["beta"], "baseline.beta", minimum=0),
        config_snapshot=raw,
    )
    MockSearchSpace(settings.lower, settings.upper)
    if settings.iterations > settings.max_oracle_calls:
        raise ValueError("iterations cannot exceed max_oracle_calls in serial P9a smoke")
    if settings.iterations * settings.pool_size > settings.max_candidate_proposals:
        raise ValueError("candidate proposal budget cannot cover configured smoke pools")
    require_json_safe(raw)
    return settings


def run_ebbo_smoke(settings: EBBOSmokeSettings, *, output_dir: str | Path) -> EBBOSmokeRun:
    root = Path(output_dir)
    if root.exists():
        raise FileExistsError(f"EBBO smoke output directory already exists: {root}")
    search_space = MockSearchSpace(settings.lower, settings.upper)
    run_id = stable_id(
        "run",
        {
            "schema_version": EBBO_SMOKE_RUN_VERSION,
            "config": settings.config_snapshot,
        },
    )
    ledger = EBBOLedger(
        max_oracle_calls=settings.max_oracle_calls,
        max_candidate_proposals=settings.max_candidate_proposals,
        max_cost=settings.max_cost,
        cost_unit=MOCK_COST_UNIT,
    )
    store = ObservationStore(root)
    scheduler = SerialScheduler(
        oracle=MockExpensiveOracle(search_space),
        ledger=ledger,
        store=store,
        run_id=run_id,
        root_seed=settings.root_seed,
    )
    surrogate = NearestObservationSurrogate(search_space, settings.prior_mean)
    observations: list[Observation] = []
    pools: list[CandidatePool] = []
    started = time.perf_counter()
    for iteration in range(settings.iterations):
        pool = build_candidate_pool(
            search_space=search_space,
            surrogate=surrogate,
            root_seed=settings.root_seed,
            iteration=iteration,
            pool_size=settings.pool_size,
            beta=settings.beta,
            excluded_candidate_ids=set(scheduler.dispatched_candidate_ids),
            ledger=ledger,
        )
        pools.append(pool)
        if not pool.entries:
            break
        observation = scheduler.dispatch(pool)
        observations.append(observation)
        if observation.objective is not None:
            request = scheduler.requests[-1]
            x = search_space.validate_candidate(request.candidate)
            surrogate = surrogate.updated(
                SurrogateSample(
                    candidate_id=request.candidate_id,
                    x=x,
                    objective=observation.objective,
                    observation_id=observation.observation_id,
                )
            )
        if ledger.oracle_calls >= settings.max_oracle_calls:
            break
    ledger.observe_wall_time(time.perf_counter() - started)
    replay_checksum = store.replay_checksum(ledger.replay_dict())
    successes = [item for item in observations if item.objective is not None]
    best = (
        min(successes, key=lambda item: (item.objective, item.observation_id))
        if successes
        else None
    )
    result = EBBOSmokeRun(
        run_id=run_id,
        observations=tuple(observations),
        pools=tuple(pools),
        scheduler=scheduler,
        ledger=ledger,
        store=store,
        replay_checksum=replay_checksum,
        best_observation_id=None if best is None else best.observation_id,
        best_objective=None if best is None else best.objective,
    )
    _write_artifacts(result, settings, surrogate, root)
    return result


def _write_artifacts(
    run: EBBOSmokeRun,
    settings: EBBOSmokeSettings,
    surrogate: NearestObservationSurrogate,
    root: Path,
) -> None:
    _write_json(
        root / "manifest.json",
        {
            "schema_version": EBBO_SMOKE_RUN_VERSION,
            "run_id": run.run_id,
            "scope": "stage6-p9a-offline-engineering-mock",
            "config": settings.config_snapshot,
            "network": "unused",
            "llm_calls": 0,
            "financial_cost": 0.0,
            "financial_cost_currency": "NONE",
        },
    )
    _write_jsonl(root / "candidate_pools.jsonl", [pool.to_dict() for pool in run.pools])
    _write_jsonl(root / "requests.jsonl", [item.to_dict() for item in run.scheduler.requests])
    _write_jsonl(root / "results.jsonl", [item.to_dict() for item in run.scheduler.results])
    _write_json(root / "ledger.json", run.ledger.to_dict())
    _write_json(
        root / "posterior.json",
        {
            "schema_version": SURROGATE_VERSION,
            "prior_mean": surrogate.prior_mean,
            "samples": [
                {
                    "candidate_id": sample.candidate_id,
                    "x": sample.x,
                    "objective": sample.objective,
                    "observation_id": sample.observation_id,
                }
                for sample in surrogate.samples
            ],
        },
    )
    _write_json(
        root / "replay.json",
        {
            "schema_version": "ebbo-replay-evidence-v1",
            "checksum": run.replay_checksum,
            "excludes": ["wall_time_seconds", "*_at_utc"],
            "store_snapshot": run.store.snapshot(),
        },
    )
    _write_json(
        root / "summary.json",
        {
            "schema_version": "ebbo-mock-smoke-summary-v1",
            "run_id": run.run_id,
            "scope": "engineering-mock-only-not-a-performance-result",
            "oracle_calls": run.ledger.oracle_calls,
            "evaluations_succeeded": run.ledger.evaluations_succeeded,
            "evaluations_failed": run.ledger.evaluations_failed,
            "candidate_proposals": run.ledger.candidate_proposals,
            "llm_calls": 0,
            "tokens": 0,
            "known_cost": run.ledger.known_cost,
            "cost_unit": run.ledger.cost_unit,
            "financial_cost": 0.0,
            "network": "unused",
            "best_observation_id": run.best_observation_id,
            "best_objective": run.best_objective,
            "replay_checksum": run.replay_checksum,
        },
    )


def _write_json(path: Path, value: dict[str, JsonValue]) -> None:
    path.write_text(f"{canonical_json(value)}\n", encoding="utf-8")


def _write_jsonl(path: Path, values: list[dict[str, JsonValue]]) -> None:
    path.write_text("".join(f"{canonical_json(value)}\n" for value in values), encoding="utf-8")


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a mapping")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{name} keys do not match the EBBO smoke schema")


def _integer(value: Any, name: str, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError(f"{name} must be an integer" + (f" >= {minimum}" if minimum else ""))
    return value


def _number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        raise ValueError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return result
