from __future__ import annotations

from typing import Any

from roco_ebbo.evolution import CollaborationEvent, CollaborationTrace
from roco_ebbo.llm import RoCoRole
from roco_ebbo.memory.converter import convert_collaboration_trace


def _candidate(candidate_id: str, score: float | None) -> dict[str, Any]:
    return {
        "id": candidate_id,
        "description": f"candidate {candidate_id}",
        "code": "def heuristic(distance_matrix):\n    return []\n",
        "parents": [],
        "operator": "test",
        "generation": 1,
        "score": score,
        "metadata": {},
    }


def _budget(value: int) -> dict[str, int | float]:
    return {
        "llm_calls": value,
        "input_tokens": value * 2,
        "output_tokens": value,
        "tokens": value * 3,
        "generated_candidates": value,
        "valid_evals": value,
        "cost": 0.0,
    }


def _event(
    event_id: str,
    role: RoCoRole,
    action: str,
    round_index: int,
    inputs: tuple[dict[str, Any], ...],
    *,
    target_branch: str,
    output_candidate: dict[str, Any] | None = None,
    output_feedback: str | None = None,
    evaluation: dict[str, Any] | None = None,
    status: str = "success",
    error_type: str | None = None,
    error_message: str | None = None,
    budget_index: int = 0,
) -> CollaborationEvent:
    return CollaborationEvent(
        event_id=event_id,
        role=role,
        action=action,
        round_index=round_index,
        target_branch=target_branch,
        temperature=1.0,
        prompt_version="roco-role-prompts-v1",
        input_candidates=inputs,
        input_feedback=(),
        output_candidate=output_candidate,
        output_feedback=output_feedback,
        evaluation=evaluation,
        budget_before=_budget(budget_index),
        budget_after=_budget(budget_index + 1),
        status=status,  # type: ignore[arg-type]
        error_type=error_type,
        error_message=error_message,
    )


def _trace(events: list[CollaborationEvent]) -> CollaborationTrace:
    return CollaborationTrace(
        generation=1,
        elite_pair=(_candidate("explorer-parent", 12.0), _candidate("exploiter-parent", 8.0)),
        elite_pair_ranks=(1, 0),
        sampling_power=3.0,
        sampling_seed=19,
        sampling_weights=(0.5, 0.5),
        rounds_requested=1,
        events=events,
        rounds_completed=1,
    )


def _convert(trace: CollaborationTrace, selected_candidate_ids: tuple[str, ...] | None = None):
    return convert_collaboration_trace(
        trace,
        run_id="run-a",
        benchmark="tsp",
        provider_name="mock",
        model_name="deterministic",
        selected_candidate_ids=selected_candidate_ids,
    )


def test_converter_maps_all_successful_roles_and_associates_branch_feedback() -> None:
    explorer_parent = _candidate("explorer-parent", 12.0)
    exploiter_parent = _candidate("exploiter-parent", 8.0)
    explorer_child = _candidate("explorer-child", 9.0)
    exploiter_child = _candidate("exploiter-child", 7.0)
    integrated = _candidate("integrated", 6.0)
    events = [
        _event(
            "initial-critic",
            RoCoRole.CRITIC,
            "initial_compare",
            0,
            (explorer_parent, exploiter_parent),
            target_branch="both",
            output_feedback="Initial feedback is audit-only.",
        ),
        _event(
            "explorer-proposal",
            RoCoRole.EXPLORER,
            "propose",
            1,
            (explorer_parent,),
            target_branch="explorer",
            output_candidate=explorer_child,
            evaluation={"score": 9.0, "valid": True, "runtime_seconds": 0.01},
            budget_index=1,
        ),
        _event(
            "exploiter-proposal",
            RoCoRole.EXPLOITER,
            "propose",
            1,
            (exploiter_parent,),
            target_branch="exploiter",
            output_candidate=exploiter_child,
            evaluation={"score": 7.0, "valid": True, "runtime_seconds": 0.02},
            budget_index=2,
        ),
        _event(
            "explorer-critic",
            RoCoRole.CRITIC,
            "compare",
            1,
            (explorer_parent, explorer_child),
            target_branch="explorer",
            output_feedback="Explorer feedback",
            budget_index=3,
        ),
        _event(
            "exploiter-critic",
            RoCoRole.CRITIC,
            "compare",
            1,
            (exploiter_parent, exploiter_child),
            target_branch="exploiter",
            output_feedback="Exploiter feedback",
            budget_index=4,
        ),
        _event(
            "integrator-proposal",
            RoCoRole.INTEGRATOR,
            "integrate",
            1,
            (explorer_child, exploiter_child),
            target_branch="both",
            output_candidate=integrated,
            evaluation={"score": 6.0, "valid": True, "runtime_seconds": 0.03},
            budget_index=5,
        ),
    ]
    trace = _trace(events)
    original_trace = trace.to_json()

    converted = _convert(trace, ("explorer-child", "integrated"))

    assert trace.to_json() == original_trace
    assert converted == _convert(trace, ("explorer-child", "integrated"))
    assert [event.role for event in converted] == ["explorer", "exploiter", "integrator"]
    assert [event.sequence for event in converted] == [0, 1, 2]
    assert [event.before_score for event in converted] == [12.0, 8.0, 7.0]
    assert [event.after_score for event in converted] == [9.0, 7.0, 6.0]
    assert [event.delta_g for event in converted] == [3.0, 1.0, 1.0]
    assert all(event.success and event.improved for event in converted)
    assert [event.selected_in_population for event in converted] == [True, False, True]
    assert converted[0].feedback == "Explorer feedback"
    assert converted[1].feedback == "Exploiter feedback"
    assert converted[0].source_trace_event_ids == (
        "explorer-proposal",
        "explorer-critic",
    )
    assert converted[1].source_trace_event_ids == (
        "exploiter-proposal",
        "exploiter-critic",
    )
    assert converted[2].parent_candidate_ids == ("explorer-child", "exploiter-child")
    assert all("code" not in event.to_json() for event in converted)


