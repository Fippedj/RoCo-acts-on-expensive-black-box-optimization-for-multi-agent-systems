"""Strict, portable fact models for Stage 4 long-term memory.

The models in this module deliberately accept only ordinary JSON values.  They
are independent from the evolution runtime so persisted facts can be validated
and replayed without constructing an engine or provider.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, TypeAlias

MEMORY_EVENT_SCHEMA_VERSION = "roco-memory-event-v1"
ROLE_MEMORY_SUMMARY_SCHEMA_VERSION = "roco-role-memory-summary-v1"

MAX_MEMORY_TEXT_CHARACTERS = 2_000
MAX_SUMMARY_ITEMS = 64
MAX_IDENTIFIER_CHARACTERS = 512

MEMORY_ROLES = frozenset({"explorer", "exploiter", "integrator"})
MEMORY_EVENT_KINDS = frozenset(
    {
        "mutation",
        "invalid_output",
        "invalid_candidate",
        "evaluation_failure",
        "budget_exhausted",
    }
)
MEMORY_FAILURE_TYPES = frozenset(
    {
        "invalid_output",
        "invalid_candidate",
        "evaluation_timeout",
        "evaluation_error",
        "budget_exhausted",
        "provider_error",
        "summary_error",
    }
)

JsonNumber: TypeAlias = int | float

_EVENT_ID_PATTERN = re.compile(r"mem-[0-9a-f]{20}\Z")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(\b(?=[A-Za-z_][A-Za-z0-9_]*\s*=)"
    r"(?=[A-Za-z0-9_]*(?:api_?key|access_?key|token|secret|password|passwd|credential))"
    r"[A-Za-z_][A-Za-z0-9_]*\s*=\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)


def validate_json_safe(value: Any) -> None:
    """Reject values which cannot cross the strict portable JSON boundary."""

    value_type = type(value)
    if value is None or value_type in (str, bool, int):
        if value_type is str:
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("JSON text must be valid UTF-8") from exc
        return
    if value_type is float:
        if not math.isfinite(value):
            raise ValueError("JSON value contains a non-finite number")
        return
    if value_type is list:
        for item in value:
            validate_json_safe(item)
        return
    if value_type is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("JSON object keys must be strings")
            try:
                key.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("JSON object keys must be valid UTF-8") from exc
            validate_json_safe(item)
        return
    raise ValueError(f"value contains a non-JSON type: {value_type.__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a JSON-safe value as compact, sorted, deterministic UTF-8."""

    validate_json_safe(value)
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_json(value: Any) -> str:
    """Return the text form used by :func:`canonical_json_bytes`."""

    return canonical_json_bytes(value).decode("utf-8")


def sanitize_text(text: str, *, max_length: int = MAX_MEMORY_TEXT_CHARACTERS) -> str:
    """Clean generated text before persistence and apply a deterministic cap.

    Unicode control/format/surrogate characters become spaces, whitespace is
    collapsed, and common secret-bearing ``NAME=value`` assignments are
    redacted.  This is intentionally finite and conservative; it is not a
    general data-loss-prevention system.
    """

    if type(text) is not str:
        raise ValueError("memory text must be a string")
    if type(max_length) is not int or max_length < 1:
        raise ValueError("max_length must be a positive integer")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("memory text must be valid UTF-8") from exc

    without_controls = "".join(
        " " if unicodedata.category(character) in {"Cc", "Cf", "Cs"} else character
        for character in text
    )
    redacted = _SECRET_ASSIGNMENT_PATTERN.sub(r"\1[REDACTED]", without_controls)
    normalized = " ".join(redacted.split())
    return normalized[:max_length]


def minimize_delta(
    before_score: float | int | None, after_score: float | int | None
) -> float | None:
    """Return ``before - after`` for the minimize-only V1 objective."""

    before = _optional_finite_number(before_score, "before_score")
    after = _optional_finite_number(after_score, "after_score")
    if before is None or after is None:
        return None
    delta = before - after
    if not math.isfinite(delta):
        raise ValueError("delta_g must be finite")
    return 0.0 if delta == 0.0 else delta


