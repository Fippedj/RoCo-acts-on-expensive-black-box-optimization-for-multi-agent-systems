"""Deterministic TSP experiment inventory, dry-run execution, and aggregation.

This module is intentionally an offline protocol.  Its only executable provider
is the existing seeded :class:`MockLLMProvider`; it has no HTTP, credential, or
real-tokenizer path.  The fixed instance manifest, strict result schema, and
shared hard limits make later separately-authorized experiments auditable
without turning this dry-run into a paper-result claim.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

from roco_ebbo.core import BudgetLedger
from roco_ebbo.evaluation import TSPCodeEvaluator
from roco_ebbo.evolution import EoHEngine, RoCoCollaborator
from roco_ebbo.llm import ROLE_TEMPERATURES, MockLLMProvider, RoCoRole
from roco_ebbo.memory import GenerationMemoryStore, MemoryRuntime, MemoryRuntimeConfig

DATASET_MANIFEST_SCHEMA_VERSION = "roco-tsp-dataset-manifest-v1"
INSTANCE_SCHEMA_VERSION = "roco-tsp-instance-v1"
CONFIG_SCHEMA_VERSION = "roco-tsp-experiment-config-v1"
RESULT_SCHEMA_VERSION = "roco-tsp-experiment-result-v1"
SUMMARY_SCHEMA_VERSION = "roco-tsp-experiment-summary-v1"
GENERATOR_RULE = "python-random-mt19937-uniform-unit-square-v1"
PROMPT_VISIBILITY_SCHEMA_VERSION = "roco-prompt-visibility-v1"
_SUPPORTED_SIZES = frozenset({50, 100, 200})
_METHODS = frozenset({"eoh", "roco", "memory_roco"})
_VISIBILITIES = frozenset({"white_box", "black_box"})


class TSPProtocolError(ValueError):
    """Raised when a protocol artifact is malformed or cannot be replayed safely."""


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
        raise TSPProtocolError(f"protocol value is not canonical JSON: {exc}") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _derive_seed(seed: int, stream: str) -> int:
    payload = f"{seed}:{stream}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _require_exact_keys(value: dict[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise TSPProtocolError(f"{name} keys do not match schema; missing={missing}, extra={extra}")


def _require_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise TSPProtocolError(f"{name} must be an integer >= {minimum}")
    return value


def _require_finite_number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or float(value) < minimum:
        raise TSPProtocolError(f"{name} must be a finite number >= {minimum:g}")
    return float(value)


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TSPProtocolError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class TSPInstance:
    """One canonical Euclidean TSP instance with a content checksum."""

    instance_id: str
    nodes: int
    split: Literal["train", "test"]
    seed: int
    generator_rule: str
    coordinates: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if not self.instance_id:
            raise TSPProtocolError("instance_id must be non-empty")
        if self.nodes not in _SUPPORTED_SIZES:
            raise TSPProtocolError("TSP protocol supports only 50, 100, and 200 nodes")
        if self.split not in {"train", "test"}:
            raise TSPProtocolError("instance split must be train or test")
        if type(self.seed) is not int or self.seed < 0:
            raise TSPProtocolError("instance seed must be a non-negative integer")
        if self.generator_rule != GENERATOR_RULE:
            raise TSPProtocolError(
                f"unsupported coordinate generator rule: {self.generator_rule!r}"
            )
        if len(self.coordinates) != self.nodes:
            raise TSPProtocolError("coordinate count must equal TSP node count")
        for coordinate in self.coordinates:
            if len(coordinate) != 2 or any(
                not math.isfinite(component) or component < 0.0 or component >= 1.0
                for component in coordinate
            ):
                raise TSPProtocolError("coordinates must be finite values in [0, 1)")

    @property
    def checksum(self) -> str:
        return _sha256(self._payload())

    @property
    def geometry_checksum(self) -> str:
        """Fingerprint coordinates independently of split/id bookkeeping.

        A train/test record with different metadata but identical geometry is
        still leakage, so split validation uses this companion checksum rather
        than assuming record-level checksums alone are sufficient.
        """

        return _sha256(
            {
                "nodes": self.nodes,
                "generator_rule": self.generator_rule,
                "coordinates": [[x, y] for x, y in self.coordinates],
            }
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": INSTANCE_SCHEMA_VERSION,
            "instance_id": self.instance_id,
            "nodes": self.nodes,
            "split": self.split,
            "seed": self.seed,
            "generator_rule": self.generator_rule,
            "coordinates": [[x, y] for x, y in self.coordinates],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "checksum": self.checksum}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TSPInstance:
        _require_exact_keys(
            value,
            {
                "schema_version",
                "instance_id",
                "nodes",
                "split",
                "seed",
                "generator_rule",
                "coordinates",
                "checksum",
            },
            "TSP instance",
        )
        if value["schema_version"] != INSTANCE_SCHEMA_VERSION:
            raise TSPProtocolError("unsupported TSP instance schema version")
        if not isinstance(value["instance_id"], str) or not isinstance(value["split"], str):
            raise TSPProtocolError("TSP instance id and split must be strings")
        if not isinstance(value["generator_rule"], str) or not isinstance(value["checksum"], str):
            raise TSPProtocolError("TSP instance generator_rule and checksum must be strings")
        coordinates_value = value["coordinates"]
        if not isinstance(coordinates_value, list):
            raise TSPProtocolError("TSP instance coordinates must be a list")
        coordinates: list[tuple[float, float]] = []
        for index, coordinate in enumerate(coordinates_value):
            if not isinstance(coordinate, list) or len(coordinate) != 2:
                raise TSPProtocolError(f"coordinate {index} must be a length-two list")
            coordinates.append(
                (
                    _require_finite_number(coordinate[0], f"coordinate {index} x"),
                    _require_finite_number(coordinate[1], f"coordinate {index} y"),
                )
            )
        instance = cls(
            instance_id=value["instance_id"],
            nodes=_require_int(value["nodes"], "instance nodes", minimum=2),
            split=value["split"],  # type: ignore[arg-type]
            seed=_require_int(value["seed"], "instance seed"),
            generator_rule=value["generator_rule"],
            coordinates=tuple(coordinates),
        )
        if value["checksum"] != instance.checksum:
            raise TSPProtocolError(f"instance checksum mismatch for {instance.instance_id}")
        return instance

    def distance_matrix(self) -> list[list[float]]:
        """Return the deterministic symmetric matrix implied by the coordinates."""

        matrix = [[0.0 for _ in range(self.nodes)] for _ in range(self.nodes)]
        for first, (first_x, first_y) in enumerate(self.coordinates):
            for second in range(first + 1, self.nodes):
                second_x, second_y = self.coordinates[second]
                distance = math.hypot(first_x - second_x, first_y - second_y)
                matrix[first][second] = distance
                matrix[second][first] = distance
        return matrix


@dataclass(frozen=True, slots=True)
class TSPDatasetSpec:
    """The engineering inventory used by a dry-run, not a paper data claim."""

    master_seed: int
    sizes: tuple[int, ...]
    train_instances: int
    test_instances: int
    generator_rule: str = GENERATOR_RULE

    def __post_init__(self) -> None:
        if type(self.master_seed) is not int or self.master_seed < 0:
            raise TSPProtocolError("dataset master_seed must be a non-negative integer")
        if not self.sizes or any(size not in _SUPPORTED_SIZES for size in self.sizes):
            raise TSPProtocolError("dataset sizes must be a non-empty subset of 50, 100, 200")
        if len(set(self.sizes)) != len(self.sizes):
            raise TSPProtocolError("dataset sizes must not repeat")
        if self.train_instances < 1 or self.test_instances < 1:
            raise TSPProtocolError(
                "train and test inventories must both contain at least one instance"
            )
        if self.generator_rule != GENERATOR_RULE:
            raise TSPProtocolError("only the versioned unit-square generator is supported")


@dataclass(frozen=True, slots=True)
class TSPDatasetManifest:
    """Canonical inventory whose per-instance checksums enforce split separation."""

    master_seed: int
    generator_rule: str
    instances: tuple[TSPInstance, ...]

    def __post_init__(self) -> None:
        if type(self.master_seed) is not int or self.master_seed < 0:
            raise TSPProtocolError("dataset manifest master_seed must be a non-negative integer")
        if self.generator_rule != GENERATOR_RULE or not self.instances:
            raise TSPProtocolError("dataset manifest has an unsupported generator or no instances")
        ids = [instance.instance_id for instance in self.instances]
        if len(ids) != len(set(ids)):
            raise TSPProtocolError("dataset manifest repeats an instance_id")
        checksums = [instance.checksum for instance in self.instances]
        if len(checksums) != len(set(checksums)):
            raise TSPProtocolError("dataset manifest repeats an instance checksum")
        geometry_checksums = [instance.geometry_checksum for instance in self.instances]
        if len(geometry_checksums) != len(set(geometry_checksums)):
            raise TSPProtocolError("dataset split overlap or duplicate instance geometry detected")
        train = {item.geometry_checksum for item in self.instances if item.split == "train"}
        test = {item.geometry_checksum for item in self.instances if item.split == "test"}
        if train & test:
            raise TSPProtocolError("dataset train/test split overlap detected")

    @property
    def checksum(self) -> str:
        return _sha256(self._payload())

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": DATASET_MANIFEST_SCHEMA_VERSION,
            "master_seed": self.master_seed,
            "generator_rule": self.generator_rule,
            "instances": [instance.to_dict() for instance in self.instances],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "manifest_checksum": self.checksum}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TSPDatasetManifest:
        _require_exact_keys(
            value,
            {
                "schema_version",
                "master_seed",
                "generator_rule",
                "instances",
                "manifest_checksum",
            },
            "TSP dataset manifest",
        )
        if value["schema_version"] != DATASET_MANIFEST_SCHEMA_VERSION:
            raise TSPProtocolError("unsupported dataset manifest schema version")
        if not isinstance(value["generator_rule"], str) or not isinstance(
            value["manifest_checksum"], str
        ):
            raise TSPProtocolError("dataset manifest strings are invalid")
        raw_instances = value["instances"]
        if not isinstance(raw_instances, list) or not all(
            isinstance(item, dict) for item in raw_instances
        ):
            raise TSPProtocolError("dataset manifest instances must be object records")
        manifest = cls(
            master_seed=_require_int(value["master_seed"], "dataset master_seed"),
            generator_rule=value["generator_rule"],
            instances=tuple(TSPInstance.from_dict(item) for item in raw_instances),
        )
        if value["manifest_checksum"] != manifest.checksum:
            raise TSPProtocolError("dataset manifest checksum mismatch")
        return manifest


def create_dataset_manifest(spec: TSPDatasetSpec) -> TSPDatasetManifest:
    """Generate the full split-separated inventory from only the declared seed/rule."""

    instances: list[TSPInstance] = []
    for split, count in (("train", spec.train_instances), ("test", spec.test_instances)):
        for nodes in sorted(spec.sizes):
            for ordinal in range(count):
                seed = _derive_seed(
                    spec.master_seed,
                    f"{DATASET_MANIFEST_SCHEMA_VERSION}:{split}:tsp-{nodes}:instance-{ordinal}",
                )
                rng = random.Random(seed)
                coordinates = tuple((rng.random(), rng.random()) for _ in range(nodes))
                instances.append(
                    TSPInstance(
                        instance_id=f"{split}-tsp-{nodes}-{ordinal:03d}",
                        nodes=nodes,
                        split=split,  # type: ignore[arg-type]
                        seed=seed,
                        generator_rule=spec.generator_rule,
                        coordinates=coordinates,
                    )
                )
    return TSPDatasetManifest(
        master_seed=spec.master_seed,
        generator_rule=spec.generator_rule,
        instances=tuple(instances),
    )


def load_dataset_manifest(path: str | Path) -> TSPDatasetManifest:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TSPProtocolError(f"cannot read dataset manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise TSPProtocolError("dataset manifest root must be an object")
    return TSPDatasetManifest.from_dict(value)


@dataclass(frozen=True, slots=True)
class ExperimentBudgets:
    """All six hard limits, shared unchanged by every compared method."""

    max_llm_calls: int
    max_tokens: int
    max_generated_candidates: int
    max_valid_evals: int
    max_cost: float
    max_wall_time: float
    cost_currency: str = "USD"

    def __post_init__(self) -> None:
        for name in (
            "max_llm_calls",
            "max_tokens",
            "max_generated_candidates",
            "max_valid_evals",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise TSPProtocolError(f"{name} must be an integer >= 1")
        for name in ("max_cost", "max_wall_time"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise TSPProtocolError(f"{name} must be finite and greater than zero")
        if not self.cost_currency:
            raise TSPProtocolError("cost_currency must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
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
class TSPExperimentSettings:
    """Parsed TSP-only dry-run configuration with no real-provider option."""

    dataset: TSPDatasetSpec
    seeds: tuple[int, ...]
    methods: tuple[str, ...]
    prompt_visibilities: tuple[str, ...]
    budgets: ExperimentBudgets
    population_size: int
    generations: int
    candidates_per_operator: int
    collaboration_rounds: int
    elite_sampling_power: float
    role_temperatures: dict[RoCoRole, float]
    evaluator_timeout_seconds: float
    memory_enabled: bool
    memory_recent_events: int
    memory_success_slots: int
    memory_failure_slots: int
    memory_elite_count: int
    memory_max_context_characters: int
    config_snapshot: dict[str, Any]

    def __post_init__(self) -> None:
        if (
            len(self.seeds) != 3
            or len(set(self.seeds)) != 3
            or any(type(seed) is not int or seed < 0 for seed in self.seeds)
        ):
            raise TSPProtocolError("dry-run requires exactly three distinct non-negative seeds")
        if not self.methods or any(method not in _METHODS for method in self.methods):
            raise TSPProtocolError("methods must be a non-empty subset of eoh, roco, memory_roco")
        if len(set(self.methods)) != len(self.methods):
            raise TSPProtocolError("methods must not repeat")
        if "memory_roco" in self.methods and not self.memory_enabled:
            raise TSPProtocolError("memory_roco requires memory.enabled=true")
        if not self.prompt_visibilities or any(
            visibility not in _VISIBILITIES for visibility in self.prompt_visibilities
        ):
            raise TSPProtocolError("prompt visibility must use white_box and/or black_box")
        if len(set(self.prompt_visibilities)) != len(self.prompt_visibilities):
            raise TSPProtocolError("prompt visibility conditions must not repeat")
        if self.population_size < 2 or self.generations < 1 or self.candidates_per_operator < 1:
            raise TSPProtocolError("invalid EoH population, generation, or operator multiplicity")
        if self.collaboration_rounds < 1:
            raise TSPProtocolError("collaboration_rounds must be at least one")
        if not math.isfinite(self.elite_sampling_power) or self.elite_sampling_power <= 0:
            raise TSPProtocolError("elite_sampling_power must be finite and greater than zero")
        if any(
            not math.isfinite(temperature) or temperature < 0
            for temperature in self.role_temperatures.values()
        ):
            raise TSPProtocolError("role temperatures must be finite and non-negative")
        if not math.isfinite(self.evaluator_timeout_seconds) or self.evaluator_timeout_seconds <= 0:
            raise TSPProtocolError("evaluator timeout must be finite and greater than zero")
        if not self.memory_enabled and any(
            value != default
            for value, default in (
                (self.memory_recent_events, 5),
                (self.memory_success_slots, 3),
                (self.memory_failure_slots, 2),
                (self.memory_elite_count, 1),
                (self.memory_max_context_characters, 16_000),
            )
        ):
            # This catches misleading inactive settings without changing legacy memory defaults.
            raise TSPProtocolError("memory settings require memory.enabled=true")
        if self.memory_enabled:
            MemoryRuntimeConfig(
                recent_events=self.memory_recent_events,
                success_slots=self.memory_success_slots,
                failure_slots=self.memory_failure_slots,
                elite_count=self.memory_elite_count,
                max_context_characters=self.memory_max_context_characters,
            )


def load_tsp_experiment_settings(path: str | Path) -> TSPExperimentSettings:
    """Load the versioned YAML configuration and reject non-Mock execution paths."""

    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TSPProtocolError(f"cannot read experiment config: {exc}") from exc
    if not isinstance(raw, dict):
        raise TSPProtocolError("experiment config root must be a mapping")
    try:
        _require_exact_keys(
            raw,
            {"protocol", "llm", "dataset", "experiment", "evolution", "benchmark", "memory"},
            "experiment config",
        )
        protocol = _mapping(raw, "protocol")
        _require_exact_keys(protocol, {"schema_version", "dry_run"}, "protocol")
        if protocol["schema_version"] != CONFIG_SCHEMA_VERSION or protocol["dry_run"] is not True:
            raise TSPProtocolError("only the versioned offline dry-run protocol is supported")
        llm = _mapping(raw, "llm")
        _require_exact_keys(llm, {"provider", "temperatures"}, "llm")
        if llm["provider"] != "mock":
            raise TSPProtocolError("TSP dry-run supports only provider=mock; network is unused")
        raw_temperatures = llm["temperatures"]
        if not isinstance(raw_temperatures, dict):
            raise TSPProtocolError("llm.temperatures must be a mapping")
        role_temperatures = {
            role: _require_finite_number(
                raw_temperatures.get(role.value, default), f"temperature for {role.value}"
            )
            for role, default in ROLE_TEMPERATURES.items()
        }
        dataset_raw = _mapping(raw, "dataset")
        _require_exact_keys(
            dataset_raw,
            {"master_seed", "sizes", "splits", "generator_rule"},
            "dataset",
        )
        splits = _mapping(dataset_raw, "splits")
        _require_exact_keys(splits, {"train", "test"}, "dataset.splits")
        raw_sizes = dataset_raw["sizes"]
        if not isinstance(raw_sizes, list):
            raise TSPProtocolError("dataset.sizes must be a list")
        dataset = TSPDatasetSpec(
            master_seed=_require_int(dataset_raw["master_seed"], "dataset.master_seed"),
            sizes=tuple(_require_int(size, "dataset size", minimum=2) for size in raw_sizes),
            train_instances=_require_int(splits["train"], "dataset.splits.train", minimum=1),
            test_instances=_require_int(splits["test"], "dataset.splits.test", minimum=1),
            generator_rule=str(dataset_raw["generator_rule"]),
        )
        experiment = _mapping(raw, "experiment")
        _require_exact_keys(
            experiment, {"seeds", "methods", "prompt_visibility", "budgets"}, "experiment"
        )
        raw_seeds = experiment["seeds"]
        raw_methods = experiment["methods"]
        raw_visibilities = experiment["prompt_visibility"]
        if (
            not isinstance(raw_seeds, list)
            or not isinstance(raw_methods, list)
            or not isinstance(raw_visibilities, list)
        ):
            raise TSPProtocolError("experiment seeds, methods, and prompt_visibility must be lists")
        budgets_raw = _mapping(experiment, "budgets")
        _require_exact_keys(
            budgets_raw,
            {
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
        budgets = ExperimentBudgets(
            max_llm_calls=_require_int(budgets_raw["max_llm_calls"], "max_llm_calls", minimum=1),
            max_tokens=_require_int(budgets_raw["max_tokens"], "max_tokens", minimum=1),
            max_generated_candidates=_require_int(
                budgets_raw["max_generated_candidates"], "max_generated_candidates", minimum=1
            ),
            max_valid_evals=_require_int(
                budgets_raw["max_valid_evals"], "max_valid_evals", minimum=1
            ),
            max_cost=_require_finite_number(budgets_raw["max_cost"], "max_cost", minimum=0.0),
            max_wall_time=_require_finite_number(
                budgets_raw["max_wall_time"], "max_wall_time", minimum=0.0
            ),
            cost_currency=str(budgets_raw["cost_currency"]),
        )
        evolution = _mapping(raw, "evolution")
        _require_exact_keys(
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
        _require_exact_keys(benchmark, {"name", "evaluator_timeout_seconds"}, "benchmark")
        if benchmark["name"] != "tsp":
            raise TSPProtocolError("experiment protocol is TSP-only")
        memory = _mapping(raw, "memory")
        _require_exact_keys(
            memory,
            {
                "enabled",
                "recent_events",
                "success_slots",
                "failure_slots",
                "elite_count",
                "max_context_characters",
            },
            "memory",
        )
        if type(memory["enabled"]) is not bool:
            raise TSPProtocolError("memory.enabled must be a boolean")
        settings = TSPExperimentSettings(
            dataset=dataset,
            seeds=tuple(_require_int(seed, "experiment seed") for seed in raw_seeds),
            methods=tuple(str(method) for method in raw_methods),
            prompt_visibilities=tuple(str(item) for item in raw_visibilities),
            budgets=budgets,
            population_size=_require_int(
                evolution["population_size"], "population_size", minimum=2
            ),
            generations=_require_int(evolution["generations"], "generations", minimum=1),
            candidates_per_operator=_require_int(
                evolution["candidates_per_operator"], "candidates_per_operator", minimum=1
            ),
            collaboration_rounds=_require_int(
                evolution["collaboration_rounds"], "collaboration_rounds", minimum=1
            ),
            elite_sampling_power=_require_finite_number(
                evolution["elite_sampling_power"], "elite_sampling_power", minimum=0.0
            ),
            role_temperatures=role_temperatures,
            evaluator_timeout_seconds=_require_finite_number(
                benchmark["evaluator_timeout_seconds"], "evaluator_timeout_seconds", minimum=0.0
            ),
            memory_enabled=memory["enabled"],
            memory_recent_events=_require_int(memory["recent_events"], "memory.recent_events"),
            memory_success_slots=_require_int(memory["success_slots"], "memory.success_slots"),
            memory_failure_slots=_require_int(memory["failure_slots"], "memory.failure_slots"),
            memory_elite_count=_require_int(memory["elite_count"], "memory.elite_count", minimum=1),
            memory_max_context_characters=_require_int(
                memory["max_context_characters"], "memory.max_context_characters", minimum=1
            ),
            config_snapshot=raw,
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, TSPProtocolError):
            raise
        raise TSPProtocolError(f"invalid TSP experiment config: {exc}") from exc
    return settings


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise TSPProtocolError(f"{key} must be a mapping")
    return value


def _visibility_contract(condition: str) -> dict[str, str | bool]:
    if condition == "white_box":
        semantics = "prompt may expose declared TSP mechanics; not an expensive-oracle condition"
    elif condition == "black_box":
        semantics = "prompt must not expose coordinates, distance matrix, or evaluator internals"
    else:
        raise TSPProtocolError(f"unknown prompt visibility condition: {condition}")
    return {
        "schema_version": PROMPT_VISIBILITY_SCHEMA_VERSION,
        "condition": condition,
        "semantics": semantics,
        "mock_metadata_only": True,
    }


@dataclass(frozen=True, slots=True)
class TSPExperimentResult:
    """One result row with raw accounting and a non-time replay checksum."""

    run_id: str
    seed: int
    split: str
    instance: dict[str, Any]
    method: str
    provider: dict[str, Any]
    prompt_visibility: dict[str, Any]
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cost: float
    cost_currency: str
    valid_evals: int
    generated_candidates: int
    wall_time: float
    best_score: float | None
    status: Literal["completed", "budget_exhausted", "failed"]
    failure: dict[str, str] | None
    budget: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.run_id or type(self.seed) is not int or self.seed < 0:
            raise TSPProtocolError("result run_id and seed are invalid")
        if self.split not in {"train", "test"} or self.method not in _METHODS:
            raise TSPProtocolError("result split or method is invalid")
        _validate_result_instance(self.instance, self.split)
        _require_exact_keys(self.provider, {"name", "model", "network"}, "result provider")
        if self.provider.get("name") != "mock" or self.provider.get("network") != "unused":
            raise TSPProtocolError("only offline mock provider results are valid in this protocol")
        contract = _visibility_contract(str(self.prompt_visibility.get("condition", "")))
        if self.prompt_visibility != contract:
            raise TSPProtocolError("result prompt visibility contract is invalid")
        for name in (
            "llm_calls",
            "input_tokens",
            "output_tokens",
            "valid_evals",
            "generated_candidates",
        ):
            _require_int(getattr(self, name), f"result {name}")
        _require_finite_number(self.cost, "result cost")
        _require_finite_number(self.wall_time, "result wall_time")
        if not self.cost_currency:
            raise TSPProtocolError("result cost_currency must be non-empty")
        if self.best_score is not None:
            _require_finite_number(self.best_score, "result best_score")
        if self.status not in {"completed", "budget_exhausted", "failed"}:
            raise TSPProtocolError("result status is invalid")
        if (self.status == "failed") != (self.failure is not None):
            raise TSPProtocolError("only failed results may contain a failure object")
        if self.failure is not None and (
            set(self.failure) != {"type", "message"}
            or not all(isinstance(item, str) and item for item in self.failure.values())
        ):
            raise TSPProtocolError("result failure must contain non-empty type and message")
        _validate_budget_snapshot(self.budget)
        if self.cost_currency != self.budget["hard_limits"]["cost_currency"]:
            raise TSPProtocolError("result cost_currency must match its hard-budget currency")

    @property
    def replay_checksum(self) -> str:
        payload = self._payload()
        payload["wall_time"] = None
        return _sha256(payload)

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "seed": self.seed,
            "split": self.split,
            "instance": self.instance,
            "method": self.method,
            "provider": self.provider,
            "prompt_visibility": self.prompt_visibility,
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost": self.cost,
            "cost_currency": self.cost_currency,
            "valid_evals": self.valid_evals,
            "generated_candidates": self.generated_candidates,
            "wall_time": self.wall_time,
            "best_score": self.best_score,
            "status": self.status,
            "failure": self.failure,
            "budget": self.budget,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "replay_checksum": self.replay_checksum}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TSPExperimentResult:
        fields = {
            "schema_version",
            "run_id",
            "seed",
            "split",
            "instance",
            "method",
            "provider",
            "prompt_visibility",
            "llm_calls",
            "input_tokens",
            "output_tokens",
            "cost",
            "cost_currency",
            "valid_evals",
            "generated_candidates",
            "wall_time",
            "best_score",
            "status",
            "failure",
            "budget",
            "replay_checksum",
        }
        _require_exact_keys(value, fields, "experiment result")
        if value["schema_version"] != RESULT_SCHEMA_VERSION:
            raise TSPProtocolError("unsupported experiment result schema version")
        mappings = ("instance", "provider", "prompt_visibility", "budget")
        if any(not isinstance(value[name], dict) for name in mappings):
            raise TSPProtocolError("experiment result nested records must be objects")
        if value["failure"] is not None and not isinstance(value["failure"], dict):
            raise TSPProtocolError("experiment result failure must be an object or null")
        result = cls(
            run_id=_require_string(value["run_id"], "result run_id"),
            seed=_require_int(value["seed"], "result seed"),
            split=_require_string(value["split"], "result split"),
            instance=value["instance"],
            method=_require_string(value["method"], "result method"),
            provider=value["provider"],
            prompt_visibility=value["prompt_visibility"],
            llm_calls=_require_int(value["llm_calls"], "result llm_calls"),
            input_tokens=_require_int(value["input_tokens"], "result input_tokens"),
            output_tokens=_require_int(value["output_tokens"], "result output_tokens"),
            cost=_require_finite_number(value["cost"], "result cost"),
            cost_currency=_require_string(value["cost_currency"], "result cost_currency"),
            valid_evals=_require_int(value["valid_evals"], "result valid_evals"),
            generated_candidates=_require_int(
                value["generated_candidates"], "result generated_candidates"
            ),
            wall_time=_require_finite_number(value["wall_time"], "result wall_time"),
            best_score=(
                None
                if value["best_score"] is None
                else _require_finite_number(value["best_score"], "result best_score")
            ),
            status=_require_string(value["status"], "result status"),  # type: ignore[arg-type]
            failure=value["failure"],
            budget=value["budget"],
        )
        if value["replay_checksum"] != result.replay_checksum:
            raise TSPProtocolError(f"result replay checksum mismatch for {result.run_id}")
        return result


def _validate_result_instance(instance: dict[str, Any], split: str) -> None:
    _require_exact_keys(
        instance,
        {"instance_id", "nodes", "split", "seed", "generator_rule", "checksum"},
        "result instance",
    )
    if instance["split"] != split or instance["nodes"] not in _SUPPORTED_SIZES:
        raise TSPProtocolError("result instance split or node count is invalid")
    _require_int(instance["seed"], "result instance seed")
    if instance["generator_rule"] != GENERATOR_RULE or not all(
        isinstance(instance[name], str) and instance[name]
        for name in ("instance_id", "generator_rule", "checksum")
    ):
        raise TSPProtocolError("result instance metadata is invalid")


def _validate_budget_snapshot(value: dict[str, Any]) -> None:
    _require_exact_keys(value, {"hard_limits", "reached_limits", "budget_reached"}, "result budget")
    hard_limits = value["hard_limits"]
    if not isinstance(hard_limits, dict):
        raise TSPProtocolError("result hard_limits must be an object")
    _require_exact_keys(
        hard_limits,
        {
            "max_llm_calls",
            "max_tokens",
            "max_generated_candidates",
            "max_valid_evals",
            "max_cost",
            "max_wall_time",
            "cost_currency",
        },
        "result hard_limits",
    )
    ExperimentBudgets(
        max_llm_calls=_require_int(hard_limits["max_llm_calls"], "result max_llm_calls", minimum=1),
        max_tokens=_require_int(hard_limits["max_tokens"], "result max_tokens", minimum=1),
        max_generated_candidates=_require_int(
            hard_limits["max_generated_candidates"], "result max_generated_candidates", minimum=1
        ),
        max_valid_evals=_require_int(
            hard_limits["max_valid_evals"], "result max_valid_evals", minimum=1
        ),
        max_cost=_require_finite_number(hard_limits["max_cost"], "result max_cost"),
        max_wall_time=_require_finite_number(hard_limits["max_wall_time"], "result max_wall_time"),
        cost_currency=_require_string(hard_limits["cost_currency"], "result cost_currency"),
    )
    if type(value["budget_reached"]) is not bool or not isinstance(value["reached_limits"], list):
        raise TSPProtocolError("result budget status is invalid")
    if not all(isinstance(item, str) for item in value["reached_limits"]):
        raise TSPProtocolError("result reached limits must be strings")


def _instance_reference(instance: TSPInstance) -> dict[str, Any]:
    return {
        "instance_id": instance.instance_id,
        "nodes": instance.nodes,
        "split": instance.split,
        "seed": instance.seed,
        "generator_rule": instance.generator_rule,
        "checksum": instance.checksum,
    }


def _run_id(instance: TSPInstance, method: str, visibility: str, seed: int) -> str:
    digest = _sha256(
        {
            "instance_checksum": instance.checksum,
            "method": method,
            "prompt_visibility": visibility,
            "seed": seed,
        }
    )[:16]
    return f"tsp-{instance.split}-{instance.nodes}-{method}-{visibility}-s{seed}-{digest}"


@dataclass(frozen=True, slots=True)
class TSPExperimentRun:
    dataset: TSPDatasetManifest
    results: tuple[TSPExperimentResult, ...]
    summaries: tuple[TSPExperimentSummary, ...]


def execute_tsp_experiment(
    settings: TSPExperimentSettings,
    *,
    dataset: TSPDatasetManifest | None = None,
    memory_artifacts_root: str | Path | None = None,
) -> TSPExperimentRun:
    """Execute every configured offline condition in a deterministic ordering."""

    resolved_dataset = dataset or create_dataset_manifest(settings.dataset)
    _validate_dataset_matches_settings(resolved_dataset, settings.dataset)
    if "memory_roco" in settings.methods and memory_artifacts_root is None:
        raise TSPProtocolError("memory_roco requires an explicit memory artifact directory")
    results: list[TSPExperimentResult] = []
    for instance in resolved_dataset.instances:
        for visibility in settings.prompt_visibilities:
            for seed in settings.seeds:
                for method in settings.methods:
                    results.append(
                        _execute_one(
                            settings,
                            instance=instance,
                            method=method,
                            visibility=visibility,
                            seed=seed,
                            memory_artifacts_root=memory_artifacts_root,
                        )
                    )
    summaries = aggregate_results(results)
    return TSPExperimentRun(
        dataset=resolved_dataset,
        results=tuple(results),
        summaries=summaries,
    )


def _validate_dataset_matches_settings(
    dataset: TSPDatasetManifest,
    spec: TSPDatasetSpec,
) -> None:
    expected: dict[tuple[str, int], int] = {
        ("train", nodes): spec.train_instances for nodes in spec.sizes
    } | {("test", nodes): spec.test_instances for nodes in spec.sizes}
    actual: dict[tuple[str, int], int] = {}
    for instance in dataset.instances:
        key = (instance.split, instance.nodes)
        actual[key] = actual.get(key, 0) + 1
    if actual != expected:
        raise TSPProtocolError(
            "loaded dataset manifest does not match configured sizes/split inventory"
        )


def _execute_one(
    settings: TSPExperimentSettings,
    *,
    instance: TSPInstance,
    method: str,
    visibility: str,
    seed: int,
    memory_artifacts_root: str | Path | None,
) -> TSPExperimentResult:
    run_id = _run_id(instance, method, visibility, seed)
    ledger = settings.budgets.new_ledger()
    provider = MockLLMProvider(seed=_derive_seed(seed, "mock-provider"))
    evaluator = TSPCodeEvaluator(timeout_seconds=settings.evaluator_timeout_seconds)
    collaborator: RoCoCollaborator | None = None
    if method in {"roco", "memory_roco"}:
        collaborator = RoCoCollaborator(
            provider=provider,
            evaluator=evaluator,
            distance_matrix=instance.distance_matrix(),
            ledger=ledger,
            rounds=settings.collaboration_rounds,
            elite_sampling_power=settings.elite_sampling_power,
            seed=_derive_seed(seed, "roco-collaboration"),
            temperatures=settings.role_temperatures,
            minimize=True,
        )
    memory_runtime = None
    if method == "memory_roco":
        assert collaborator is not None
        assert memory_artifacts_root is not None
        memory_runtime = MemoryRuntime(
            provider=provider,
            evaluator=evaluator,
            distance_matrix=instance.distance_matrix(),
            ledger=ledger,
            store=GenerationMemoryStore(Path(memory_artifacts_root) / run_id / "memory"),
            collaborator=collaborator,
            run_id=run_id,
            benchmark=f"tsp-{instance.nodes}",
            objective="minimize",
            config_hash=_sha256(settings.config_snapshot),
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
        distance_matrix=instance.distance_matrix(),
        ledger=ledger,
        population_size=settings.population_size,
        generations=settings.generations,
        candidates_per_operator=settings.candidates_per_operator,
        minimize=True,
        collaborator=collaborator,
        memory_runtime=memory_runtime,
    )
    try:
        engine_result = engine.run()
        status: Literal["completed", "budget_exhausted", "failed"] = (
            "budget_exhausted"
            if engine_result.stopped_on_budget or ledger.budget_reached
            else "completed"
        )
        failure = None
        best_score = engine_result.population.best.score
    # Mock protocol persists a declared failure rather than a partial result.
    except Exception as exc:
        status = "failed"
        failure = {"type": type(exc).__name__, "message": str(exc)[:500] or "unspecified failure"}
        best_score = None
    budget_snapshot = ledger.to_dict()
    budget = {
        "hard_limits": settings.budgets.to_dict(),
        "reached_limits": budget_snapshot["reached_limits"],
        "budget_reached": budget_snapshot["budget_reached"],
    }
    return TSPExperimentResult(
        run_id=run_id,
        seed=seed,
        split=instance.split,
        instance=_instance_reference(instance),
        method=method,
        provider={"name": "mock", "model": "deterministic", "network": "unused"},
        prompt_visibility=_visibility_contract(visibility),
        llm_calls=ledger.llm_calls,
        input_tokens=ledger.input_tokens,
        output_tokens=ledger.output_tokens,
        cost=ledger.cost,
        cost_currency=ledger.cost_currency,
        valid_evals=ledger.valid_evals,
        generated_candidates=ledger.generated_candidates,
        wall_time=ledger.wall_time,
        best_score=best_score,
        status=status,
        failure=failure,
        budget=budget,
    )


@dataclass(frozen=True, slots=True)
class TSPExperimentSummary:
    """Descriptive summary; it intentionally contains no significance test."""

    method: str
    seed: int
    split: str
    prompt_visibility: str
    nodes: int
    runs: int
    completed_runs: int
    budget_exhausted_runs: int
    failed_runs: int
    scored_runs: int
    mean_best_score: float | None
    min_best_score: float | None
    total_llm_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost: float
    total_valid_evals: int
    total_generated_candidates: int
    total_wall_time: float
    input_replay_checksums: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "method": self.method,
            "seed": self.seed,
            "split": self.split,
            "prompt_visibility": self.prompt_visibility,
            "nodes": self.nodes,
            "runs": self.runs,
            "completed_runs": self.completed_runs,
            "budget_exhausted_runs": self.budget_exhausted_runs,
            "failed_runs": self.failed_runs,
            "scored_runs": self.scored_runs,
            "mean_best_score": self.mean_best_score,
            "min_best_score": self.min_best_score,
            "total_llm_calls": self.total_llm_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost": self.total_cost,
            "total_valid_evals": self.total_valid_evals,
            "total_generated_candidates": self.total_generated_candidates,
            "total_wall_time": self.total_wall_time,
            "input_replay_checksums": list(self.input_replay_checksums),
            "analysis_note": (
                "descriptive aggregation only; no statistical significance is computed"
            ),
        }


def aggregate_results(results: Iterable[TSPExperimentResult]) -> tuple[TSPExperimentSummary, ...]:
    """Aggregate valid result objects by method, seed, split, visibility, and size."""

    groups: dict[tuple[str, int, str, str, int], list[TSPExperimentResult]] = {}
    for result in results:
        key = (
            result.method,
            result.seed,
            result.split,
            str(result.prompt_visibility["condition"]),
            int(result.instance["nodes"]),
        )
        groups.setdefault(key, []).append(result)
    summaries: list[TSPExperimentSummary] = []
    for key in sorted(groups):
        method, seed, split, visibility, nodes = key
        rows = sorted(groups[key], key=lambda row: row.run_id)
        scores = [float(row.best_score) for row in rows if row.best_score is not None]
        summaries.append(
            TSPExperimentSummary(
                method=method,
                seed=seed,
                split=split,
                prompt_visibility=visibility,
                nodes=nodes,
                runs=len(rows),
                completed_runs=sum(row.status == "completed" for row in rows),
                budget_exhausted_runs=sum(row.status == "budget_exhausted" for row in rows),
                failed_runs=sum(row.status == "failed" for row in rows),
                scored_runs=len(scores),
                mean_best_score=(None if not scores else sum(scores) / len(scores)),
                min_best_score=(None if not scores else min(scores)),
                total_llm_calls=sum(row.llm_calls for row in rows),
                total_input_tokens=sum(row.input_tokens for row in rows),
                total_output_tokens=sum(row.output_tokens for row in rows),
                total_cost=sum(row.cost for row in rows),
                total_valid_evals=sum(row.valid_evals for row in rows),
                total_generated_candidates=sum(row.generated_candidates for row in rows),
                total_wall_time=sum(row.wall_time for row in rows),
                input_replay_checksums=tuple(row.replay_checksum for row in rows),
            )
        )
    return tuple(summaries)


def read_results_jsonl(path: str | Path) -> tuple[TSPExperimentResult, ...]:
    """Read strict JSONL and identify the corrupt line instead of silently skipping it."""

    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise TSPProtocolError(f"cannot read results JSONL: {exc}") from exc
    results: list[TSPExperimentResult] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise TSPProtocolError(f"results JSONL contains a blank line at {line_number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TSPProtocolError(
                f"results JSONL is corrupt at line {line_number}: {exc.msg}"
            ) from exc
        if not isinstance(value, dict):
            raise TSPProtocolError(f"results JSONL line {line_number} must be an object")
        try:
            results.append(TSPExperimentResult.from_dict(value))
        except TSPProtocolError as exc:
            raise TSPProtocolError(
                f"results JSONL schema failure at line {line_number}: {exc}"
            ) from exc
    if len({result.run_id for result in results}) != len(results):
        raise TSPProtocolError("results JSONL contains duplicate run_id values")
    return tuple(results)


def write_experiment_artifacts(run: TSPExperimentRun, output_dir: str | Path) -> Path:
    """Write canonical manifest/result/summary JSONL and CSV files into a new directory."""

    root = Path(output_dir)
    try:
        root.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise TSPProtocolError(f"experiment output directory must be new: {exc}") from exc
    _write_json(root / "dataset_manifest.json", run.dataset.to_dict())
    _write_jsonl(root / "results.jsonl", (result.to_dict() for result in run.results))
    _write_jsonl(root / "summary.jsonl", (summary.to_dict() for summary in run.summaries))
    _write_results_csv(root / "results.csv", run.results)
    _write_summary_csv(root / "summary.csv", run.summaries)
    return root


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        f"{json.dumps(value, allow_nan=False, indent=2, sort_keys=True)}\n", encoding="utf-8"
    )


def _write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(_canonical_json(value))
            stream.write("\n")


def _write_results_csv(path: Path, results: Sequence[TSPExperimentResult]) -> None:
    fields = [
        "run_id",
        "replay_checksum",
        "seed",
        "split",
        "instance_id",
        "nodes",
        "instance_checksum",
        "method",
        "provider",
        "prompt_visibility",
        "status",
        "llm_calls",
        "input_tokens",
        "output_tokens",
        "cost",
        "cost_currency",
        "valid_evals",
        "generated_candidates",
        "wall_time",
        "best_score",
        "failure_type",
        "failure_message",
        "budget_reached",
        "reached_limits",
        "hard_limits",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "run_id": result.run_id,
                    "replay_checksum": result.replay_checksum,
                    "seed": result.seed,
                    "split": result.split,
                    "instance_id": result.instance["instance_id"],
                    "nodes": result.instance["nodes"],
                    "instance_checksum": result.instance["checksum"],
                    "method": result.method,
                    "provider": result.provider["name"],
                    "prompt_visibility": result.prompt_visibility["condition"],
                    "status": result.status,
                    "llm_calls": result.llm_calls,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "cost": result.cost,
                    "cost_currency": result.cost_currency,
                    "valid_evals": result.valid_evals,
                    "generated_candidates": result.generated_candidates,
                    "wall_time": result.wall_time,
                    "best_score": result.best_score,
                    "failure_type": None if result.failure is None else result.failure["type"],
                    "failure_message": None
                    if result.failure is None
                    else result.failure["message"],
                    "budget_reached": result.budget["budget_reached"],
                    "reached_limits": _canonical_json(result.budget["reached_limits"]),
                    "hard_limits": _canonical_json(result.budget["hard_limits"]),
                }
            )


def _write_summary_csv(path: Path, summaries: Sequence[TSPExperimentSummary]) -> None:
    fields = [
        "method",
        "seed",
        "split",
        "prompt_visibility",
        "nodes",
        "runs",
        "completed_runs",
        "budget_exhausted_runs",
        "failed_runs",
        "scored_runs",
        "mean_best_score",
        "min_best_score",
        "total_llm_calls",
        "total_input_tokens",
        "total_output_tokens",
        "total_cost",
        "total_valid_evals",
        "total_generated_candidates",
        "total_wall_time",
        "input_replay_checksums",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for summary in summaries:
            document = summary.to_dict()
            writer.writerow({name: document[name] for name in fields})
