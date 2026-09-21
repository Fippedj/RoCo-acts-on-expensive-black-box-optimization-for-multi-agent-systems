"""FSU MKP protocol-only integration dry-run with an offline Mock provider."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml  # type: ignore[import-untyped]

from roco_ebbo.benchmarks import (
    FSU_MKP_LICENSE_ID,
    FSU_MKP_PROTOCOL_VERSION,
    FSU_MKP_SOURCE_ID,
    FSU_MKP_SOURCE_RELEASE,
    FSU_MKP_SPLIT_POLICY_VERSION,
    MKPDatasetManifest,
    MKPInstance,
    load_fsu_mkp_dataset,
)
from roco_ebbo.core import BudgetLedger
from roco_ebbo.evaluation import MKPCodeEvaluator
from roco_ebbo.evolution import EoHEngine, RoCoCollaborator
from roco_ebbo.llm import (
    MKP_MOCK_PROVIDER_VERSION,
    ROLE_TEMPERATURES,
    MKPMockLLMProvider,
    RoCoRole,
)

CONFIG_SCHEMA_VERSION = "roco-mkp-fsu-experiment-config-v1"
RESULT_SCHEMA_VERSION = "roco-multicop-experiment-result-v1"
PROMPT_VISIBILITY_VERSION = "mkp-fsu-full-instance-visibility-v1"
PROMPT_VERSION = "mkp-fsu-full-instance-prompt-v1"
EVALUATOR_CONTRACT_VERSION = "mkp-fsu-evaluator-v1"
DEFAULT_BUDGET_PROFILE_ID = "mkp-fsu-mock-engineering-v1"
METHOD_VERSIONS = {"eoh": "eoh-stage2-v1", "roco": "roco-stage3-v1"}
_METHODS = frozenset(METHOD_VERSIONS)
_ALLOWED_PROMPT_FIELDS = (
    "instance_id",
    "capacities",
    "weights",
    "profits",
    "objective",
    "constraints",
    "candidate_signature",
)
_EXCLUDED_PROMPT_FIELDS = (
    "optional_reference",
    "reference_assignment",
    "reference_objective",
    "claimed_optimum",
)


class MKPProtocolError(ValueError):
    """Raised when an MKP config or replay artifact fails its frozen contract."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise MKPProtocolError(f"value is not canonical JSON: {exc}") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _derive_seed(seed: int, stream: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{stream}".encode()).digest()[:8], "big")


