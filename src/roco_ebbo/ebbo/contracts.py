"""Strict, replayable JSON contracts for the Stage 6 P9a EBBO runtime."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

CANONICAL_JSON_VERSION = "roco-ebbo-canonical-json-v1"
ORACLE_REQUEST_VERSION = "ebbo-oracle-request-v1"
ORACLE_RESULT_VERSION = "ebbo-oracle-result-v1"
OBSERVATION_VERSION = "ebbo-observation-v1"


class EvaluationStatus(StrEnum):
    """Auditable states shared by requests, results, and observations."""

    RESERVED = "reserved"
    ACCEPTED = "accepted"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED_BEFORE_ACCEPT = "cancelled_before_accept"
    CANCELLED_AFTER_ACCEPT = "cancelled_after_accept"


def strict_json_loads(value: str | bytes) -> JsonValue:
    """Decode strict JSON, rejecting duplicate keys and non-finite constants."""

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = item
        return result

    def reject_constant(constant: str) -> None:
        raise ValueError(f"non-finite JSON constant: {constant}")

    try:
        decoded = json.loads(
            value,
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    require_json_safe(decoded)
    return decoded  # type: ignore[no-any-return]


def require_json_safe(value: Any, *, path: str = "$") -> None:
    """Reject values that cannot cross the strict EBBO persistence boundary."""

    if value is None or isinstance(value, str) or type(value) in (bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            require_json_safe(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError(f"{path} object keys must be strings")
        for key, item in value.items():
            require_json_safe(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} contains non-JSON value: {type(value).__name__}")


def canonical_json(value: JsonValue) -> str:
    """Return the one P9a canonical encoding used for hashes and JSONL."""

    require_json_safe(value)
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def stable_id(kind: str, payload: JsonValue) -> str:
    """Create a domain-separated full SHA-256 identifier."""

    if not kind or not kind.isascii():
        raise ValueError("stable ID kind must be a non-empty ASCII string")
    envelope: JsonValue = {
        "canonical_json_version": CANONICAL_JSON_VERSION,
        "kind": kind,
        "payload": payload,
    }
    digest = hashlib.sha256(canonical_json(envelope).encode("utf-8")).hexdigest()
    return f"{kind}-{digest}"


def derive_seed(root_seed: int, *labels: str | int) -> int:
    """Derive a portable non-negative 63-bit seed from explicit labels."""

    if type(root_seed) is not int or root_seed < 0:
        raise ValueError("root_seed must be a non-negative integer")
    normalized: list[JsonValue] = []
    for label in labels:
        if type(label) is int:
            normalized.append(label)
        elif isinstance(label, str) and label:
            normalized.append(label)
        else:
            raise ValueError("seed labels must be integers or non-empty strings")
    digest = stable_id("seed", {"root_seed": root_seed, "labels": normalized}).rsplit("-", 1)[1]
    return int(digest[:16], 16) & ((1 << 63) - 1)


def _exact_mapping(value: Any, expected: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    if set(value) != expected:
        unknown = sorted(set(value) - expected)
        missing = sorted(expected - set(value))
        raise ValueError(f"{name} schema mismatch; unknown={unknown}, missing={missing}")
    require_json_safe(value)
    return value


def _non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_timestamp(value: Any, name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be a string or null")
    return value


def _finite_number(value: Any, name: str, *, optional: bool = False) -> float | None:
    if optional and value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number" + (" or null" if optional else ""))
    return float(value)


def _json_object(value: Any, name: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    require_json_safe(value)
    return value  # type: ignore[return-value]


def _cost_record(value: Any, name: str) -> dict[str, JsonValue]:
    record = _exact_mapping(value, {"amount", "unit", "source"}, name)
    amount = record["amount"]
    if amount is not None:
        numeric = _finite_number(amount, f"{name}.amount")
        assert numeric is not None
        if numeric < 0:
            raise ValueError(f"{name}.amount must be non-negative")
    _non_empty_string(record["unit"], f"{name}.unit")
    _non_empty_string(record["source"], f"{name}.source")
    return record  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class OracleRequest:
    """One immutable candidate evaluation request."""

    schema_version: str
    request_id: str
    run_id: str
    problem_id: str
    problem_version: str
    oracle_contract_version: str
    candidate_id: str
    candidate: dict[str, JsonValue]
    objective_direction: str
    constraint_contract: dict[str, JsonValue]
    logical_evaluation_index: int
    replicate_index: int
    oracle_seed: int | None
    timeout_seconds: float
    seed_lineage: dict[str, JsonValue]
    budget_reservation: dict[str, JsonValue]
    reservation_id: str
    deduplication_key: str
    provenance: dict[str, JsonValue]
    created_at_utc: str | None = None

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        problem_id: str,
        candidate_id: str,
        candidate: dict[str, JsonValue],
        seed_lineage: dict[str, JsonValue],
        budget_reservation: dict[str, JsonValue],
        problem_version: str = "ebbo-mock-problem-v1",
        oracle_contract_version: str = "ebbo-mock-expensive-oracle-v1",
        logical_evaluation_index: int = 0,
        replicate_index: int = 0,
        oracle_seed: int | None = None,
        timeout_seconds: float = 1.0,
        provenance: dict[str, JsonValue] | None = None,
        created_at_utc: str | None = None,
    ) -> OracleRequest:
        reservation_id = stable_id(
            "reservation",
            {
                "run_id": run_id,
                "logical_evaluation_index": logical_evaluation_index,
                "candidate_id": candidate_id,
                "budget_reservation": budget_reservation,
            },
        )
        deduplication_key = stable_id(
            "deduplication",
            {
                "problem_id": problem_id,
                "problem_version": problem_version,
                "candidate_id": candidate_id,
                "replicate_index": replicate_index,
            },
        )
        fields: dict[str, JsonValue] = {
            "schema_version": ORACLE_REQUEST_VERSION,
            "run_id": run_id,
            "problem_id": problem_id,
            "problem_version": problem_version,
            "oracle_contract_version": oracle_contract_version,
            "candidate_id": candidate_id,
            "candidate": candidate,
            "objective_direction": "minimize",
            "constraint_contract": {"enabled": False, "version": "none-v1"},
            "logical_evaluation_index": logical_evaluation_index,
            "replicate_index": replicate_index,
            "oracle_seed": oracle_seed,
            "timeout_seconds": timeout_seconds,
            "seed_lineage": seed_lineage,
            "budget_reservation": budget_reservation,
            "reservation_id": reservation_id,
            "deduplication_key": deduplication_key,
            "provenance": provenance or {},
        }
        request_id = stable_id("request", fields)
        return cls.from_dict({**fields, "request_id": request_id, "created_at_utc": created_at_utc})

    def replay_dict(self) -> dict[str, JsonValue]:
        value = self.to_dict()
        value.pop("created_at_utc")
        return value

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "problem_id": self.problem_id,
            "problem_version": self.problem_version,
            "oracle_contract_version": self.oracle_contract_version,
            "candidate_id": self.candidate_id,
            "candidate": self.candidate,
            "objective_direction": self.objective_direction,
            "constraint_contract": self.constraint_contract,
            "logical_evaluation_index": self.logical_evaluation_index,
            "replicate_index": self.replicate_index,
            "oracle_seed": self.oracle_seed,
            "timeout_seconds": self.timeout_seconds,
            "seed_lineage": self.seed_lineage,
            "budget_reservation": self.budget_reservation,
            "reservation_id": self.reservation_id,
            "deduplication_key": self.deduplication_key,
            "provenance": self.provenance,
            "created_at_utc": self.created_at_utc,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, value: str | bytes) -> OracleRequest:
        decoded = strict_json_loads(value)
        if not isinstance(decoded, dict):
            raise ValueError("OracleRequest JSON must contain an object")
        return cls.from_dict(decoded)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> OracleRequest:
        names = {
            "schema_version",
            "request_id",
            "run_id",
            "problem_id",
            "problem_version",
            "oracle_contract_version",
            "candidate_id",
            "candidate",
            "objective_direction",
            "constraint_contract",
            "logical_evaluation_index",
            "replicate_index",
            "oracle_seed",
            "timeout_seconds",
            "seed_lineage",
            "budget_reservation",
            "reservation_id",
            "deduplication_key",
            "provenance",
            "created_at_utc",
        }
        raw = _exact_mapping(value, names, "OracleRequest")
        if raw["schema_version"] != ORACLE_REQUEST_VERSION:
            raise ValueError("unsupported OracleRequest schema_version")
        for name in (
            "request_id",
            "run_id",
            "problem_id",
            "problem_version",
            "oracle_contract_version",
            "candidate_id",
            "reservation_id",
            "deduplication_key",
        ):
            _non_empty_string(raw[name], f"OracleRequest.{name}")
        if raw["objective_direction"] != "minimize":
            raise ValueError("P9a supports only objective_direction=minimize")
        candidate = _json_object(raw["candidate"], "OracleRequest.candidate")
        constraint_contract = _json_object(
            raw["constraint_contract"], "OracleRequest.constraint_contract"
        )
        for name in ("logical_evaluation_index", "replicate_index"):
            if type(raw[name]) is not int or raw[name] < 0:
                raise ValueError(f"OracleRequest.{name} must be a non-negative integer")
        oracle_seed = raw["oracle_seed"]
        if oracle_seed is not None and (type(oracle_seed) is not int or oracle_seed < 0):
            raise ValueError("OracleRequest.oracle_seed must be a non-negative integer or null")
        timeout_seconds = _finite_number(raw["timeout_seconds"], "OracleRequest.timeout_seconds")
        assert timeout_seconds is not None
        if timeout_seconds <= 0:
            raise ValueError("OracleRequest.timeout_seconds must be greater than zero")
        seed_lineage = _json_object(raw["seed_lineage"], "OracleRequest.seed_lineage")
        reservation = _json_object(raw["budget_reservation"], "OracleRequest.budget_reservation")
        provenance = _json_object(raw["provenance"], "OracleRequest.provenance")
        _optional_timestamp(raw["created_at_utc"], "OracleRequest.created_at_utc")
        hashed = {
            key: item for key, item in raw.items() if key not in {"request_id", "created_at_utc"}
        }
        if raw["request_id"] != stable_id("request", hashed):
            raise ValueError("OracleRequest request_id does not match its content")
        expected_reservation_id = stable_id(
            "reservation",
            {
                "run_id": raw["run_id"],
                "logical_evaluation_index": raw["logical_evaluation_index"],
                "candidate_id": raw["candidate_id"],
                "budget_reservation": reservation,
            },
        )
        if raw["reservation_id"] != expected_reservation_id:
            raise ValueError("OracleRequest reservation_id does not match its content")
        expected_deduplication_key = stable_id(
            "deduplication",
            {
                "problem_id": raw["problem_id"],
                "problem_version": raw["problem_version"],
                "candidate_id": raw["candidate_id"],
                "replicate_index": raw["replicate_index"],
            },
        )
        if raw["deduplication_key"] != expected_deduplication_key:
            raise ValueError("OracleRequest deduplication_key does not match its content")
        return cls(
            schema_version=ORACLE_REQUEST_VERSION,
            request_id=raw["request_id"],
            run_id=raw["run_id"],
            problem_id=raw["problem_id"],
            problem_version=raw["problem_version"],
            oracle_contract_version=raw["oracle_contract_version"],
            candidate_id=raw["candidate_id"],
            candidate=candidate,
            objective_direction="minimize",
            constraint_contract=constraint_contract,
            logical_evaluation_index=raw["logical_evaluation_index"],
            replicate_index=raw["replicate_index"],
            oracle_seed=oracle_seed,
            timeout_seconds=timeout_seconds,
            seed_lineage=seed_lineage,
            budget_reservation=reservation,
            reservation_id=raw["reservation_id"],
            deduplication_key=raw["deduplication_key"],
            provenance=provenance,
            created_at_utc=raw["created_at_utc"],
        )


@dataclass(frozen=True, slots=True)
class OracleResult:
    """Validated terminal result for one accepted attempt."""

    schema_version: str
    result_id: str
    request_id: str
    attempt_id: str
    status: EvaluationStatus
    objective: float | None
    constraints: dict[str, JsonValue] | None
    feasible: bool | None
    failure: dict[str, JsonValue] | None
    actual_cost: dict[str, JsonValue]
    noise: dict[str, JsonValue]
    oracle_metadata: dict[str, JsonValue]
    started_at_utc: str | None = None
    completed_at_utc: str | None = None

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        attempt_id: str,
        status: EvaluationStatus,
        objective: float | None,
        constraints: dict[str, JsonValue] | None,
        feasible: bool | None,
        failure: dict[str, JsonValue] | None,
        actual_cost: dict[str, JsonValue],
        oracle_metadata: dict[str, JsonValue],
        noise: dict[str, JsonValue] | None = None,
        started_at_utc: str | None = None,
        completed_at_utc: str | None = None,
    ) -> OracleResult:
        fields: dict[str, JsonValue] = {
            "schema_version": ORACLE_RESULT_VERSION,
            "request_id": request_id,
            "attempt_id": attempt_id,
            "status": status.value,
            "objective": objective,
            "constraints": constraints,
            "feasible": feasible,
            "failure": failure,
            "actual_cost": actual_cost,
            "noise": noise or {"kind": "none"},
            "oracle_metadata": oracle_metadata,
        }
        result_id = stable_id("result", fields)
        return cls.from_dict(
            {
                **fields,
                "result_id": result_id,
                "started_at_utc": started_at_utc,
                "completed_at_utc": completed_at_utc,
            }
        )

    def replay_dict(self) -> dict[str, JsonValue]:
        value = self.to_dict()
        value.pop("started_at_utc")
        value.pop("completed_at_utc")
        return value

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "result_id": self.result_id,
            "request_id": self.request_id,
            "attempt_id": self.attempt_id,
            "status": self.status.value,
            "objective": self.objective,
            "constraints": self.constraints,
            "feasible": self.feasible,
            "failure": self.failure,
            "actual_cost": self.actual_cost,
            "noise": self.noise,
            "oracle_metadata": self.oracle_metadata,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, value: str | bytes) -> OracleResult:
        decoded = strict_json_loads(value)
        if not isinstance(decoded, dict):
            raise ValueError("OracleResult JSON must contain an object")
        return cls.from_dict(decoded)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> OracleResult:
        names = {
            "schema_version",
            "result_id",
            "request_id",
            "attempt_id",
            "status",
            "objective",
            "constraints",
            "feasible",
            "failure",
            "actual_cost",
            "noise",
            "oracle_metadata",
            "started_at_utc",
            "completed_at_utc",
        }
        raw = _exact_mapping(value, names, "OracleResult")
        if raw["schema_version"] != ORACLE_RESULT_VERSION:
            raise ValueError("unsupported OracleResult schema_version")
        for name in ("result_id", "request_id", "attempt_id"):
            _non_empty_string(raw[name], f"OracleResult.{name}")
        try:
            status = EvaluationStatus(raw["status"])
        except (TypeError, ValueError) as exc:
            raise ValueError("OracleResult.status is unknown") from exc
        if status not in {
            EvaluationStatus.SUCCEEDED,
            EvaluationStatus.FAILED,
            EvaluationStatus.TIMED_OUT,
        }:
            raise ValueError("OracleResult must have a terminal oracle status")
        objective = _finite_number(raw["objective"], "OracleResult.objective", optional=True)
        constraints_raw = raw["constraints"]
        constraints: dict[str, JsonValue] | None = None
        if constraints_raw is not None:
            if not isinstance(constraints_raw, dict):
                raise ValueError("OracleResult.constraints must be an object or null")
            constraints = {}
            for key, item in constraints_raw.items():
                constraints[key] = _finite_number(item, f"constraint {key}")
        feasible = raw["feasible"]
        if feasible is not None and type(feasible) is not bool:
            raise ValueError("OracleResult.feasible must be a boolean or null")
        failure_raw = raw["failure"]
        failure = None if failure_raw is None else _json_object(failure_raw, "OracleResult.failure")
        if status is EvaluationStatus.SUCCEEDED:
            if objective is None or failure is not None:
                raise ValueError("successful OracleResult needs objective and no failure")
        elif (
            objective is not None
            or constraints is not None
            or feasible is not None
            or failure is None
        ):
            raise ValueError(
                "failed OracleResult cannot fabricate objective, constraints, or feasible"
            )
        actual_cost = _cost_record(raw["actual_cost"], "OracleResult.actual_cost")
        noise = _json_object(raw["noise"], "OracleResult.noise")
        if noise.get("kind") != "none":
            raise ValueError("P9a Mock OracleResult requires noise.kind=none")
        metadata = _json_object(raw["oracle_metadata"], "OracleResult.oracle_metadata")
        _optional_timestamp(raw["started_at_utc"], "OracleResult.started_at_utc")
        _optional_timestamp(raw["completed_at_utc"], "OracleResult.completed_at_utc")
        excluded = {"result_id", "started_at_utc", "completed_at_utc"}
        hashed = {key: item for key, item in raw.items() if key not in excluded}
        if raw["result_id"] != stable_id("result", hashed):
            raise ValueError("OracleResult result_id does not match its content")
        return cls(
            schema_version=ORACLE_RESULT_VERSION,
            result_id=raw["result_id"],
            request_id=raw["request_id"],
            attempt_id=raw["attempt_id"],
            status=status,
            objective=objective,
            constraints=constraints,
            feasible=feasible,
            failure=failure,
            actual_cost=actual_cost,
            noise=noise,
            oracle_metadata=metadata,
            started_at_utc=raw["started_at_utc"],
            completed_at_utc=raw["completed_at_utc"],
        )


@dataclass(frozen=True, slots=True)
class Observation:
    """Immutable fact derived from a request and one terminal oracle result."""

    schema_version: str
    observation_id: str
    run_id: str
    request_id: str
    attempt_id: str
    result_id: str
    candidate_id: str
    candidate: dict[str, JsonValue]
    status: EvaluationStatus
    objective: float | None
    constraints: dict[str, JsonValue] | None
    feasible: bool | None
    failure: dict[str, JsonValue] | None
    actual_cost: dict[str, JsonValue]
    noise: dict[str, JsonValue]
    logical_evaluation_index: int
    completion_sequence: int
    eligible_for_objective_surrogate: bool
    source_result_hash: str
    seed_lineage: dict[str, JsonValue]
    oracle_metadata: dict[str, JsonValue]
    observed_at_utc: str | None = None

    @classmethod
    def from_result(
        cls,
        request: OracleRequest,
        result: OracleResult,
        *,
        completion_sequence: int = 0,
        observed_at_utc: str | None = None,
    ) -> Observation:
        if result.request_id != request.request_id:
            raise ValueError("result does not belong to request")
        fields: dict[str, JsonValue] = {
            "schema_version": OBSERVATION_VERSION,
            "run_id": request.run_id,
            "request_id": request.request_id,
            "attempt_id": result.attempt_id,
            "result_id": result.result_id,
            "candidate_id": request.candidate_id,
            "candidate": request.candidate,
            "status": result.status.value,
            "objective": result.objective,
            "constraints": result.constraints,
            "feasible": result.feasible,
            "failure": result.failure,
            "actual_cost": result.actual_cost,
            "noise": result.noise,
            "logical_evaluation_index": request.logical_evaluation_index,
            "completion_sequence": completion_sequence,
            "eligible_for_objective_surrogate": result.status is EvaluationStatus.SUCCEEDED,
            "source_result_hash": result.result_id,
            "seed_lineage": request.seed_lineage,
            "oracle_metadata": result.oracle_metadata,
        }
        identity = {key: item for key, item in fields.items() if key != "completion_sequence"}
        observation_id = stable_id("observation", identity)
        return cls.from_dict(
            {
                **fields,
                "observation_id": observation_id,
                "observed_at_utc": observed_at_utc,
            }
        )

    def replay_dict(self) -> dict[str, JsonValue]:
        value = self.to_dict()
        value.pop("observed_at_utc")
        return value

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "observation_id": self.observation_id,
            "run_id": self.run_id,
            "request_id": self.request_id,
            "attempt_id": self.attempt_id,
            "result_id": self.result_id,
            "candidate_id": self.candidate_id,
            "candidate": self.candidate,
            "status": self.status.value,
            "objective": self.objective,
            "constraints": self.constraints,
            "feasible": self.feasible,
            "failure": self.failure,
            "actual_cost": self.actual_cost,
            "noise": self.noise,
            "logical_evaluation_index": self.logical_evaluation_index,
            "completion_sequence": self.completion_sequence,
            "eligible_for_objective_surrogate": self.eligible_for_objective_surrogate,
            "source_result_hash": self.source_result_hash,
            "seed_lineage": self.seed_lineage,
            "oracle_metadata": self.oracle_metadata,
            "observed_at_utc": self.observed_at_utc,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, value: str | bytes) -> Observation:
        decoded = strict_json_loads(value)
        if not isinstance(decoded, dict):
            raise ValueError("Observation JSON must contain an object")
        return cls.from_dict(decoded)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Observation:
        names = {
            "schema_version",
            "observation_id",
            "run_id",
            "request_id",
            "attempt_id",
            "result_id",
            "candidate_id",
            "candidate",
            "status",
            "objective",
            "constraints",
            "feasible",
            "failure",
            "actual_cost",
            "noise",
            "logical_evaluation_index",
            "completion_sequence",
            "eligible_for_objective_surrogate",
            "source_result_hash",
            "seed_lineage",
            "oracle_metadata",
            "observed_at_utc",
        }
        raw = _exact_mapping(value, names, "Observation")
        if raw["schema_version"] != OBSERVATION_VERSION:
            raise ValueError("unsupported Observation schema_version")
        for name in (
            "observation_id",
            "run_id",
            "request_id",
            "attempt_id",
            "result_id",
            "candidate_id",
            "source_result_hash",
        ):
            _non_empty_string(raw[name], f"Observation.{name}")
        try:
            status = EvaluationStatus(raw["status"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Observation.status is unknown") from exc
        if status not in {
            EvaluationStatus.SUCCEEDED,
            EvaluationStatus.FAILED,
            EvaluationStatus.TIMED_OUT,
        }:
            raise ValueError("Observation must have a terminal status")
        objective = _finite_number(raw["objective"], "Observation.objective", optional=True)
        constraints_raw = raw["constraints"]
        constraints: dict[str, JsonValue] | None = None
        if constraints_raw is not None:
            if not isinstance(constraints_raw, dict):
                raise ValueError("Observation.constraints must be an object or null")
            constraints = {}
            for key, item in constraints_raw.items():
                constraints[key] = _finite_number(item, f"constraint {key}")
        feasible = raw["feasible"]
        if feasible is not None and type(feasible) is not bool:
            raise ValueError("Observation.feasible must be a boolean or null")
        failure_raw = raw["failure"]
        failure = None if failure_raw is None else _json_object(failure_raw, "Observation.failure")
        if status is EvaluationStatus.SUCCEEDED:
            if objective is None or failure is not None:
                raise ValueError("successful Observation needs objective and no failure")
        elif (
            objective is not None
            or constraints is not None
            or feasible is not None
            or failure is None
        ):
            raise ValueError(
                "failed Observation cannot fabricate objective, constraints, or feasible"
            )
        actual_cost = _cost_record(raw["actual_cost"], "Observation.actual_cost")
        candidate = _json_object(raw["candidate"], "Observation.candidate")
        noise = _json_object(raw["noise"], "Observation.noise")
        if noise.get("kind") != "none":
            raise ValueError("P9a Mock Observation requires noise.kind=none")
        for name in ("logical_evaluation_index", "completion_sequence"):
            if type(raw[name]) is not int or raw[name] < 0:
                raise ValueError(f"Observation.{name} must be a non-negative integer")
        eligible = raw["eligible_for_objective_surrogate"]
        if type(eligible) is not bool or eligible != (status is EvaluationStatus.SUCCEEDED):
            raise ValueError("Observation surrogate eligibility does not match status")
        if raw["source_result_hash"] != raw["result_id"]:
            raise ValueError("Observation source_result_hash does not match result_id")
        seed_lineage = _json_object(raw["seed_lineage"], "Observation.seed_lineage")
        metadata = _json_object(raw["oracle_metadata"], "Observation.oracle_metadata")
        _optional_timestamp(raw["observed_at_utc"], "Observation.observed_at_utc")
        excluded = {"observation_id", "observed_at_utc", "completion_sequence"}
        hashed = {key: item for key, item in raw.items() if key not in excluded}
        if raw["observation_id"] != stable_id("observation", hashed):
            raise ValueError("Observation observation_id does not match its content")
        return cls(
            schema_version=OBSERVATION_VERSION,
            observation_id=raw["observation_id"],
            run_id=raw["run_id"],
            request_id=raw["request_id"],
            attempt_id=raw["attempt_id"],
            result_id=raw["result_id"],
            candidate_id=raw["candidate_id"],
            candidate=candidate,
            status=status,
            objective=objective,
            constraints=constraints,
            feasible=feasible,
            failure=failure,
            actual_cost=actual_cost,
            noise=noise,
            logical_evaluation_index=raw["logical_evaluation_index"],
            completion_sequence=raw["completion_sequence"],
            eligible_for_objective_surrogate=eligible,
            source_result_hash=raw["source_result_hash"],
            seed_lineage=seed_lineage,
            oracle_metadata=metadata,
            observed_at_utc=raw["observed_at_utc"],
        )