def test_converter_preserves_structured_failures_for_every_generating_role() -> None:
    explorer_parent = _candidate("explorer-parent", 12.0)
    exploiter_parent = _candidate("exploiter-parent", 8.0)
    bad_exploiter = _candidate("bad-exploiter", None)
    events = [
        _event(
            "explorer-invalid-output",
            RoCoRole.EXPLORER,
            "propose",
            1,
            (explorer_parent,),
            target_branch="explorer",
            status="invalid_output",
            error_type="role_output_error",
            error_message="bad\x00 structured response",
        ),
        _event(
            "exploiter-invalid-candidate",
            RoCoRole.EXPLOITER,
            "propose",
            1,
            (exploiter_parent,),
            target_branch="exploiter",
            output_candidate=bad_exploiter,
            evaluation={
                "score": None,
                "valid": False,
                "runtime_seconds": 0.1,
                "error_type": "timeout",
                "error_message": "evaluation timed out",
            },
            status="invalid_candidate",
            error_type="timeout",
            error_message="evaluation timed out",
            budget_index=1,
        ),
        _event(
            "integrator-budget",
            RoCoRole.INTEGRATOR,
            "integrate",
            1,
            (explorer_parent, exploiter_parent),
            target_branch="both",
            status="budget_exhausted",
            error_type="BudgetExceededError",
            error_message="hard budget reached",
            budget_index=2,
        ),
    ]

    converted = _convert(_trace(events))

    assert [event.role for event in converted] == ["explorer", "exploiter", "integrator"]
    assert [event.event_kind for event in converted] == [
        "invalid_output",
        "evaluation_failure",
        "budget_exhausted",
    ]
    assert not any(event.success or event.improved for event in converted)
    assert [event.after_score for event in converted] == [None, None, None]
    assert [event.delta_g for event in converted] == [None, None, None]
    assert converted[0].output_candidate_id is None
    assert converted[1].output_candidate_id == "bad-exploiter"
    assert converted[2].before_score == 8.0
    assert converted[0].failure_type == "invalid_output"
    assert converted[1].failure_type == "evaluation_timeout"
    assert converted[2].failure_type == "budget_exhausted"
    assert "\x00" not in (converted[0].failure_message or "")


def test_converter_maps_provider_error_to_a_structured_memory_failure() -> None:
    parent = _candidate("explorer-parent", 12.0)
    trace = _trace(
        [
            _event(
                "explorer-provider-error",
                RoCoRole.EXPLORER,
                "propose",
                1,
                (parent,),
                target_branch="explorer",
                status="provider_error",
                error_type="ConnectionError",
                error_message="provider transport failed",
                budget_index=1,
            )
        ]
    )

    (event,) = _convert(trace)

    assert event.role == "explorer"
    assert event.event_kind == "invalid_output"
    assert event.failure_type == "provider_error"
    assert event.failure_message == "provider transport failed"
    assert event.success is False
    assert event.after_score is None
    assert event.delta_g is None
    assert event.improved is False


def test_converter_maps_non_timeout_evaluation_error_to_a_structured_failure() -> None:
    parent = _candidate("exploiter-parent", 8.0)
    output = _candidate("exploiter-child", None)
    trace = _trace(
        [
            _event(
                "exploiter-evaluation-error",
                RoCoRole.EXPLOITER,
                "propose",
                1,
                (parent,),
                target_branch="exploiter",
                output_candidate=output,
                evaluation={
                    "score": None,
                    "valid": False,
                    "runtime_seconds": 0.1,
                    "error_type": "runtime_error",
                    "error_message": "evaluator worker crashed",
                },
                status="invalid_candidate",
                error_type="runtime_error",
                error_message="evaluator worker crashed",
                budget_index=1,
            )
        ]
    )

    (event,) = _convert(trace)

    assert event.role == "exploiter"
    assert event.event_kind == "evaluation_failure"
    assert event.failure_type == "evaluation_error"
    assert event.failure_message == "evaluator worker crashed"
    assert event.output_candidate_id == "exploiter-child"
    assert event.success is False
    assert event.after_score is None
    assert event.delta_g is None
    assert event.improved is False


def test_selected_ids_default_to_final_trace_selection() -> None:
    parent = _candidate("parent", 4.0)
    child = _candidate("child", 3.0)
    trace = _trace(
        [
            _event(
                "proposal",
                RoCoRole.EXPLORER,
                "propose",
                1,
                (parent,),
                target_branch="explorer",
                output_candidate=child,
                evaluation={"score": 3.0, "valid": True, "runtime_seconds": 0.01},
            )
        ]
    )
    trace.selected_candidate_ids = ("child",)

    (event,) = _convert(trace)

    assert event.selected_in_population is True
