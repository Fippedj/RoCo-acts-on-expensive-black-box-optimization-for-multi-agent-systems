"""Four comparable, wholly offline P9b role-control engineering smoke paths."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml  # type: ignore[import-untyped]

from roco_ebbo.ebbo.baseline import (
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
from roco_ebbo.ebbo.oracle import MOCK_COST_UNIT, MockExpensiveOracle
from roco_ebbo.ebbo.role_scheduler import RestrictedRoleScheduler
from roco_ebbo.ebbo.roles import (
    ROLE_CONTROL_VERSION,
    DeterministicFakeRoleProvider,
    RoleController,
    RoleProvider,
)
from roco_ebbo.ebbo.runtime import EBBOSmokeSettings, load_ebbo_smoke_settings, run_ebbo_smoke
from roco_ebbo.ebbo.scheduler import SerialScheduler
from roco_ebbo.ebbo.store import ObservationStore

ROLE_SMOKE_CONFIG_VERSION = "ebbo-role-mock-smoke-config-v1"
ROLE_MODES = ("full", "no_roles", "no_critic", "no_integrator")


@dataclass(frozen=True, slots=True)
class RoleSmokeSettings:
    baseline: EBBOSmokeSettings
    veto_mode: str
    max_role_calls: int
    max_role_tokens: int
    config_snapshot: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class RoleSmokeResult:
    mode: str
    run_id: str
    observations: tuple[Observation, ...]
    pools: tuple[CandidatePool, ...]
    ledger: EBBOLedger
    store: ObservationStore
    scheduler: SerialScheduler
    replay_checksum: str

    def summary(self) -> dict[str, JsonValue]:
        return {
            "schema_version": "ebbo-role-mock-summary-v1",
            "mode": self.mode,
            "run_id": self.run_id,
            "oracle_calls": self.ledger.oracle_calls,
            "evaluations_succeeded": self.ledger.evaluations_succeeded,
            "evaluations_failed": self.ledger.evaluations_failed,
            "candidate_proposals": self.ledger.candidate_proposals,
            "llm_calls": self.ledger.llm_calls,
            "tokens": self.ledger.tokens,
            "input_tokens": self.ledger.role_input_tokens,
            "output_tokens": self.ledger.role_output_tokens,
            "known_cost": self.ledger.known_cost,
            "cost_unit": self.ledger.cost_unit,
            "financial_cost": 0.0,
            "network": "unused",
            "replay_checksum": self.replay_checksum,
            "scope": "offline-engineering-mock-not-performance-evidence",
        }


def load_role_smoke_settings(path: str | Path) -> RoleSmokeSettings:
    source = Path(path)
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "baseline_config", "roles"}:
        raise ValueError("P9b smoke config schema mismatch")
    if raw["schema_version"] != ROLE_SMOKE_CONFIG_VERSION:
        raise ValueError("unsupported P9b smoke config")
    base = raw["baseline_config"]
    if not isinstance(base, str) or not base or Path(base).name != base:
        raise ValueError("baseline_config must be a sibling filename")
    roles = raw["roles"]
    if not isinstance(roles, dict) or set(roles) != {
        "provider",
        "veto_mode",
        "max_role_calls",
        "max_role_tokens",
    }:
        raise ValueError("P9b role config schema mismatch")
    if roles["provider"] != "ebbo-deterministic-fake-role-provider-v1":
        raise ValueError("P9b smoke permits only the injected offline fake provider")
    if roles["veto_mode"] not in {"advisory", "hard"}:
        raise ValueError("invalid critic veto mode")
    for key in ("max_role_calls", "max_role_tokens"):
        if type(roles[key]) is not int or roles[key] < 0:
            raise ValueError(f"{key} must be a non-negative integer")
    require_json_safe(raw)
    return RoleSmokeSettings(
        baseline=load_ebbo_smoke_settings(source.parent / base),
        veto_mode=roles["veto_mode"],
        max_role_calls=roles["max_role_calls"],
        max_role_tokens=roles["max_role_tokens"],
        config_snapshot=cast(dict[str, JsonValue], raw),
    )


def run_role_smoke(
    settings: RoleSmokeSettings,
    *,
    output_dir: str | Path,
    provider_factory: type[RoleProvider] = DeterministicFakeRoleProvider,
) -> dict[str, RoleSmokeResult]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    results: dict[str, RoleSmokeResult] = {}
    for mode in ROLE_MODES:
        directory = root / mode
        if mode == "no_roles":
            base = run_ebbo_smoke(settings.baseline, output_dir=directory)
            result = RoleSmokeResult(
                mode=mode,
                run_id=base.run_id,
                observations=base.observations,
                pools=base.pools,
                ledger=base.ledger,
                store=base.store,
                scheduler=base.scheduler,
                replay_checksum=base.replay_checksum,
            )
        else:
            result = _run_controlled(settings, mode, directory, provider_factory)
        results[mode] = result
        _write_json(directory / "role_summary.json", result.summary())
    _write_json(
        root / "matrix.json",
        {
            "schema_version": "ebbo-role-mock-matrix-v1",
            "scope": "offline-control-flow-only-not-performance-evidence",
            "baseline_config": settings.baseline.config_snapshot,
            "role_config": settings.config_snapshot,
            "modes": {mode: result.summary() for mode, result in results.items()},
            "network": "unused",
        },
    )
    return results


def _run_controlled(
    settings: RoleSmokeSettings,
    mode: str,
    directory: Path,
    provider_factory: type[RoleProvider],
) -> RoleSmokeResult:
    base = settings.baseline
    search_space = MockSearchSpace(base.lower, base.upper)
    run_id = stable_id(
        "run",
        {
            "schema_version": ROLE_CONTROL_VERSION,
            "mode": mode,
            "baseline_config": base.config_snapshot,
            "roles": settings.config_snapshot,
        },
    )
    ledger = EBBOLedger(
        max_oracle_calls=base.max_oracle_calls,
        max_candidate_proposals=base.max_candidate_proposals,
        max_cost=base.max_cost,
        cost_unit=MOCK_COST_UNIT,
        max_role_calls=settings.max_role_calls,
        max_role_tokens=settings.max_role_tokens,
    )
    store = ObservationStore(directory)
    serial = SerialScheduler(
        oracle=MockExpensiveOracle(search_space),
        ledger=ledger,
        store=store,
        run_id=run_id,
        root_seed=base.root_seed,
    )
    gate = RestrictedRoleScheduler(serial)
    controller = RoleController(
        provider=provider_factory(),
        ledger=ledger,
        store=store,
        root_seed=base.root_seed,
        veto_mode=settings.veto_mode,
    )
    surrogate = NearestObservationSurrogate(search_space, base.prior_mean)
    pools: list[CandidatePool] = []
    observations: list[Observation] = []
    started = time.perf_counter()
    for iteration in range(base.iterations):
        pool = build_candidate_pool(
            search_space=search_space,
            surrogate=surrogate,
            root_seed=base.root_seed,
            iteration=iteration,
            pool_size=base.pool_size,
            beta=base.beta,
            excluded_candidate_ids=set(serial.dispatched_candidate_ids),
            ledger=ledger,
        )
        pools.append(pool)
        if not pool.entries:
            break
        decision = controller.choose(pool, iteration=iteration, mode=mode)
        if decision.selected_entry_id is None:
            break
        observation = gate.dispatch(pool, decision)
        observations.append(observation)
        if observation.objective is not None:
            request = serial.requests[-1]
            surrogate = surrogate.updated(
                SurrogateSample(
                    candidate_id=request.candidate_id,
                    x=search_space.validate_candidate(request.candidate),
                    objective=observation.objective,
                    observation_id=observation.observation_id,
                )
            )
        if ledger.oracle_calls >= base.max_oracle_calls:
            break
    ledger.observe_wall_time(time.perf_counter() - started)
    result = RoleSmokeResult(
        mode=mode,
        run_id=run_id,
        observations=tuple(observations),
        pools=tuple(pools),
        ledger=ledger,
        store=store,
        scheduler=serial,
        replay_checksum=store.replay_checksum(ledger.replay_dict()),
    )
    _write_json(
        directory / "manifest.json",
        {
            "schema_version": ROLE_CONTROL_VERSION,
            "run_id": run_id,
            "mode": mode,
            "config": settings.config_snapshot,
            "baseline_config": base.config_snapshot,
            "network": "unused",
            "financial_cost": 0.0,
        },
    )
    _write_jsonl(directory / "candidate_pools.jsonl", [pool.to_dict() for pool in pools])
    _write_jsonl(directory / "requests.jsonl", [r.to_dict() for r in serial.requests])
    _write_jsonl(directory / "results.jsonl", [r.to_dict() for r in serial.results])
    _write_json(directory / "ledger.json", ledger.to_dict())
    _write_json(
        directory / "posterior.json",
        {
            "schema_version": "ebbo-nearest-observation-surrogate-v1",
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
        directory / "replay.json",
        {
            "schema_version": "ebbo-role-replay-v1",
            "checksum": result.replay_checksum,
            "excludes": ["wall_time_seconds", "*_at_utc"],
            "store_snapshot": store.snapshot(),
        },
    )
    return result


def _write_json(path: Path, value: dict[str, JsonValue]) -> None:
    path.write_text(f"{canonical_json(value)}\n", encoding="utf-8")


def _write_jsonl(path: Path, values: list[dict[str, JsonValue]]) -> None:
    path.write_text("".join(f"{canonical_json(value)}\n" for value in values), encoding="utf-8")
