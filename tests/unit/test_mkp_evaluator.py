from __future__ import annotations

from roco_ebbo.benchmarks import MKPInstance
from roco_ebbo.evaluation import MKPCodeEvaluator


def _instance() -> MKPInstance:
    return MKPInstance(
        instance_id="fixture",
        capacities=(5, 6),
        weights=(2, 3, 4),
        profits=(4, 5, 8),
        input_files=(
            {"filename": "fixture_c.txt", "sha256": "a" * 64},
            {"filename": "fixture_w.txt", "sha256": "b" * 64},
            {"filename": "fixture_p.txt", "sha256": "c" * 64},
        ),
        reference_file=None,
    )


def test_evaluator_returns_negative_profit_and_audit_normalization() -> None:
    code = """def heuristic(capacities, weights, profits):
    return [[0, 1], [2]]
"""
    result = MKPCodeEvaluator(timeout_seconds=2).evaluate(code, _instance())

    assert result.valid and result.feasible
    assert result.raw_profit == 17
    assert result.score == -17.0
    assert result.normalized_score == -1.0


def test_evaluator_rejects_over_capacity_and_duplicate_assignment() -> None:
    over_capacity = """def heuristic(capacities, weights, profits):
    return [[0, 2], []]
"""
    duplicate = """def heuristic(capacities, weights, profits):
    return [[0], [0]]
"""
    evaluator = MKPCodeEvaluator(timeout_seconds=2)

    assert evaluator.evaluate(over_capacity, _instance()).error_type == "capacity_exceeded"
    assert evaluator.evaluate(duplicate, _instance()).error_type == "duplicate_assignment"


def test_evaluator_rejects_illegal_candidate_and_signature() -> None:
    illegal = """def heuristic(capacities, weights, profits):
    return [[99], []]
"""
    signature = """def heuristic(capacities):
    return []
"""
    evaluator = MKPCodeEvaluator(timeout_seconds=2)

    assert evaluator.evaluate(illegal, _instance()).error_type == "invalid_assignment"
    assert evaluator.evaluate(signature, _instance()).error_type == "signature_error"


def test_evaluator_structures_runtime_error_and_timeout() -> None:
    runtime_error = """def heuristic(capacities, weights, profits):
    return 1 / 0
"""
    timeout = """def heuristic(capacities, weights, profits):
    while True:
        pass
"""

    runtime_result = MKPCodeEvaluator(timeout_seconds=2).evaluate(runtime_error, _instance())
    timeout_result = MKPCodeEvaluator(timeout_seconds=0.2).evaluate(timeout, _instance())

    assert runtime_result.error_type == "runtime_error"
    assert timeout_result.error_type == "timeout"
    assert timeout_result.runtime_seconds < 2
