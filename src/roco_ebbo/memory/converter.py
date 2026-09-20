"""Pure conversion from Stage 3 generation traces to Stage 4 memory facts."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from roco_ebbo.evolution.collaboration import CollaborationTrace

from .models import MemoryEvent, sanitize_text, validate_json_safe


@dataclass(frozen=True, slots=True)
class MemoryConversionIssue:
    """One isolated source record which could not become a memory event."""

    trace_index: int
    source_trace_event_id: str | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_index": self.trace_index,
            "source_trace_event_id": self.source_trace_event_id,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class MemoryConversionReport:
    """Converted facts plus deterministic reports for isolated bad records."""

    events: tuple[MemoryEvent, ...]
    issues: tuple[MemoryConversionIssue, ...]

    @property
    def skipped_count(self) -> int:
        return len(self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_ids": [event.event_id for event in self.events],
            "converted_count": len(self.events),
            "skipped_count": self.skipped_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def convert_collaboration_trace(
    trace: CollaborationTrace | dict[str, Any],
    *,
    run_id: str,
    benchmark: str,
    provider_name: str,
    model_name: str,
    objective: str = "minimize",
    selected_candidate_ids: Sequence[str] | None = None,
    evaluations: Mapping[str, Any] | None = None,
) -> tuple[MemoryEvent, ...]:
    """Convert proposal/integration facts while excluding Critic-only events.

    ``evaluations`` is an optional candidate-ID mapping used when evaluation
    facts are held separately from the trace.  A mapping value may be a finite
    score, ``None``, or an evaluation-result dictionary.  When absent, the
    evaluation embedded in the Stage 3 trace remains authoritative.
    """

    return convert_collaboration_trace_with_report(
        trace,
        run_id=run_id,
        benchmark=benchmark,
        provider_name=provider_name,
        model_name=model_name,
        objective=objective,
        selected_candidate_ids=selected_candidate_ids,
        evaluations=evaluations,
    ).events


def convert_collaboration_trace_with_report(
    trace: CollaborationTrace | dict[str, Any],
    *,
    run_id: str,
    benchmark: str,
    provider_name: str,
    model_name: str,
    objective: str = "minimize",
    selected_candidate_ids: Sequence[str] | None = None,
    evaluations: Mapping[str, Any] | None = None,
) -> MemoryConversionReport:
    """Return converted events and reports for individually malformed records."""

    _validate_conversion_context(
        run_id=run_id,
        benchmark=benchmark,
        objective=objective,
        provider_name=provider_name,
        model_name=model_name,
    )
    raw_trace = _trace_dict(trace)
    generation = _trace_generation(raw_trace)
    raw_events = raw_trace.get("events")
    if type(raw_events) is not list:
        raise ValueError("collaboration trace events must be an array")
    selected = _selected_ids(raw_trace, selected_candidate_ids)
    if evaluations is not None and not isinstance(evaluations, Mapping):
        raise ValueError("evaluations must be a candidate-ID mapping")
    if evaluations is not None and not all(
        type(candidate_id) is str and candidate_id for candidate_id in evaluations
    ):
        raise ValueError("evaluation mapping keys must be non-empty candidate IDs")

    converted: list[MemoryEvent] = []
    issues: list[MemoryConversionIssue] = []
    memory_sequence = 0
    for trace_index, raw_event in enumerate(raw_events):
        if type(raw_event) is not dict:
            continue
        if not _is_generation_action(raw_event):
            continue
        sequence = memory_sequence
        memory_sequence += 1
        source_id = raw_event.get("event_id")
        report_id = (
            sanitize_text(source_id, max_length=500) or None if type(source_id) is str else None
        )
        try:
            event = _convert_event(
                raw_event,
                trace_index=trace_index,
                trace_events=raw_events,
                generation=generation,
                sequence=sequence,
                run_id=run_id,
                benchmark=benchmark,
                objective=objective,
                provider_name=provider_name,
                model_name=model_name,
                selected=selected,
                evaluations=evaluations,
            )
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(
                MemoryConversionIssue(
                    trace_index=trace_index,
                    source_trace_event_id=report_id,
                    message=sanitize_text(str(exc), max_length=500) or "invalid trace event",
                )
            )
            continue
        converted.append(event)

    converted.sort(key=lambda event: event.sort_key)
    _fail_on_collision(converted)
    return MemoryConversionReport(tuple(converted), tuple(issues))


def _convert_event(
    raw_event: dict[str, Any],
    *,
    trace_index: int,
    trace_events: list[Any],
    generation: int,
    sequence: int,
    run_id: str,
    benchmark: str,
    objective: str,
    provider_name: str,
    model_name: str,
    selected: frozenset[str],
    evaluations: Mapping[str, Any] | None,
) -> MemoryEvent:
    role = _required_string(raw_event, "role")
    action = _required_string(raw_event, "action")
    expected_action = "integrate" if role == "integrator" else "propose"
    if role not in {"explorer", "exploiter", "integrator"} or action != expected_action:
        raise ValueError("generation event role/action pair is invalid")
    source_id = _required_string(raw_event, "event_id")
    round_index = _required_non_negative_integer(raw_event, "round")
    target_branch = _required_string(raw_event, "target_branch")
    prompt_version = _required_string(raw_event, "prompt_version")
    input_candidates = raw_event.get("input_candidates")
    if type(input_candidates) is not list:
        raise ValueError("trace input_candidates must be an array")
    expected_parent_count = 2 if role == "integrator" else 1
    if len(input_candidates) != expected_parent_count:
        raise ValueError(f"{role} event must contain {expected_parent_count} input candidate(s)")

    parent_candidate_ids: list[str] = []
    parent_scores: list[float | None] = []
    for candidate in input_candidates:
        if type(candidate) is not dict:
            raise ValueError("trace input candidate must be an object")
        candidate_id = _required_string(candidate, "id")
        parent_candidate_ids.append(candidate_id)
        parent_scores.append(_candidate_score(candidate, candidate_id, evaluations))

    before_score = _before_score(role, parent_scores)
    output = raw_event.get("output_candidate")
    if output is not None and type(output) is not dict:
        raise ValueError("trace output_candidate must be an object or null")
    output_candidate_id = None if output is None else _required_string(output, "id")
    evaluation = _evaluation_fact(raw_event, output_candidate_id, output, evaluations)
    status = _required_string(raw_event, "status")
    outcome = _normalize_outcome(
        status=status,
        role=role,
        before_score=before_score,
        output_candidate_id=output_candidate_id,
        evaluation=evaluation,
        source_error_type=raw_event.get("error_type"),
        source_error_message=raw_event.get("error_message"),
    )

    source_trace_event_ids = [source_id]
    feedback: str | None = None
    if role in {"explorer", "exploiter"}:
        critic = _subsequent_critic(
            trace_events,
            start_index=trace_index + 1,
            round_index=round_index,
            target_branch=target_branch,
        )
        if critic is not None:
            critic_id = critic.get("event_id")
            if type(critic_id) is str and critic_id:
                source_trace_event_ids.append(critic_id)
                output_feedback = critic.get("output_feedback")
                if type(output_feedback) is str and output_feedback.strip():
                    feedback = output_feedback

    return MemoryEvent.create(
        run_id=run_id,
        benchmark=benchmark,
        objective=objective,
        generation=generation,
        round_index=round_index,
        sequence=sequence,
        role=role,
        event_kind=outcome.event_kind,
        source_trace_event_ids=source_trace_event_ids,
        parent_candidate_ids=parent_candidate_ids,
        output_candidate_id=output_candidate_id,
        before_score=before_score,
        after_score=outcome.after_score,
        success=outcome.success,
        selected_in_population=(
            outcome.success and output_candidate_id is not None and output_candidate_id in selected
        ),
        feedback=feedback,
        failure_type=outcome.failure_type,
        failure_message=outcome.failure_message,
        budget_before=_required_budget(raw_event, "budget_before"),
        budget_after=_required_budget(raw_event, "budget_after"),
        prompt_version=prompt_version,
        provider_name=provider_name,
        model_name=model_name,
    )


@dataclass(frozen=True, slots=True)
class _EvaluationFact:
    present: bool
    valid: bool
    score: float | None
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class _NormalizedOutcome:
    success: bool
    after_score: float | None
    event_kind: str
    failure_type: str | None
    failure_message: str | None


def _normalize_outcome(
    *,
    status: str,
    role: str,
    before_score: float | None,
    output_candidate_id: str | None,
    evaluation: _EvaluationFact,
    source_error_type: Any,
    source_error_message: Any,
) -> _NormalizedOutcome:
    if status not in {
        "success",
        "invalid_output",
        "invalid_candidate",
        "provider_error",
        "budget_exhausted",
    }:
        raise ValueError("trace status is not supported")
    message = source_error_message if type(source_error_message) is str else None
    source_type = source_error_type if type(source_error_type) is str else None

    if status == "success":
        if output_candidate_id is None:
            return _failed("invalid_output", "invalid_output", message)
        if before_score is None:
            baseline_message = f"{role} input candidates do not have finite scores"
            return _failed("invalid_candidate", "invalid_candidate", baseline_message)
        if evaluation.valid and evaluation.score is not None:
            return _NormalizedOutcome(True, evaluation.score, "mutation", None, None)
        failure_type, event_kind = _evaluation_failure(evaluation.error_type)
        return _failed(
            event_kind,
            failure_type,
            evaluation.error_message
            or message
            or "candidate evaluation did not produce a finite score",
        )
    if status == "invalid_output":
        return _failed("invalid_output", "invalid_output", message)
    if status == "provider_error":
        return _failed("invalid_output", "provider_error", message)
    if status == "budget_exhausted":
        return _failed("budget_exhausted", "budget_exhausted", message)

    error_type = evaluation.error_type or source_type
    if error_type == "timeout":
        return _failed(
            "evaluation_failure",
            "evaluation_timeout",
            evaluation.error_message or message,
        )
    if error_type in {"runtime_error", "evaluation_error"} or not evaluation.present:
        return _failed(
            "evaluation_failure",
            "evaluation_error",
            evaluation.error_message or message,
        )
    return _failed(
        "invalid_candidate",
        "invalid_candidate",
        evaluation.error_message or message,
    )


def _failed(event_kind: str, failure_type: str, message: str | None) -> _NormalizedOutcome:
    return _NormalizedOutcome(False, None, event_kind, failure_type, message)


def _evaluation_failure(error_type: str | None) -> tuple[str, str]:
    if error_type == "timeout":
        return ("evaluation_timeout", "evaluation_failure")
    return ("evaluation_error", "evaluation_failure")


def _evaluation_fact(
    raw_event: dict[str, Any],
    candidate_id: str | None,
    output_candidate: dict[str, Any] | None,
    evaluations: Mapping[str, Any] | None,
) -> _EvaluationFact:
    if candidate_id is not None and evaluations is not None and candidate_id in evaluations:
        return _parse_evaluation(evaluations[candidate_id])
    embedded = raw_event.get("evaluation")
    if embedded is not None:
        return _parse_evaluation(embedded)
    if output_candidate is not None:
        score = _finite_optional_score(output_candidate.get("score"), "output candidate score")
        if score is not None:
            return _EvaluationFact(True, True, score, None, None)
    return _EvaluationFact(False, False, None, None, None)


def _parse_evaluation(value: Any) -> _EvaluationFact:
    if value is None:
        return _EvaluationFact(True, False, None, None, None)
    if type(value) in (int, float):
        return _EvaluationFact(
            True,
            True,
            _finite_optional_score(value, "evaluation score"),
            None,
            None,
        )
    if hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    if type(value) is not dict:
        raise ValueError("evaluation must be a score, result object, or null")
    valid = value.get("valid")
    if type(valid) is not bool:
        raise ValueError("evaluation valid must be a boolean")
    score = _finite_optional_score(value.get("score"), "evaluation score")
    if valid and score is None:
        return _EvaluationFact(
            True,
            False,
            None,
            "evaluation_error",
            "valid evaluation is missing a finite score",
        )
    error_type = value.get("error_type")
    error_message = value.get("error_message")
    if error_type is not None and type(error_type) is not str:
        raise ValueError("evaluation error_type must be a string or null")
    if error_message is not None and type(error_message) is not str:
        raise ValueError("evaluation error_message must be a string or null")
    return _EvaluationFact(True, valid, score if valid else None, error_type, error_message)


def _candidate_score(
    candidate: dict[str, Any], candidate_id: str, evaluations: Mapping[str, Any] | None
) -> float | None:
    if evaluations is not None and candidate_id in evaluations:
        evaluation = _parse_evaluation(evaluations[candidate_id])
        return evaluation.score if evaluation.valid else None
    return _finite_optional_score(candidate.get("score"), "candidate score")


def _before_score(role: str, scores: list[float | None]) -> float | None:
    if role == "integrator":
        if len(scores) != 2 or any(score is None for score in scores):
            return None
        return min(score for score in scores if score is not None)
    return scores[0] if scores else None


def _subsequent_critic(
    events: list[Any], *, start_index: int, round_index: int, target_branch: str
) -> dict[str, Any] | None:
    for item in events[start_index:]:
        if type(item) is not dict:
            continue
        if (
            item.get("role") == "critic"
            and item.get("action") == "compare"
            and item.get("round") == round_index
            and item.get("target_branch") == target_branch
        ):
            return item
    return None


def _trace_dict(trace: CollaborationTrace | dict[str, Any]) -> dict[str, Any]:
    if isinstance(trace, CollaborationTrace):
        value = trace.to_dict()
    elif type(trace) is dict:
        value = trace
    else:
        raise ValueError("trace must be a CollaborationTrace or JSON object")
    validate_json_safe(value)
    schema_version = value.get("schema_version")
    if schema_version != "roco-collaboration-trace-v1":
        raise ValueError("unsupported collaboration trace schema_version")
    if value.get("scope") != "generation-local":
        raise ValueError("collaboration trace must have generation-local scope")
    return value


def _trace_generation(trace: dict[str, Any]) -> int:
    value = trace.get("generation")
    if type(value) is not int or value < 0:
        raise ValueError("collaboration trace generation must be a non-negative integer")
    return value


def _selected_ids(trace: dict[str, Any], override: Sequence[str] | None) -> frozenset[str]:
    value: Any = trace.get("selected_candidate_ids", []) if override is None else override
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError("selected_candidate_ids must be a sequence of strings")
    if not all(type(candidate_id) is str and candidate_id for candidate_id in value):
        raise ValueError("selected_candidate_ids must contain non-empty strings")
    return frozenset(value)


def _validate_conversion_context(
    *, run_id: Any, benchmark: Any, objective: Any, provider_name: Any, model_name: Any
) -> None:
    for name, value in (
        ("run_id", run_id),
        ("benchmark", benchmark),
        ("provider_name", provider_name),
        ("model_name", model_name),
    ):
        if type(value) is not str or not value or len(value) > 512 or sanitize_text(value) != value:
            raise ValueError(f"{name} must be normalized finite text")
    if objective != "minimize":
        raise ValueError("memory conversion supports only objective='minimize'")


def _is_generation_action(event: dict[str, Any]) -> bool:
    return event.get("action") in {"propose", "integrate"}


def _required_string(value: dict[str, Any], name: str) -> str:
    item = value.get(name)
    if type(item) is not str or not item:
        raise ValueError(f"trace {name} must be a non-empty string")
    return item


def _required_non_negative_integer(value: dict[str, Any], name: str) -> int:
    item = value.get(name)
    if type(item) is not int or item < 0:
        raise ValueError(f"trace {name} must be a non-negative integer")
    return item


def _required_budget(value: dict[str, Any], name: str) -> dict[str, int | float]:
    item = value.get(name)
    if type(item) is not dict:
        raise ValueError(f"trace {name} must be an object")
    return dict(item)


def _finite_optional_score(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number or null")
    result = float(value)
    return 0.0 if result == 0.0 else result


def _fail_on_collision(events: Sequence[MemoryEvent]) -> None:
    seen: dict[str, str] = {}
    for event in events:
        previous = seen.get(event.event_id)
        if previous is not None and previous != event.content_digest:
            raise ValueError(f"memory event ID collision: {event.event_id}")
        seen[event.event_id] = event.content_digest