def _exact_keys(value: dict[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise MKPProtocolError(f"{name} keys mismatch; missing={missing}, extra={extra}")


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise MKPProtocolError(f"{key} must be a mapping")
    return value


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise MKPProtocolError(f"{name} must be an integer >= {minimum}")
    return value


def _finite(value: Any, name: str, *, positive: bool = False) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise MKPProtocolError(f"{name} must be finite")
    resolved = float(value)
    if (positive and resolved <= 0) or (not positive and resolved < 0):
        qualifier = "greater than zero" if positive else "non-negative"
        raise MKPProtocolError(f"{name} must be {qualifier}")
    return resolved


@dataclass(frozen=True, slots=True)
class MKPBudgetProfile:
    """Engineering-only six-ledger hard ceiling for every MKP method."""

    profile_id: str
    max_llm_calls: int
    max_tokens: int
    max_generated_candidates: int
    max_valid_evals: int
    max_cost: float
    max_wall_time: float
    cost_currency: str = "USD"

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise MKPProtocolError("budget profile_id must be non-empty")
        for name in (
            "max_llm_calls",
            "max_tokens",
            "max_generated_candidates",
            "max_valid_evals",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise MKPProtocolError(f"{name} must be an integer >= 1")
        for name in ("max_cost", "max_wall_time"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise MKPProtocolError(f"{name} must be finite and greater than zero")
        if not self.cost_currency:
            raise MKPProtocolError("cost_currency must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "max_llm_calls": self.max_llm_calls,
            "max_tokens": self.max_tokens,
            "max_generated_candidates": self.max_generated_candidates,
            "max_valid_evals": self.max_valid_evals,
            "max_cost": self.max_cost,
            "max_wall_time": self.max_wall_time,
            "cost_currency": self.cost_currency,
        }

    def new_ledger(self) -> BudgetLedger:
        return BudgetLedger(
            max_llm_calls=self.max_llm_calls,
            max_tokens=self.max_tokens,
            max_generated_candidates=self.max_generated_candidates,
            max_valid_evals=self.max_valid_evals,
            max_cost=self.max_cost,
            max_wall_time=self.max_wall_time,
            cost_currency=self.cost_currency,
        )


@dataclass(frozen=True, slots=True)
class MKPExperimentSettings:
    root_seed: int
    methods: tuple[str, ...]
    budgets: MKPBudgetProfile
    population_size: int
    generations: int
    candidates_per_operator: int
    collaboration_rounds: int
    elite_sampling_power: float
    role_temperatures: dict[RoCoRole, float]
    evaluator_timeout_seconds: float
    config_snapshot: dict[str, Any]

    def __post_init__(self) -> None:
        if type(self.root_seed) is not int or self.root_seed < 0:
            raise MKPProtocolError("root_seed must be a non-negative integer")
        if not self.methods or any(method not in _METHODS for method in self.methods):
            raise MKPProtocolError("methods must be a non-empty subset of eoh and roco")
        if len(set(self.methods)) != len(self.methods):
            raise MKPProtocolError("methods must not repeat")
        if self.population_size < 2 or self.generations < 1 or self.candidates_per_operator < 1:
            raise MKPProtocolError("invalid evolution population/generation/multiplicity")
        if self.collaboration_rounds < 1:
            raise MKPProtocolError("collaboration_rounds must be at least one")
        if not math.isfinite(self.elite_sampling_power) or self.elite_sampling_power <= 0:
            raise MKPProtocolError("elite_sampling_power must be finite and positive")
        if set(self.role_temperatures) != set(RoCoRole) or any(
            not math.isfinite(value) or value < 0 for value in self.role_temperatures.values()
        ):
            raise MKPProtocolError("all role temperatures must be finite and non-negative")
        if not math.isfinite(self.evaluator_timeout_seconds) or self.evaluator_timeout_seconds <= 0:
            raise MKPProtocolError("evaluator timeout must be finite and positive")


def load_mkp_experiment_settings(path: str | Path) -> MKPExperimentSettings:
    """Load only the versioned, Mock-only, protocol-only MKP config."""

    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MKPProtocolError(f"cannot read MKP experiment config: {exc}") from exc
    if not isinstance(raw, dict):
        raise MKPProtocolError("MKP experiment config root must be a mapping")
    _exact_keys(
        raw, {"protocol", "llm", "dataset", "experiment", "evolution", "benchmark"}, "config"
    )
    protocol = _mapping(raw, "protocol")
    _exact_keys(protocol, {"schema_version", "dry_run"}, "protocol")
    if protocol != {"schema_version": CONFIG_SCHEMA_VERSION, "dry_run": True}:
        raise MKPProtocolError("only the versioned offline MKP dry-run is supported")

    llm = _mapping(raw, "llm")
    _exact_keys(llm, {"provider", "network", "temperatures"}, "llm")
    if llm["provider"] != "mock" or llm["network"] != "unused":
        raise MKPProtocolError("MKP dry-run requires provider=mock and network=unused")
    raw_temperatures = llm["temperatures"]
    if not isinstance(raw_temperatures, dict):
        raise MKPProtocolError("llm.temperatures must be a mapping")
    role_temperatures = {
        role: _finite(raw_temperatures.get(role.value, default), f"temperature.{role.value}")
        for role, default in ROLE_TEMPERATURES.items()
    }

    dataset = _mapping(raw, "dataset")
    _exact_keys(
        dataset,
        {"source_version", "protocol_version", "split_policy_version", "split", "instances"},
        "dataset",
    )
    expected_instances = [f"p{number:02d}" for number in range(1, 7)]
    if (
        dataset["source_version"] != "mkp-fsu-knapsack-multiple-v1"
        or dataset["protocol_version"] != FSU_MKP_PROTOCOL_VERSION
        or dataset["split_policy_version"] != FSU_MKP_SPLIT_POLICY_VERSION
        or dataset["split"] != "protocol-only"
        or dataset["instances"] != expected_instances
    ):
        raise MKPProtocolError("dataset must be the frozen P01--P06 protocol-only inventory")

    experiment = _mapping(raw, "experiment")
    _exact_keys(experiment, {"root_seed", "methods", "prompt_visibility", "budgets"}, "experiment")
    if experiment["prompt_visibility"] != "full_instance":
        raise MKPProtocolError("MKP protocol supports only full_instance visibility")
    methods = experiment["methods"]
    if not isinstance(methods, list):
        raise MKPProtocolError("experiment.methods must be a list")
    budget_raw = _mapping(experiment, "budgets")
    _exact_keys(
        budget_raw,
        {
            "profile_id",
            "max_llm_calls",
            "max_tokens",
            "max_generated_candidates",
            "max_valid_evals",
            "max_cost",
            "max_wall_time",
            "cost_currency",
        },
        "experiment.budgets",
    )
    budgets = MKPBudgetProfile(
        profile_id=str(budget_raw["profile_id"]),
        max_llm_calls=_integer(budget_raw["max_llm_calls"], "max_llm_calls", minimum=1),
        max_tokens=_integer(budget_raw["max_tokens"], "max_tokens", minimum=1),
        max_generated_candidates=_integer(
            budget_raw["max_generated_candidates"], "max_generated_candidates", minimum=1
        ),
        max_valid_evals=_integer(budget_raw["max_valid_evals"], "max_valid_evals", minimum=1),
        max_cost=_finite(budget_raw["max_cost"], "max_cost", positive=True),
        max_wall_time=_finite(budget_raw["max_wall_time"], "max_wall_time", positive=True),
        cost_currency=str(budget_raw["cost_currency"]),
    )
    evolution = _mapping(raw, "evolution")
    _exact_keys(
        evolution,
        {
            "population_size",
            "generations",
            "candidates_per_operator",
            "collaboration_rounds",
            "elite_sampling_power",
        },
        "evolution",
    )
    benchmark = _mapping(raw, "benchmark")
    _exact_keys(benchmark, {"id", "evaluator_contract", "evaluator_timeout_seconds"}, "benchmark")
    if benchmark["id"] != "mkp-01" or benchmark["evaluator_contract"] != EVALUATOR_CONTRACT_VERSION:
        raise MKPProtocolError("benchmark must use the frozen MKP evaluator contract")
    return MKPExperimentSettings(
        root_seed=_integer(experiment["root_seed"], "experiment.root_seed"),
        methods=tuple(str(method) for method in methods),
        budgets=budgets,
        population_size=_integer(evolution["population_size"], "population_size", minimum=2),
        generations=_integer(evolution["generations"], "generations", minimum=1),
        candidates_per_operator=_integer(
            evolution["candidates_per_operator"], "candidates_per_operator", minimum=1
        ),
        collaboration_rounds=_integer(
            evolution["collaboration_rounds"], "collaboration_rounds", minimum=1
        ),
        elite_sampling_power=_finite(
            evolution["elite_sampling_power"], "elite_sampling_power", positive=True
        ),
        role_temperatures=role_temperatures,
        evaluator_timeout_seconds=_finite(
            benchmark["evaluator_timeout_seconds"],
            "evaluator_timeout_seconds",
            positive=True,
        ),
        config_snapshot=raw,
    )


def build_full_instance_prompt(instance: MKPInstance) -> str:
    """Render only allowed full-instance fields; references never enter this payload."""

    payload = {
        "contract": PROMPT_VERSION,
        "instance_id": instance.instance_id,
        "capacities": list(instance.capacities),
        "weights": list(instance.weights),
        "profits": list(instance.profits),
        "objective": "maximize raw profit; runtime selection minimizes negative raw profit",
        "constraints": (
            "each item is omitted or assigned to exactly one knapsack; each capacity is hard"
        ),
        "candidate_signature": "heuristic(capacities, weights, profits) -> list[list[int]]",
    }
    return _canonical_json(payload)


def prompt_visibility_contract(instance: MKPInstance) -> dict[str, Any]:
    """Return the versioned full-instance information-set audit record."""

    base_prompt = build_full_instance_prompt(instance)
    role_prompts = _role_prompts(base_prompt)
    return {
        "contract_version": PROMPT_VISIBILITY_VERSION,
        "condition": "full_instance",
        "allowed_fields_hash": _sha256(list(_ALLOWED_PROMPT_FIELDS)),
        "excluded_fields": list(_EXCLUDED_PROMPT_FIELDS),
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": _sha256(
            {"eoh": base_prompt, "roles": {role.value: role_prompts[role] for role in RoCoRole}}
        ),
        "reference_visible": False,
        "oracle": False,
    }


def _role_prompts(base_prompt: str) -> dict[RoCoRole, str]:
    instructions = {
        RoCoRole.EXPLORER: "Propose a diverse feasible assignment heuristic.",
        RoCoRole.EXPLOITER: "Propose a conservative feasible assignment heuristic.",
        RoCoRole.CRITIC: "Compare candidate negative-profit scores and feasibility only.",
        RoCoRole.INTEGRATOR: "Integrate feedback into one feasible assignment heuristic.",
    }
    return {role: f"{base_prompt}\nrole={role.value}\n{instructions[role]}" for role in RoCoRole}


@dataclass(frozen=True, slots=True)
class MKPExperimentResult:
    """Strict P7a-shaped run record with a non-time replay checksum."""

    run_id: str
    benchmark: dict[str, Any]
    dataset: dict[str, Any]
    randomness: dict[str, Any]
    method: dict[str, Any]
    provider: dict[str, Any]
    prompt_visibility: dict[str, Any]
    budget: dict[str, Any]
    evaluation: dict[str, Any]
    status: Literal["completed", "budget_exhausted", "invalid", "failed"]
    failure: dict[str, str] | None
    replay: dict[str, bool]

    def __post_init__(self) -> None:
        if not self.run_id or self.status not in {
            "completed",
            "budget_exhausted",
            "invalid",
            "failed",
        }:
            raise MKPProtocolError("run_id or status is invalid")
        _validate_result_nested(self)
        if self.status == "completed" and self.failure is not None:
            raise MKPProtocolError("completed result cannot contain a failure")
        if self.status in {"invalid", "failed"} and self.failure is None:
            raise MKPProtocolError("invalid/failed result must contain a structured failure")
        if self.status != "completed" and self.failure is not None:
            _exact_keys(self.failure, {"phase", "type", "safe_message"}, "result.failure")
            if not all(isinstance(value, str) and value for value in self.failure.values()):
                raise MKPProtocolError("result.failure fields must be non-empty strings")

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "benchmark": self.benchmark,
            "dataset": self.dataset,
            "randomness": self.randomness,
            "method": self.method,
            "provider": self.provider,
            "prompt_visibility": self.prompt_visibility,
            "budget": self.budget,
            "evaluation": self.evaluation,
            "status": self.status,
            "failure": self.failure,
            "replay": self.replay,
        }

    @property
    def replay_checksum(self) -> str:
        payload = deepcopy(self._payload())
        payload["budget"]["actual"]["wall_time"] = None
        return _sha256(payload)

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "replay_checksum": self.replay_checksum}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MKPExperimentResult:
        fields = {
            "schema_version",
            "run_id",
            "benchmark",
            "dataset",
            "randomness",
            "method",
            "provider",
            "prompt_visibility",
            "budget",
            "evaluation",
            "status",
            "failure",
            "replay",
            "replay_checksum",
        }
        _exact_keys(value, fields, "MKP result")
        if value["schema_version"] != RESULT_SCHEMA_VERSION:
            raise MKPProtocolError("unsupported MKP result schema version")
        nested = (
            "benchmark",
            "dataset",
            "randomness",
            "method",
            "provider",
            "prompt_visibility",
            "budget",
            "evaluation",
            "replay",
        )
        if any(not isinstance(value[name], dict) for name in nested):
            raise MKPProtocolError("MKP result nested fields must be objects")
        if value["failure"] is not None and not isinstance(value["failure"], dict):
            raise MKPProtocolError("MKP result failure must be an object or null")
        result = cls(
            run_id=str(value["run_id"]),
            benchmark=value["benchmark"],
            dataset=value["dataset"],
            randomness=value["randomness"],
            method=value["method"],
            provider=value["provider"],
            prompt_visibility=value["prompt_visibility"],
            budget=value["budget"],
            evaluation=value["evaluation"],
            status=value["status"],
            failure=value["failure"],
            replay=value["replay"],
        )
        if value["replay_checksum"] != result.replay_checksum:
            raise MKPProtocolError(f"replay checksum mismatch for {result.run_id}")
        return result


def _validate_result_nested(result: MKPExperimentResult) -> None:
    _exact_keys(
        result.benchmark,
        {"id", "version", "evidence_level", "source_id", "release", "license_id"},
        "result.benchmark",
    )
    if result.benchmark != {
        "id": "mkp-01",
        "version": FSU_MKP_PROTOCOL_VERSION,
        "evidence_level": "E3",
        "source_id": FSU_MKP_SOURCE_ID,
        "release": FSU_MKP_SOURCE_RELEASE,
        "license_id": FSU_MKP_LICENSE_ID,
    }:
        raise MKPProtocolError("result benchmark identity is invalid")
    _exact_keys(
        result.dataset,
        {
            "inventory_checksum",
            "instance_id",
            "instance_checksum",
            "split",
            "split_policy_version",
        },
        "result.dataset",
    )
    if (
        result.dataset["split"] != "protocol-only"
        or result.dataset["split_policy_version"] != FSU_MKP_SPLIT_POLICY_VERSION
    ):
        raise MKPProtocolError("result dataset split is invalid")
    for name in ("inventory_checksum", "instance_checksum"):
        if not isinstance(result.dataset[name], str) or len(result.dataset[name]) != 64:
            raise MKPProtocolError(f"result dataset {name} is invalid")
    if not isinstance(result.dataset["instance_id"], str) or not result.dataset["instance_id"]:
        raise MKPProtocolError("result dataset instance_id is invalid")
    _exact_keys(
        result.randomness, {"root_seed", "derived_run_seed", "provider_seed"}, "result.randomness"
    )
    for name in result.randomness:
        _integer(result.randomness[name], f"result.randomness.{name}")
    _exact_keys(result.method, {"id", "version", "implementation_git_sha"}, "result.method")
    method_id = result.method.get("id")
    if method_id not in _METHODS or result.method.get("version") != METHOD_VERSIONS[method_id]:
        raise MKPProtocolError("result method identity is invalid")
    implementation_sha = result.method["implementation_git_sha"]
    if implementation_sha is not None and (
        not isinstance(implementation_sha, str)
        or len(implementation_sha) != 40
        or any(character not in "0123456789abcdef" for character in implementation_sha)
    ):
        raise MKPProtocolError("implementation_git_sha must be a lowercase full SHA or null")
    _exact_keys(
        result.provider,
        {
            "name",
            "network_state",
            "model",
            "adapter_contract",
            "tokenizer_counter",
            "pricing_version",
        },
        "result.provider",
    )
    if result.provider != {
        "name": "mock",
        "network_state": "unused",
        "model": "deterministic-mkp",
        "adapter_contract": MKP_MOCK_PROVIDER_VERSION,
        "tokenizer_counter": "mock-whitespace-v1",
        "pricing_version": "mock-zero-cost-v1",
    }:
        raise MKPProtocolError("result provider must be offline Mock")
    expected_prompt_keys = {
        "contract_version",
        "condition",
        "allowed_fields_hash",
        "excluded_fields",
        "prompt_version",
        "prompt_hash",
        "reference_visible",
        "oracle",
    }
    _exact_keys(result.prompt_visibility, expected_prompt_keys, "result.prompt_visibility")
    if (
        result.prompt_visibility["condition"] != "full_instance"
        or result.prompt_visibility["reference_visible"] is not False
        or result.prompt_visibility["oracle"] is not False
        or result.prompt_visibility["contract_version"] != PROMPT_VISIBILITY_VERSION
        or result.prompt_visibility["prompt_version"] != PROMPT_VERSION
        or result.prompt_visibility["allowed_fields_hash"] != _sha256(list(_ALLOWED_PROMPT_FIELDS))
        or result.prompt_visibility["excluded_fields"] != list(_EXCLUDED_PROMPT_FIELDS)
    ):
        raise MKPProtocolError("result prompt visibility is invalid")
    for name in ("allowed_fields_hash", "prompt_hash"):
        if (
            not isinstance(result.prompt_visibility[name], str)
            or len(result.prompt_visibility[name]) != 64
        ):
            raise MKPProtocolError(f"result prompt visibility {name} is invalid")
    _exact_keys(
        result.budget, {"profile_id", "hard_limits", "actual", "reached_limits"}, "result.budget"
    )
    hard_limits = result.budget["hard_limits"]
    if not isinstance(hard_limits, dict):
        raise MKPProtocolError("result budget hard_limits must be an object")
    if result.budget["profile_id"] != hard_limits.get("profile_id"):
        raise MKPProtocolError("budget profile identity mismatch")
    _exact_keys(
        hard_limits,
        {
            "profile_id",
            "max_llm_calls",
            "max_tokens",
            "max_generated_candidates",
            "max_valid_evals",
            "max_cost",
            "max_wall_time",
            "cost_currency",
        },
        "result.budget.hard_limits",
    )
    MKPBudgetProfile(
        profile_id=str(hard_limits["profile_id"]),
        max_llm_calls=_integer(hard_limits["max_llm_calls"], "hard max_llm_calls", minimum=1),
        max_tokens=_integer(hard_limits["max_tokens"], "hard max_tokens", minimum=1),
        max_generated_candidates=_integer(
            hard_limits["max_generated_candidates"], "hard max_generated_candidates", minimum=1
        ),
        max_valid_evals=_integer(hard_limits["max_valid_evals"], "hard max_valid_evals", minimum=1),
        max_cost=_finite(hard_limits["max_cost"], "hard max_cost", positive=True),
        max_wall_time=_finite(hard_limits["max_wall_time"], "hard max_wall_time", positive=True),
        cost_currency=str(hard_limits["cost_currency"]),
    )
    actual = result.budget["actual"]
    if not isinstance(actual, dict):
        raise MKPProtocolError("result budget actual must be an object")
    _exact_keys(
        actual,
        {
            "llm_calls",
            "input_tokens",
            "output_tokens",
            "tokens",
            "generated_candidates",
            "valid_evals",
            "cost",
            "cost_currency",
            "wall_time",
        },
        "result.budget.actual",
    )
    for name in (
        "llm_calls",
        "input_tokens",
        "output_tokens",
        "tokens",
        "generated_candidates",
        "valid_evals",
    ):
        _integer(actual[name], f"result budget actual {name}")
    if actual["tokens"] != actual["input_tokens"] + actual["output_tokens"]:
        raise MKPProtocolError("result token ledger is inconsistent")
    _finite(actual["cost"], "result cost")
    _finite(actual["wall_time"], "result wall_time")
    if actual["cost_currency"] != hard_limits["cost_currency"]:
        raise MKPProtocolError("result budget currencies do not match")
    if not isinstance(result.budget["reached_limits"], list) or not all(
        isinstance(name, str) for name in result.budget["reached_limits"]
    ):
        raise MKPProtocolError("result reached_limits must be a list")
    _exact_keys(
        result.evaluation,
        {
            "source_objective_direction",
            "selection_direction",
            "evaluator_contract",
            "timeout_scope",
            "metric_name",
            "reference_version_or_null",
            "best_score",
            "raw_profit",
            "normalized_score",
            "normalization_contract",
            "feasible",
        },
        "result.evaluation",
    )
    for name in ("best_score", "normalized_score"):
        value = result.evaluation[name]
        if value is not None and (
            type(value) not in (int, float) or not math.isfinite(float(value))
        ):
            raise MKPProtocolError(f"result evaluation {name} must be finite or null")
    raw_profit = result.evaluation["raw_profit"]
    if raw_profit is not None and type(raw_profit) is not int:
        raise MKPProtocolError("result raw_profit must be an integer or null")
    if result.evaluation["best_score"] is not None:
        if raw_profit is None or result.evaluation["best_score"] != -float(raw_profit):
            raise MKPProtocolError("result score must equal negative raw_profit")
    if (
        result.evaluation["source_objective_direction"] != "maximize"
        or result.evaluation["selection_direction"] != "minimize"
        or result.evaluation["evaluator_contract"] != EVALUATOR_CONTRACT_VERSION
        or result.evaluation["timeout_scope"] != "per-candidate"
        or result.evaluation["metric_name"] != "negative_raw_profit"
        or result.evaluation["reference_version_or_null"] is not None
        or result.evaluation["normalization_contract"]
        != "negative-profit-over-total-positive-profit-v1"
        or type(result.evaluation["feasible"]) is not bool
    ):
        raise MKPProtocolError("result evaluation contract is invalid")
    if result.status == "completed" and (
        result.evaluation["best_score"] is None
        or raw_profit is None
        or result.evaluation["normalized_score"] is None
        or result.evaluation["feasible"] is not True
    ):
        raise MKPProtocolError("completed result must contain one finite feasible result")
    _exact_keys(
        result.replay,
        {"dataset_verified", "split_verified", "result_verified", "non_time_state_verified"},
        "result.replay",
    )
    if any(type(value) is not bool for value in result.replay.values()):
        raise MKPProtocolError("result replay flags must be booleans")


@dataclass(frozen=True, slots=True)
class MKPExperimentRun:
    dataset: MKPDatasetManifest
    results: tuple[MKPExperimentResult, ...]


ProviderFactory = Callable[[int, str], MKPMockLLMProvider]


def execute_mkp_experiment(
    settings: MKPExperimentSettings,
    *,
    data_root: str | Path,
    provider_factory: ProviderFactory = MKPMockLLMProvider,
) -> MKPExperimentRun:
    """Execute P01--P06 × EoH/RoCo in a deterministic protocol-only matrix."""

    dataset = load_fsu_mkp_dataset(data_root)
    results = tuple(
        _execute_one(settings, dataset, instance, method, provider_factory)
        for instance in dataset.instances
        for method in settings.methods
    )
    return MKPExperimentRun(dataset=dataset, results=results)


def _execute_one(
    settings: MKPExperimentSettings,
    dataset: MKPDatasetManifest,
    instance: MKPInstance,
    method: str,
    provider_factory: ProviderFactory,
) -> MKPExperimentResult:
    derived_seed = _derive_seed(
        settings.root_seed,
        ":".join(
            (
                FSU_MKP_PROTOCOL_VERSION,
                instance.checksum,
                instance.split,
                "full_instance",
                method,
            )
        ),
    )
    provider_seed = _derive_seed(derived_seed, "mock-provider")
    run_digest = _sha256([instance.checksum, method, derived_seed])[:16]
    run_id = f"mkp-{instance.instance_id}-{method}-s{settings.root_seed}-{run_digest}"
    base_prompt = build_full_instance_prompt(instance)
    provider = provider_factory(provider_seed, base_prompt)
    ledger = settings.budgets.new_ledger()
    evaluator = MKPCodeEvaluator(timeout_seconds=settings.evaluator_timeout_seconds)
    collaborator = None
    if method == "roco":
        collaborator = RoCoCollaborator(
            provider=provider,
            evaluator=evaluator,
            distance_matrix=instance,
            ledger=ledger,
            rounds=settings.collaboration_rounds,
            elite_sampling_power=settings.elite_sampling_power,
            seed=_derive_seed(derived_seed, "roco-collaboration"),
            temperatures=settings.role_temperatures,
            minimize=True,
            role_prompts=_role_prompts(base_prompt),
            prompt_version=PROMPT_VERSION,
        )
    engine = EoHEngine(
        provider=provider,
        evaluator=evaluator,
        distance_matrix=instance,
        ledger=ledger,
        population_size=settings.population_size,
        generations=settings.generations,
        candidates_per_operator=settings.candidates_per_operator,
        minimize=True,
        collaborator=collaborator,
        memory_runtime=None,
    )
    best_score: float | None = None
    raw_profit: int | None = None
    normalized_score: float | None = None
    feasible = False
    failure: dict[str, str] | None = None
    try:
        engine_result = engine.run()
        best = engine_result.population.best
        best_score = best.score
        evaluation = best.metadata.get("evaluation", {})
        if isinstance(evaluation, dict):
            raw = evaluation.get("raw_profit")
            normalized = evaluation.get("normalized_score")
            raw_profit = raw if type(raw) is int else None
            normalized_score = (
                float(cast(int | float, normalized)) if type(normalized) in (int, float) else None
            )
            feasible = evaluation.get("feasible") is True
        status: Literal["completed", "budget_exhausted", "invalid", "failed"] = (
            "budget_exhausted"
            if engine_result.stopped_on_budget or ledger.budget_reached
            else "completed"
        )
    except Exception as exc:
        if ledger.budget_reached:
            status = "budget_exhausted"
            failure = {
                "phase": "budget",
                "type": type(exc).__name__,
                "safe_message": "offline MKP run stopped after a hard budget was reached",
            }
        else:
            status = "failed"
            failure = {
                "phase": "execution",
                "type": type(exc).__name__,
                "safe_message": (
                    "offline MKP run failed without exposing provider or candidate text"
                ),
            }
    actual = ledger.to_dict()
    budget = {
        "profile_id": settings.budgets.profile_id,
        "hard_limits": settings.budgets.to_dict(),
        "actual": {
            "llm_calls": ledger.llm_calls,
            "input_tokens": ledger.input_tokens,
            "output_tokens": ledger.output_tokens,
            "tokens": ledger.tokens,
            "generated_candidates": ledger.generated_candidates,
            "valid_evals": ledger.valid_evals,
            "cost": ledger.cost,
            "cost_currency": ledger.cost_currency,
            "wall_time": ledger.wall_time,
        },
        "reached_limits": actual["reached_limits"],
    }
    result_verified = (
        best_score is not None and raw_profit is not None and normalized_score is not None
    )
    return MKPExperimentResult(
        run_id=run_id,
        benchmark={
            "id": "mkp-01",
            "version": FSU_MKP_PROTOCOL_VERSION,
            "evidence_level": "E3",
            "source_id": FSU_MKP_SOURCE_ID,
            "release": FSU_MKP_SOURCE_RELEASE,
            "license_id": FSU_MKP_LICENSE_ID,
        },
        dataset={
            "inventory_checksum": dataset.checksum,
            "instance_id": instance.instance_id,
            "instance_checksum": instance.checksum,
            "split": instance.split,
            "split_policy_version": FSU_MKP_SPLIT_POLICY_VERSION,
        },
        randomness={
            "root_seed": settings.root_seed,
            "derived_run_seed": derived_seed,
            "provider_seed": provider_seed,
        },
        method={
            "id": method,
            "version": METHOD_VERSIONS[method],
            "implementation_git_sha": None,
        },
        provider={
            "name": "mock",
            "network_state": "unused",
            "model": "deterministic-mkp",
            "adapter_contract": MKP_MOCK_PROVIDER_VERSION,
            "tokenizer_counter": "mock-whitespace-v1",
            "pricing_version": "mock-zero-cost-v1",
        },
        prompt_visibility=prompt_visibility_contract(instance),
        budget=budget,
        evaluation={
            "source_objective_direction": "maximize",
            "selection_direction": "minimize",
            "evaluator_contract": EVALUATOR_CONTRACT_VERSION,
            "timeout_scope": "per-candidate",
            "metric_name": "negative_raw_profit",
            "reference_version_or_null": None,
            "best_score": best_score,
            "raw_profit": raw_profit,
            "normalized_score": normalized_score,
            "normalization_contract": "negative-profit-over-total-positive-profit-v1",
            "feasible": feasible,
        },
        status=status,
        failure=failure,
        replay={
            "dataset_verified": True,
            "split_verified": True,
            "result_verified": result_verified,
            "non_time_state_verified": True,
        },
    )


def read_mkp_results_jsonl(path: str | Path) -> tuple[MKPExperimentResult, ...]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MKPProtocolError(f"cannot read MKP results JSONL: {exc}") from exc
    results: list[MKPExperimentResult] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise MKPProtocolError(f"MKP results JSONL contains a blank line at {line_number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MKPProtocolError(
                f"MKP results JSONL corrupt at line {line_number}: {exc.msg}"
            ) from exc
        if not isinstance(value, dict):
            raise MKPProtocolError(f"MKP results JSONL line {line_number} must be an object")
        try:
            results.append(MKPExperimentResult.from_dict(value))
        except MKPProtocolError as exc:
            raise MKPProtocolError(
                f"MKP results schema failure at line {line_number}: {exc}"
            ) from exc
    if len({result.run_id for result in results}) != len(results):
        raise MKPProtocolError("MKP results JSONL repeats a run_id")
    return tuple(results)


def write_mkp_experiment_artifacts(run: MKPExperimentRun, output_dir: str | Path) -> Path:
    """Write manifest plus run records only; no statistical summary is produced."""

    root = Path(output_dir)
    try:
        root.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise MKPProtocolError(f"MKP output directory must be new: {exc}") from exc
    (root / "dataset_manifest.json").write_text(
        f"{json.dumps(run.dataset.to_dict(), allow_nan=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    with (root / "results.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for result in run.results:
            stream.write(_canonical_json(result.to_dict()))
            stream.write("\n")
    _write_results_csv(root / "results.csv", run.results)
    return root


def _write_results_csv(path: Path, results: Sequence[MKPExperimentResult]) -> None:
    fields = [
        "run_id",
        "replay_checksum",
        "instance_id",
        "instance_checksum",
        "split",
        "root_seed",
        "derived_run_seed",
        "method",
        "provider",
        "visibility",
        "budget_profile",
        "status",
        "llm_calls",
        "input_tokens",
        "output_tokens",
        "generated_candidates",
        "valid_evals",
        "cost",
        "cost_currency",
        "wall_time",
        "best_score",
        "raw_profit",
        "normalized_score",
        "feasible",
        "reached_limits",
        "failure_type",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for result in results:
            actual = result.budget["actual"]
            writer.writerow(
                {
                    "run_id": result.run_id,
                    "replay_checksum": result.replay_checksum,
                    "instance_id": result.dataset["instance_id"],
                    "instance_checksum": result.dataset["instance_checksum"],
                    "split": result.dataset["split"],
                    "root_seed": result.randomness["root_seed"],
                    "derived_run_seed": result.randomness["derived_run_seed"],
                    "method": result.method["id"],
                    "provider": result.provider["name"],
                    "visibility": result.prompt_visibility["condition"],
                    "budget_profile": result.budget["profile_id"],
                    "status": result.status,
                    "llm_calls": actual["llm_calls"],
                    "input_tokens": actual["input_tokens"],
                    "output_tokens": actual["output_tokens"],
                    "generated_candidates": actual["generated_candidates"],
                    "valid_evals": actual["valid_evals"],
                    "cost": actual["cost"],
                    "cost_currency": actual["cost_currency"],
                    "wall_time": actual["wall_time"],
                    "best_score": result.evaluation["best_score"],
                    "raw_profit": result.evaluation["raw_profit"],
                    "normalized_score": result.evaluation["normalized_score"],
                    "feasible": result.evaluation["feasible"],
                    "reached_limits": _canonical_json(result.budget["reached_limits"]),
                    "failure_type": None if result.failure is None else result.failure["type"],
                }
            )