@dataclass(frozen=True, slots=True)
class MemoryEvent:
    """One canonical, content-addressed Stage 4 memory fact."""

    schema_version: str
    event_id: str
    run_id: str
    benchmark: str
    objective: str
    generation: int
    round: int
    sequence: int
    role: str
    event_kind: str
    source_trace_event_ids: tuple[str, ...]
    parent_candidate_ids: tuple[str, ...]
    output_candidate_id: str | None
    before_score: float | None
    after_score: float | None
    delta_g: float | None
    improved: bool
    success: bool
    selected_in_population: bool
    feedback: str | None
    failure_type: str | None
    failure_message: str | None
    budget_before: Mapping[str, JsonNumber]
    budget_after: Mapping[str, JsonNumber]
    budget_delta: Mapping[str, JsonNumber]
    prompt_version: str
    provider_name: str
    model_name: str

    def __post_init__(self) -> None:
        before = _copy_budget(self.budget_before, "budget_before")
        after = _copy_budget(self.budget_after, "budget_after")
        delta = _copy_budget(self.budget_delta, "budget_delta")
        object.__setattr__(self, "budget_before", MappingProxyType(before))
        object.__setattr__(self, "budget_after", MappingProxyType(after))
        object.__setattr__(self, "budget_delta", MappingProxyType(delta))
        self._validate()

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        benchmark: str,
        objective: str,
        generation: int,
        sequence: int,
        role: str,
        event_kind: str,
        source_trace_event_ids: Sequence[str],
        parent_candidate_ids: Sequence[str],
        budget_before: Mapping[str, JsonNumber],
        budget_after: Mapping[str, JsonNumber],
        prompt_version: str,
        provider_name: str,
        model_name: str,
        round_index: int | None = None,
        round: int | None = None,
        output_candidate_id: str | None = None,
        before_score: float | int | None = None,
        after_score: float | int | None = None,
        success: bool = False,
        selected_in_population: bool = False,
        feedback: str | None = None,
        failure_type: str | None = None,
        failure_message: str | None = None,
    ) -> MemoryEvent:
        """Normalize fields, derive deltas, and assign the stable event ID."""

        resolved_round = _resolve_round(round_index, round)
        normalized_before = _optional_finite_number(before_score, "before_score")
        normalized_after = _optional_finite_number(after_score, "after_score")
        if not success and normalized_after is not None:
            raise ValueError("failed events cannot supply after_score")
        delta = minimize_delta(normalized_before, normalized_after) if success else None
        improved = bool(success and delta is not None and delta > 0.0)
        before_budget = _copy_budget(budget_before, "budget_before")
        after_budget = _copy_budget(budget_after, "budget_after")
        budget_delta = _calculate_budget_delta(before_budget, after_budget)
        source_ids = _copy_string_sequence(source_trace_event_ids, "source_trace_event_ids")
        parent_ids = _copy_string_sequence(parent_candidate_ids, "parent_candidate_ids")

        values: dict[str, Any] = {
            "schema_version": MEMORY_EVENT_SCHEMA_VERSION,
            "run_id": run_id,
            "benchmark": benchmark,
            "objective": objective,
            "generation": generation,
            "round": resolved_round,
            "sequence": sequence,
            "role": role,
            "event_kind": event_kind,
            "source_trace_event_ids": list(source_ids),
            "parent_candidate_ids": list(parent_ids),
            "output_candidate_id": output_candidate_id,
            "before_score": normalized_before,
            "after_score": normalized_after if success else None,
            "delta_g": delta,
            "improved": improved,
            "success": success,
            "selected_in_population": selected_in_population,
            "feedback": _sanitize_optional_text(feedback),
            "failure_type": failure_type,
            "failure_message": _sanitize_optional_text(failure_message),
            "budget_before": before_budget,
            "budget_after": after_budget,
            "budget_delta": budget_delta,
            "prompt_version": prompt_version,
            "provider_name": provider_name,
            "model_name": model_name,
        }
        digest = hashlib.sha256(canonical_json_bytes(values)).hexdigest()
        constructor_values = {
            **values,
            "source_trace_event_ids": source_ids,
            "parent_candidate_ids": parent_ids,
        }
        return cls(event_id=f"mem-{digest[:20]}", **constructor_values)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MemoryEvent:
        """Validate and restore an event without accepting schema extensions."""

        _require_object(value, _MEMORY_EVENT_FIELDS, "memory event")
        validate_json_safe(value)
        _require_list(value["source_trace_event_ids"], "source_trace_event_ids")
        _require_list(value["parent_candidate_ids"], "parent_candidate_ids")
        for name in ("budget_before", "budget_after", "budget_delta"):
            if type(value[name]) is not dict:
                raise ValueError(f"{name} must be an object")
        return cls(
            schema_version=value["schema_version"],
            event_id=value["event_id"],
            run_id=value["run_id"],
            benchmark=value["benchmark"],
            objective=value["objective"],
            generation=value["generation"],
            round=value["round"],
            sequence=value["sequence"],
            role=value["role"],
            event_kind=value["event_kind"],
            source_trace_event_ids=tuple(value["source_trace_event_ids"]),
            parent_candidate_ids=tuple(value["parent_candidate_ids"]),
            output_candidate_id=value["output_candidate_id"],
            before_score=value["before_score"],
            after_score=value["after_score"],
            delta_g=value["delta_g"],
            improved=value["improved"],
            success=value["success"],
            selected_in_population=value["selected_in_population"],
            feedback=value["feedback"],
            failure_type=value["failure_type"],
            failure_message=value["failure_message"],
            budget_before=dict(value["budget_before"]),
            budget_after=dict(value["budget_after"]),
            budget_delta=dict(value["budget_delta"]),
            prompt_version=value["prompt_version"],
            provider_name=value["provider_name"],
            model_name=value["model_name"],
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> MemoryEvent:
        return cls.from_dict(_load_json_object(value, "memory event"))

    @property
    def round_index(self) -> int:
        """Compatibility spelling for generation-local trace callers."""

        return self.round

    @property
    def content_digest(self) -> str:
        """Full SHA-256 digest behind the truncated public event ID."""

        return hashlib.sha256(canonical_json_bytes(self._content_dict())).hexdigest()

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        return (self.generation, self.round, self.sequence, self.event_id)

    def to_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, **self._content_dict()}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def _content_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "benchmark": self.benchmark,
            "objective": self.objective,
            "generation": self.generation,
            "round": self.round,
            "sequence": self.sequence,
            "role": self.role,
            "event_kind": self.event_kind,
            "source_trace_event_ids": list(self.source_trace_event_ids),
            "parent_candidate_ids": list(self.parent_candidate_ids),
            "output_candidate_id": self.output_candidate_id,
            "before_score": self.before_score,
            "after_score": self.after_score,
            "delta_g": self.delta_g,
            "improved": self.improved,
            "success": self.success,
            "selected_in_population": self.selected_in_population,
            "feedback": self.feedback,
            "failure_type": self.failure_type,
            "failure_message": self.failure_message,
            "budget_before": dict(self.budget_before),
            "budget_after": dict(self.budget_after),
            "budget_delta": dict(self.budget_delta),
            "prompt_version": self.prompt_version,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
        }

    def _validate(self) -> None:
        if self.schema_version != MEMORY_EVENT_SCHEMA_VERSION:
            raise ValueError("unsupported memory event schema_version")
        for name in ("run_id", "benchmark", "prompt_version", "provider_name", "model_name"):
            _validate_identifier(getattr(self, name), name)
        if self.objective != "minimize":
            raise ValueError("memory event objective must be 'minimize'")
        _validate_non_negative_integer(self.generation, "generation")
        _validate_non_negative_integer(self.round, "round")
        _validate_non_negative_integer(self.sequence, "sequence")
        if self.role not in MEMORY_ROLES:
            raise ValueError("memory event role is not supported")
        if self.event_kind not in MEMORY_EVENT_KINDS:
            raise ValueError("memory event_kind is not supported")
        _validate_identifiers(self.source_trace_event_ids, "source_trace_event_ids", required=True)
        _validate_identifiers(self.parent_candidate_ids, "parent_candidate_ids", required=True)
        if self.output_candidate_id is not None:
            _validate_identifier(self.output_candidate_id, "output_candidate_id")
        before = _optional_finite_number(self.before_score, "before_score")
        after = _optional_finite_number(self.after_score, "after_score")
        delta = _optional_finite_number(self.delta_g, "delta_g")
        for name in ("improved", "success", "selected_in_population"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        _validate_optional_stored_text(self.feedback, "feedback")
        _validate_optional_stored_text(self.failure_message, "failure_message")

        if self.success:
            if self.event_kind != "mutation":
                raise ValueError("successful events must have event_kind 'mutation'")
            if self.output_candidate_id is None or after is None:
                raise ValueError("successful events require an output candidate and after_score")
            if self.failure_type is not None or self.failure_message is not None:
                raise ValueError("successful events cannot contain failure fields")
            expected_delta = minimize_delta(before, after)
            if delta != expected_delta:
                raise ValueError("delta_g does not match minimize scores")
            if self.improved is not (expected_delta is not None and expected_delta > 0.0):
                raise ValueError("improved does not match the event scores")
        else:
            if self.event_kind == "mutation":
                raise ValueError("failed events cannot have event_kind 'mutation'")
            if after is not None or delta is not None or self.improved:
                raise ValueError("failed events cannot contain an outcome score or improvement")
            if self.selected_in_population:
                raise ValueError("failed events cannot be selected in the population")
            if self.failure_type not in MEMORY_FAILURE_TYPES:
                raise ValueError("failed events require a supported failure_type")
        if self.selected_in_population and self.output_candidate_id is None:
            raise ValueError("selected events require an output candidate")

        expected_budget_delta = _calculate_budget_delta(self.budget_before, self.budget_after)
        _validate_budget(self.budget_delta, "budget_delta", allow_empty=False)
        if self.budget_delta != expected_budget_delta:
            raise ValueError("budget_delta does not match budget snapshots")
        if not _EVENT_ID_PATTERN.fullmatch(self.event_id):
            raise ValueError("memory event_id has an invalid format")
        expected_event_id = f"mem-{self.content_digest[:20]}"
        if self.event_id != expected_event_id:
            raise ValueError("memory event_id does not match its canonical content")


@dataclass(frozen=True, slots=True)
class RoleMemorySummary:
    """Strict, rebuildable summary derived from committed role events."""

    schema_version: str
    role: str
    through_generation: int
    source_event_ids: tuple[str, ...]
    source_hash: str
    prompt_version: str
    provider_name: str
    model_name: str
    useful_strategies: tuple[str, ...]
    failure_patterns: tuple[str, ...]
    applicability_conditions: tuple[str, ...]
    avoid_patterns: tuple[str, ...]

    def __post_init__(self) -> None:
        self._validate()

    @classmethod
    def create(
        cls,
        *,
        role: str,
        through_generation: int,
        source_event_ids: Sequence[str],
        prompt_version: str,
        provider_name: str,
        model_name: str,
        useful_strategies: Sequence[str] = (),
        failure_patterns: Sequence[str] = (),
        applicability_conditions: Sequence[str] = (),
        avoid_patterns: Sequence[str] = (),
    ) -> RoleMemorySummary:
        source_ids = _copy_string_sequence(source_event_ids, "source_event_ids")
        return cls(
            schema_version=ROLE_MEMORY_SUMMARY_SCHEMA_VERSION,
            role=role,
            through_generation=through_generation,
            source_event_ids=source_ids,
            source_hash=source_event_ids_hash(source_ids),
            prompt_version=prompt_version,
            provider_name=provider_name,
            model_name=model_name,
            useful_strategies=_sanitize_text_sequence(useful_strategies, "useful_strategies"),
            failure_patterns=_sanitize_text_sequence(failure_patterns, "failure_patterns"),
            applicability_conditions=_sanitize_text_sequence(
                applicability_conditions, "applicability_conditions"
            ),
            avoid_patterns=_sanitize_text_sequence(avoid_patterns, "avoid_patterns"),
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RoleMemorySummary:
        _require_object(value, _ROLE_MEMORY_SUMMARY_FIELDS, "role memory summary")
        validate_json_safe(value)
        list_names = (
            "source_event_ids",
            "useful_strategies",
            "failure_patterns",
            "applicability_conditions",
            "avoid_patterns",
        )
        for name in list_names:
            _require_list(value[name], name)
        return cls(
            schema_version=value["schema_version"],
            role=value["role"],
            through_generation=value["through_generation"],
            source_event_ids=tuple(value["source_event_ids"]),
            source_hash=value["source_hash"],
            prompt_version=value["prompt_version"],
            provider_name=value["provider_name"],
            model_name=value["model_name"],
            useful_strategies=tuple(value["useful_strategies"]),
            failure_patterns=tuple(value["failure_patterns"]),
            applicability_conditions=tuple(value["applicability_conditions"]),
            avoid_patterns=tuple(value["avoid_patterns"]),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> RoleMemorySummary:
        return cls.from_dict(_load_json_object(value, "role memory summary"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "role": self.role,
            "through_generation": self.through_generation,
            "source_event_ids": list(self.source_event_ids),
            "source_hash": self.source_hash,
            "prompt_version": self.prompt_version,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "useful_strategies": list(self.useful_strategies),
            "failure_patterns": list(self.failure_patterns),
            "applicability_conditions": list(self.applicability_conditions),
            "avoid_patterns": list(self.avoid_patterns),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def _validate(self) -> None:
        if self.schema_version != ROLE_MEMORY_SUMMARY_SCHEMA_VERSION:
            raise ValueError("unsupported role memory summary schema_version")
        if self.role not in MEMORY_ROLES:
            raise ValueError("role memory summary role is not supported")
        _validate_non_negative_integer(self.through_generation, "through_generation")
        _validate_identifiers(self.source_event_ids, "source_event_ids", required=False)
        if any(not _EVENT_ID_PATTERN.fullmatch(event_id) for event_id in self.source_event_ids):
            raise ValueError("source_event_ids must contain memory event IDs")
        if not _DIGEST_PATTERN.fullmatch(self.source_hash):
            raise ValueError("role memory summary source_hash has an invalid format")
        if self.source_hash != source_event_ids_hash(self.source_event_ids):
            raise ValueError("role memory summary source_hash does not match its sources")
        for name in ("prompt_version", "provider_name", "model_name"):
            _validate_identifier(getattr(self, name), name)
        for name in (
            "useful_strategies",
            "failure_patterns",
            "applicability_conditions",
            "avoid_patterns",
        ):
            values = getattr(self, name)
            if type(values) is not tuple or len(values) > MAX_SUMMARY_ITEMS:
                raise ValueError(f"{name} must be a finite tuple of strings")
            for item in values:
                if type(item) is not str or not item:
                    raise ValueError(f"{name} must contain non-empty strings")
                if sanitize_text(item) != item:
                    raise ValueError(f"{name} contains text which is not normalized")


def source_event_ids_hash(source_event_ids: Sequence[str]) -> str:
    """Hash an ordered role-summary source list."""

    ids = _copy_string_sequence(source_event_ids, "source_event_ids")
    _validate_identifiers(ids, "source_event_ids", required=False)
    return hashlib.sha256(canonical_json_bytes(list(ids))).hexdigest()


_MEMORY_EVENT_FIELDS = {
    "schema_version",
    "event_id",
    "run_id",
    "benchmark",
    "objective",
    "generation",
    "round",
    "sequence",
    "role",
    "event_kind",
    "source_trace_event_ids",
    "parent_candidate_ids",
    "output_candidate_id",
    "before_score",
    "after_score",
    "delta_g",
    "improved",
    "success",
    "selected_in_population",
    "feedback",
    "failure_type",
    "failure_message",
    "budget_before",
    "budget_after",
    "budget_delta",
    "prompt_version",
    "provider_name",
    "model_name",
}

_ROLE_MEMORY_SUMMARY_FIELDS = {
    "schema_version",
    "role",
    "through_generation",
    "source_event_ids",
    "source_hash",
    "prompt_version",
    "provider_name",
    "model_name",
    "useful_strategies",
    "failure_patterns",
    "applicability_conditions",
    "avoid_patterns",
}


def _resolve_round(round_index: int | None, round_value: int | None) -> int:
    if round_index is None and round_value is None:
        raise ValueError("round_index (or round) is required")
    if round_index is not None and round_value is not None and round_index != round_value:
        raise ValueError("round_index and round disagree")
    result = round_index if round_index is not None else round_value
    assert result is not None
    return result


def _optional_finite_number(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number or null")
    result = float(value)
    return 0.0 if result == 0.0 else result


def _copy_budget(value: Mapping[str, JsonNumber], name: str) -> dict[str, JsonNumber]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    result = dict(value)
    _validate_budget(result, name, allow_empty=False)
    return result


def _validate_budget(value: Any, name: str, *, allow_empty: bool) -> None:
    if not isinstance(value, Mapping) or (not allow_empty and not value):
        raise ValueError(f"{name} must be a non-empty object")
    for key, item in value.items():
        _validate_identifier(key, f"{name} key")
        if type(item) not in (int, float) or not math.isfinite(item) or item < 0:
            raise ValueError(f"{name} values must be finite non-negative numbers")


def _calculate_budget_delta(
    before: Mapping[str, JsonNumber], after: Mapping[str, JsonNumber]
) -> dict[str, JsonNumber]:
    before_dict = dict(before)
    after_dict = dict(after)
    _validate_budget(before_dict, "budget_before", allow_empty=False)
    _validate_budget(after_dict, "budget_after", allow_empty=False)
    if set(before_dict) != set(after_dict):
        raise ValueError("budget_before and budget_after must contain the same counters")
    result: dict[str, JsonNumber] = {}
    for key in sorted(before_dict):
        delta = after_dict[key] - before_dict[key]
        if not math.isfinite(delta) or delta < 0:
            raise ValueError("budget counters must be finite and monotonic")
        result[key] = delta
    return result


def _sanitize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    sanitized = sanitize_text(value)
    return sanitized or None


def _validate_optional_stored_text(value: Any, name: str) -> None:
    if value is None:
        return
    if type(value) is not str or not value or sanitize_text(value) != value:
        raise ValueError(f"{name} must be normalized finite text or null")


def _sanitize_text_sequence(value: Sequence[str], name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence of strings")
    if len(value) > MAX_SUMMARY_ITEMS:
        raise ValueError(f"{name} contains too many items")
    result: list[str] = []
    for item in value:
        cleaned = sanitize_text(item)
        if not cleaned:
            raise ValueError(f"{name} cannot contain empty text")
        result.append(cleaned)
    return tuple(result)


def _copy_string_sequence(value: Sequence[str], name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence of strings")
    if not all(type(item) is str for item in value):
        raise ValueError(f"{name} must contain only strings")
    return tuple(value)


def _validate_identifiers(value: Any, name: str, *, required: bool) -> None:
    if type(value) is not tuple or (required and not value):
        qualifier = "non-empty " if required else ""
        raise ValueError(f"{name} must be a {qualifier}tuple of strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} cannot contain duplicate values")
    for item in value:
        _validate_identifier(item, name)


def _validate_identifier(value: Any, name: str) -> None:
    if type(value) is not str or not value or len(value) > MAX_IDENTIFIER_CHARACTERS:
        raise ValueError(f"{name} must be a finite non-empty string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} must be valid UTF-8") from exc
    if value.strip() != value or any(
        unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value
    ):
        raise ValueError(f"{name} cannot contain surrounding whitespace or control characters")


def _validate_non_negative_integer(value: Any, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_object(value: Any, expected_keys: set[str], name: str) -> None:
    if type(value) is not dict or set(value) != expected_keys:
        raise ValueError(f"{name} keys do not match its schema")


def _require_list(value: Any, name: str) -> None:
    if type(value) is not list:
        raise ValueError(f"{name} must be an array")


def _load_json_object(value: str | bytes | bytearray, name: str) -> dict[str, Any]:
    if type(value) not in (str, bytes, bytearray):
        raise ValueError(f"{name} JSON must be text or bytes")

    def reject_constant(constant: str) -> None:
        raise ValueError(f"non-finite JSON constant is forbidden: {constant}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = item
        return result

    try:
        parsed = json.loads(
            value,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid {name} JSON") from exc
    if type(parsed) is not dict:
        raise ValueError(f"{name} JSON must contain one object")
    return parsed
