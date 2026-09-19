from __future__ import annotations

import pytest

from roco_ebbo.benchmarks import generate_symmetric_distance_matrix
from roco_ebbo.evaluation import TSPCodeEvaluator


@pytest.fixture
def distance_matrix() -> list[list[float]]:
    return generate_symmetric_distance_matrix(nodes=20, seed=11)


def test_evaluator_accepts_a_complete_permutation(distance_matrix: list[list[float]]) -> None:
    code = """def heuristic(distance_matrix):
    return list(range(len(distance_matrix)))
"""
    result = TSPCodeEvaluator(timeout_seconds=2).evaluate(code, distance_matrix)

    assert result.valid
    assert result.score is not None and result.score > 0
    assert result.error_type is None


def test_evaluator_rejects_an_illegal_tour(distance_matrix: list[list[float]]) -> None:
    code = """def heuristic(distance_matrix):
    return [0, 0]
"""
    result = TSPCodeEvaluator(timeout_seconds=2).evaluate(code, distance_matrix)

    assert not result.valid
    assert result.error_type == "invalid_tour"


@pytest.mark.parametrize(
    ("code", "error_type"),
    [
        ("def heuristic(:\n    return []\n", "syntax_error"),
        ("def heuristic(matrix, extra):\n    return []\n", "signature_error"),
        ("import os\ndef heuristic(distance_matrix):\n    return []\n", "unsafe_code"),
    ],
)
def test_evaluator_classifies_static_failures(
    distance_matrix: list[list[float]], code: str, error_type: str
) -> None:
    result = TSPCodeEvaluator(timeout_seconds=2).evaluate(code, distance_matrix)
    assert not result.valid
    assert result.error_type == error_type


def test_evaluator_returns_runtime_error_without_stopping_run(
    distance_matrix: list[list[float]],
) -> None:
    code = """def heuristic(distance_matrix):
    return 1 / 0
"""
    result = TSPCodeEvaluator(timeout_seconds=2).evaluate(code, distance_matrix)

    assert not result.valid
    assert result.error_type == "runtime_error"
    assert "ZeroDivisionError" in (result.error_message or "")


def test_evaluator_terminates_a_timeout_candidate(distance_matrix: list[list[float]]) -> None:
    code = """def heuristic(distance_matrix):
    while True:
        pass
"""
    result = TSPCodeEvaluator(timeout_seconds=0.2).evaluate(code, distance_matrix)

    assert not result.valid
    assert result.error_type == "timeout"
    assert result.runtime_seconds < 2
