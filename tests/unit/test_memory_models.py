from __future__ import annotations

import json
import re

import pytest

from roco_ebbo.memory.models import (
    MemoryEvent,
    RoleMemorySummary,
    minimize_delta,
    sanitize_text,
)


def _event_kwargs() -> dict[str, object]:
    return {
        "run_id": "run-7",
        "benchmark": "tsp",
        "objective": "minimize",
        "generation": 3,
        "round_index": 2,
        "sequence": 1,
        "role": "explorer",
        "event_kind": "mutation",
        "source_trace_event_ids": ("trace-4", "trace-5"),
        "parent_candidate_ids": ("parent-a",),
        "output_candidate_id": "child-a",
        "before_score": 12.5,
        "after_score": 10.0,
        "success": True,
        "selected_in_population": False,
        "feedback": "Keep the bounded change.",
        "failure_type": None,
        "failure_message": None,
        "budget_before": {
            "llm_calls": 4,
            "input_tokens": 10,
            "output_tokens": 5,
            "tokens": 15,
            "generated_candidates": 2,
            "valid_evals": 2,
            "cost": 0.0,
        },
        "budget_after": {
            "llm_calls": 5,
            "input_tokens": 14,
            "output_tokens": 7,
            "tokens": 21,
            "generated_candidates": 3,
            "valid_evals": 3,
            "cost": 0.0,
        },
        "prompt_version": "roco-role-prompts-v1",
        "provider_name": "mock",
        "model_name": "deterministic",
    }


def test_memory_event_strict_json_round_trip() -> None:
    event = MemoryEvent.create(**_event_kwargs())

    encoded = event.to_json()
    payload = json.loads(encoded)
    restored = MemoryEvent.from_json(encoded)

    assert restored == event
    assert restored.to_dict() == payload
    assert payload["schema_version"] == "roco-memory-event-v1"
    assert payload["source_trace_event_ids"] == ["trace-4", "trace-5"]
    assert "code" not in encoded

    payload["unexpected"] = True
    with pytest.raises(ValueError, match="schema|keys|unexpected"):
        MemoryEvent.from_dict(payload)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_memory_event_rejects_non_finite_scores_and_budget_values(bad_value: float) -> None:
    score_kwargs = _event_kwargs()
    score_kwargs["after_score"] = bad_value
    with pytest.raises(ValueError, match="finite"):
        MemoryEvent.create(**score_kwargs)

    budget_kwargs = _event_kwargs()
    budget_after = dict(budget_kwargs["budget_after"])  # type: ignore[arg-type]
    budget_after["cost"] = bad_value
    budget_kwargs["budget_after"] = budget_after
    with pytest.raises(ValueError, match="finite"):
        MemoryEvent.create(**budget_kwargs)


def test_text_cleaning_is_bounded_deterministic_and_applied_at_event_boundary() -> None:
    dirty = " useful\x00idea\nwith\tcontrols " + ("x" * 100)

    cleaned = sanitize_text(dirty, max_length=32)

    assert cleaned == sanitize_text(dirty, max_length=32)
    assert len(cleaned) <= 32
    assert all(ord(character) >= 32 and ord(character) != 127 for character in cleaned)

    kwargs = _event_kwargs()
    kwargs["feedback"] = dirty
    event = MemoryEvent.create(**kwargs)
    assert event.feedback == sanitize_text(dirty)

    failed_kwargs = _event_kwargs()
    failed_kwargs.update(
        success=False,
        after_score=None,
        selected_in_population=False,
        event_kind="evaluation_failure",
        failure_type="evaluation_error",
        failure_message=dirty,
    )
    failed = MemoryEvent.create(**failed_kwargs)
    assert failed.failure_message == sanitize_text(dirty)


def test_event_text_redacts_secret_assignments_in_feedback_and_failures() -> None:
    feedback_secret = "Keep OPENAI_API_KEY=sk-feedback-secret out of the proposal."
    failure_secret = 'Worker failed: DATABASE_PASSWORD = "failure-secret"'

    feedback_kwargs = _event_kwargs()
    feedback_kwargs["feedback"] = feedback_secret
    feedback_event = MemoryEvent.create(**feedback_kwargs)

    failure_kwargs = _event_kwargs()
    failure_kwargs.update(
        success=False,
        after_score=None,
        selected_in_population=False,
        event_kind="evaluation_failure",
        failure_type="evaluation_error",
        failure_message=failure_secret,
    )
    failure_event = MemoryEvent.create(**failure_kwargs)

    assert feedback_event.feedback == "Keep OPENAI_API_KEY=[REDACTED] out of the proposal."
    assert failure_event.failure_message == "Worker failed: DATABASE_PASSWORD = [REDACTED]"
    assert "sk-feedback-secret" not in feedback_event.to_json()
    assert "failure-secret" not in failure_event.to_json()


