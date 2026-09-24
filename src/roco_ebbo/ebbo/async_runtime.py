"""Opt-in P9c deterministic fake-asynchronous EBBO engineering smoke."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml  # type: ignore[import-untyped]

from roco_ebbo.ebbo.async_ledger import AsyncEBBOLedger
from roco_ebbo.ebbo.async_scheduler import AsyncMockScheduler
from roco_ebbo.ebbo.baseline import (
    MockSearchSpace,
    NearestObservationSurrogate,
    SurrogateSample,
    build_candidate_pool,
)
from roco_ebbo.ebbo.contracts import JsonValue, require_json_safe, stable_id
from roco_ebbo.ebbo.oracle import MOCK_COST_UNIT, MockExpensiveOracle, MockOracleOutcome
from roco_ebbo.ebbo.runtime import (
    EBBOSmokeSettings,
    _write_json,
    _write_jsonl,
    load_ebbo_smoke_settings,
)
from roco_ebbo.ebbo.store import ObservationStore

ASYNC_SMOKE_CONFIG_VERSION = "ebbo-async-mock-smoke-config-v1"
ASYNC_SMOKE_RUN_VERSION = "ebbo-async-mock-smoke-run-v1"
MOCK_COMPLETION_POLICY = "reverse-ready-v1"


@dataclass(frozen=True, slots=True)
class AsyncSmokeSettings:
    baseline: EBBOSmokeSettings
    max_concurrency: int
    cancel_after_accept_indices: tuple[int, ...]
    outcomes: dict[int, MockOracleOutcome]
    config_snapshot: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class AsyncSmokeRun:
    scheduler: AsyncMockScheduler
    complete: bool
    replay_checksum: str

    @property
    def ledger(self) -> AsyncEBBOLedger:
        return self.scheduler.ledger

    def summary(self) -> dict[str, JsonValue]:
        ledger = self.ledger
        return {
            "schema_version": "ebbo-async-mock-summary-v1",
            "run_id": self.scheduler.run_id,
            "complete": self.complete,
            "oracle_calls": ledger.oracle_calls,
            "evaluations_succeeded": ledger.evaluations_succeeded,
            "evaluations_failed": ledger.evaluations_failed,
            "failure_breakdown": dict(sorted(ledger.failure_breakdown.items())),
            "candidate_proposals": ledger.candidate_proposals,
            "known_cost": ledger.known_cost,
            "unknown_cost_attempt_ids": cast(
                list[JsonValue], sorted(ledger.unknown_cost_attempt_ids)
            ),
            "cost_unit": ledger.cost_unit,
            "llm_calls": ledger.llm_calls,
            "tokens": ledger.tokens,
            "financial_cost": 0.0,
            "network": "unused",
            "replay_checksum": self.replay_checksum,
            "scope": "offline-fake-async-engineering-only-not-performance-evidence",
        }


def load_async_smoke_settings(path: str | Path) -> AsyncSmokeSettings:
    source = Path(path)
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "baseline_config",
        "async",
        "outcomes",
    }:
        raise ValueError("P9c async smoke config schema mismatch")
    if raw["schema_version"] != ASYNC_SMOKE_CONFIG_VERSION:
        raise ValueError("unsupported P9c smoke config")
    base_name = raw["baseline_config"]
    if not isinstance(base_name, str) or not base_name or Path(base_name).name != base_name:
        raise ValueError("baseline_config must be a sibling filename")
    options = raw["async"]
    if not isinstance(options, dict) or set(options) != {
        "max_concurrency",
        "completion_policy",
        "cancel_after_accept_indices",
    }:
        raise ValueError("P9c async options schema mismatch")
    count = options["max_concurrency"]
    if type(count) is not int or count < 1:
        raise ValueError("max_concurrency must be a positive integer")
    if options["completion_policy"] != MOCK_COMPLETION_POLICY:
        raise ValueError("unsupported Mock completion policy")
    cancels = options["cancel_after_accept_indices"]
    if not isinstance(cancels, list) or any(type(x) is not int or x < 0 for x in cancels):
        raise ValueError("invalid cancellation indexes")
    if len(set(cancels)) != len(cancels):
        raise ValueError("duplicate cancellation index")
    outcomes_raw = raw["outcomes"]
    if not isinstance(outcomes_raw, list):
        raise ValueError("outcomes must be a list")
    outcomes: dict[int, MockOracleOutcome] = {}
    for item in outcomes_raw:
        if not isinstance(item, dict) or set(item) != {"x", "kind", "actual_cost"}:
            raise ValueError("Mock outcome schema mismatch")
        x = item["x"]
        cost = item["actual_cost"]
        if type(x) is not int or x in outcomes:
            raise ValueError("invalid or duplicate outcome x")
        if cost is not None and (type(cost) not in (int, float) or not 0 <= cost < float("inf")):
            raise ValueError("actual_cost must be finite non-negative or null")
        outcomes[x] = MockOracleOutcome(item["kind"], cost)
    base = load_ebbo_smoke_settings(source.parent / base_name)
    space = MockSearchSpace(base.lower, base.upper)
    for x in outcomes:
        space.candidate(x)
    if any(index >= base.max_oracle_calls for index in cancels):
        raise ValueError("cancellation index exceeds oracle call ceiling")
    require_json_safe(raw)
    return AsyncSmokeSettings(
        baseline=base,
        max_concurrency=count,
        cancel_after_accept_indices=tuple(cancels),
        outcomes=outcomes,
        config_snapshot=cast(dict[str, JsonValue], raw),
    )


def run_async_smoke(
    settings: AsyncSmokeSettings,
    *,
    output_dir: str | Path,
    resume: bool = False,
    interrupt_after: int | None = None,
) -> AsyncSmokeRun:
    """Run or explicitly resume only from a complete checkpoint action boundary."""
    if interrupt_after is not None and (type(interrupt_after) is not int or interrupt_after < 1):
        raise ValueError("interrupt_after must be a positive action count")
    root = Path(output_dir)
    if not resume and root.exists():
        raise FileExistsError(f"P9c output directory already exists: {root}")
    if resume and not root.is_dir():
        raise ValueError("P9c resume requires an existing output directory")
    base = settings.baseline
    search_space = MockSearchSpace(base.lower, base.upper)
    run_id = stable_id(
        "run",
        {
            "schema_version": ASYNC_SMOKE_RUN_VERSION,
            "config": settings.config_snapshot,
            "baseline_config": base.config_snapshot,
        },
    )
    digest = stable_id(
        "async-config",
        {
            "config": settings.config_snapshot,
            "baseline_config": base.config_snapshot,
        },
    )
    store = ObservationStore(root)
    oracle = MockExpensiveOracle(search_space, outcomes=settings.outcomes)
    if resume:
        scheduler = AsyncMockScheduler.resume(
            oracle=oracle,
            store=store,
            run_id=run_id,
            root_seed=base.root_seed,
            config_digest=digest,
            max_oracle_calls=base.max_oracle_calls,
            max_candidate_proposals=base.max_candidate_proposals,
            max_cost=base.max_cost,
            max_concurrency=settings.max_concurrency,
        )
    else:
        scheduler = AsyncMockScheduler(
            oracle=oracle,
            ledger=AsyncEBBOLedger(
                base.max_oracle_calls,
                base.max_candidate_proposals,
                base.max_cost,
                MOCK_COST_UNIT,
                max_concurrency=settings.max_concurrency,
            ),
            store=store,
            run_id=run_id,
            root_seed=base.root_seed,
            config_digest=digest,
        )
    started = time.perf_counter()
    actions = 0
    while True:
        pending = scheduler.pending
        reserved = next((p for p in pending if p.status.value == "reserved"), None)
        cancel_ready = next(
            (
                p
                for p in pending
                if p.status.value == "accepted"
                and p.request.logical_evaluation_index in settings.cancel_after_accept_indices
            ),
            None,
        )
        cancel_ack = next((p for p in pending if p.status.value == "cancel_requested"), None)
        if reserved is not None:
            scheduler.accept(reserved.request.request_id)
        elif cancel_ready is not None:
            scheduler.cancel(cancel_ready.request.request_id)
        elif cancel_ack is not None:
            scheduler.acknowledge_cancel(cancel_ack.request.request_id)
        elif (
            scheduler.ledger.oracle_calls < base.max_oracle_calls
            and scheduler.ledger.outstanding < settings.max_concurrency
            and not scheduler.ledger.unknown_cost_attempt_ids
            and not scheduler.ledger.exceeded_limits
            and (
                scheduler.ledger.max_cost is None
                or scheduler.ledger.known_cost + scheduler.ledger.expected_cost_held + 1.0
                <= scheduler.ledger.max_cost
            )
        ):
            surrogate = NearestObservationSurrogate(search_space, base.prior_mean)
            for observation in store.observations:
                if observation.objective is not None:
                    surrogate = surrogate.updated(
                        SurrogateSample(
                            candidate_id=observation.candidate_id,
                            x=search_space.validate_candidate(observation.candidate),
                            objective=observation.objective,
                            observation_id=observation.observation_id,
                        )
                    )
            remaining_proposals = (
                base.max_candidate_proposals - scheduler.ledger.candidate_proposals
            )
            if remaining_proposals > 0:
                pool = build_candidate_pool(
                    search_space=search_space,
                    surrogate=surrogate,
                    root_seed=base.root_seed,
                    iteration=len(scheduler.requests),
                    pool_size=min(base.pool_size, remaining_proposals),
                    beta=base.beta,
                    excluded_candidate_ids=set(scheduler.dispatched_candidate_ids)
                    | {p.request.candidate_id for p in pending},
                    ledger=scheduler.ledger,
                )
                if pool.entries:
                    scheduler.reserve(pool)
                elif pending:
                    scheduler.complete(
                        max(
                            (p for p in pending if p.attempt is not None),
                            key=lambda p: p.request.logical_evaluation_index,
                        ).request.request_id
                    )
                else:
                    break
            elif pending:
                scheduler.complete(
                    max(
                        (p for p in pending if p.attempt is not None),
                        key=lambda p: p.request.logical_evaluation_index,
                    ).request.request_id
                )
            else:
                break
        elif pending:
            scheduler.complete(
                max(
                    (p for p in pending if p.attempt is not None),
                    key=lambda p: p.request.logical_evaluation_index,
                ).request.request_id
            )
        else:
            break
        actions += 1
        if interrupt_after is not None and actions >= interrupt_after:
            return AsyncSmokeRun(
                scheduler, False, store.replay_checksum(scheduler.ledger.replay_dict())
            )
    scheduler.ledger.observe_wall_time(time.perf_counter() - started)
    result = AsyncSmokeRun(scheduler, True, store.replay_checksum(scheduler.ledger.replay_dict()))
    _write_artifacts(result, settings, root)
    return result


def _write_artifacts(run: AsyncSmokeRun, settings: AsyncSmokeSettings, root: Path) -> None:
    scheduler = run.scheduler
    _write_json(
        root / "manifest.json",
        {
            "schema_version": ASYNC_SMOKE_RUN_VERSION,
            "run_id": scheduler.run_id,
            "config": settings.config_snapshot,
            "baseline_config": settings.baseline.config_snapshot,
            "completion_policy": MOCK_COMPLETION_POLICY,
            "network": "unused",
            "financial_cost": 0.0,
            "scope": "P9c-offline-fake-async-engineering-only",
        },
    )
    _write_jsonl(root / "candidate_pools.jsonl", [p.to_dict() for p in scheduler.pools])
    _write_jsonl(root / "requests.jsonl", [r.to_dict() for r in scheduler.requests])
    _write_jsonl(root / "results.jsonl", [r.to_dict() for r in scheduler.results])
    _write_json(root / "ledger.json", scheduler.ledger.to_dict())
    _write_json(
        root / "replay.json",
        {
            "schema_version": "ebbo-async-replay-v1",
            "checksum": run.replay_checksum,
            "excludes": ["wall_time_seconds", "*_at_utc"],
            "store_snapshot": scheduler.store.snapshot(),
        },
    )
    _write_json(root / "summary.json", run.summary())