def test_minimize_delta_and_improved_semantics() -> None:
    assert minimize_delta(10.0, 7.5) == 2.5
    assert minimize_delta(10.0, 10.0) == 0.0
    assert minimize_delta(None, 7.5) is None
    assert minimize_delta(10.0, None) is None

    improved = MemoryEvent.create(**_event_kwargs())
    assert improved.delta_g == 2.5
    assert improved.improved is True

    non_improving_kwargs = _event_kwargs()
    non_improving_kwargs["after_score"] = 13.0
    non_improving = MemoryEvent.create(**non_improving_kwargs)
    assert non_improving.delta_g == -0.5
    assert non_improving.improved is False

    failed_kwargs = _event_kwargs()
    failed_kwargs.update(success=False, after_score=9.0, event_kind="evaluation_failure")
    failed_kwargs.update(failure_type="evaluation_error", failure_message="worker failed")
    with pytest.raises(ValueError, match="failed|after_score|outcome"):
        MemoryEvent.create(**failed_kwargs)

    failed_kwargs["after_score"] = None
    failed = MemoryEvent.create(**failed_kwargs)
    assert failed.after_score is None
    assert failed.delta_g is None
    assert failed.improved is False

    unsupported_kwargs = _event_kwargs()
    unsupported_kwargs["objective"] = "maximize"
    with pytest.raises(ValueError, match="minimize"):
        MemoryEvent.create(**unsupported_kwargs)


def test_event_id_is_stable_across_mapping_order_and_changes_with_content() -> None:
    first_kwargs = _event_kwargs()
    second_kwargs = _event_kwargs()
    second_kwargs["budget_before"] = dict(
        reversed(list(dict(second_kwargs["budget_before"]).items()))  # type: ignore[arg-type]
    )
    second_kwargs["budget_after"] = dict(
        reversed(list(dict(second_kwargs["budget_after"]).items()))  # type: ignore[arg-type]
    )

    first = MemoryEvent.create(**first_kwargs)
    second = MemoryEvent.create(**second_kwargs)

    assert first.event_id == second.event_id
    assert first.content_digest == second.content_digest
    assert re.fullmatch(r"mem-[0-9a-f]{20}", first.event_id)

    changed_kwargs = _event_kwargs()
    changed_kwargs["selected_in_population"] = True
    changed = MemoryEvent.create(**changed_kwargs)
    assert changed.event_id != first.event_id
    assert changed.content_digest != first.content_digest


def test_role_summary_is_strict_rebuildable_and_cleans_each_text_item() -> None:
    summary = RoleMemorySummary.create(
        role="integrator",
        through_generation=3,
        source_event_ids=("mem-00000000000000000001", "mem-00000000000000000002"),
        prompt_version="ltreflect-v1",
        provider_name="mock",
        model_name="deterministic",
        useful_strategies=(" merge\x00 useful edges ",),
        failure_patterns=("avoid\ntimeouts",),
        applicability_conditions=("finite scored parents",),
        avoid_patterns=("unbounded loops",),
    )

    restored = RoleMemorySummary.from_json(summary.to_json())

    assert restored == summary
    assert restored.schema_version == "roco-role-memory-summary-v1"
    assert restored.useful_strategies == ("merge useful edges",)
    assert restored.failure_patterns == ("avoid timeouts",)
    assert len(restored.source_hash) == 64

    tampered = restored.to_dict()
    tampered["source_event_ids"] = list(reversed(tampered["source_event_ids"]))
    with pytest.raises(ValueError, match="source_hash"):
        RoleMemorySummary.from_dict(tampered)


def test_json_readers_reject_nonfinite_constants_and_duplicate_keys() -> None:
    event = MemoryEvent.create(**_event_kwargs())
    nonfinite = event.to_json().replace('"after_score":10.0', '"after_score":NaN')
    with pytest.raises(ValueError, match="non-finite"):
        MemoryEvent.from_json(nonfinite)

    duplicate = event.to_json().replace(
        '"schema_version":"roco-memory-event-v1"',
        '"schema_version":"roco-memory-event-v1","schema_version":"roco-memory-event-v1"',
    )
    with pytest.raises(ValueError, match="duplicate"):
        MemoryEvent.from_json(duplicate)
