from __future__ import annotations

import json
import re

import pytest

from roco_ebbo.ebbo import (
    EvaluationStatus,
    Observation,
    OracleRequest,
    OracleResult,
    derive_seed,
    stable_id,
    strict_json_loads,
)


def _request() -> OracleRequest:
    return OracleRequest.create(
        run_id="run-test",
        problem_id="mock-problem",
        candidate_id="candidate-test",
        candidate={"x": 3},
        seed_lineage={"root_seed": 11, "oracle_seed": 12},
        budget_reservation={
            "expected_cost": 1.0,
            "cost_unit": "mock-evaluation-unit",
            "cost_source": "mock-v1",
            "oracle_calls": 1,
        },
    )


def _result(request: OracleRequest) -> OracleResult:
    return OracleResult.create(
        request_id=request.request_id,
        attempt_id="attempt-test",
        status=EvaluationStatus.SUCCEEDED,
        objective=2.0,
        constraints=None,
        feasible=None,
        failure=None,
        actual_cost={
            "amount": 1.0,
            "unit": "mock-evaluation-unit",
            "source": "mock-v1",
        },
        oracle_metadata={"network": "unused"},
    )


def test_contracts_are_strict_json_safe_and_round_trip() -> None:
    request = _request()
    result = _result(request)
    observation = Observation.from_result(request, result)

    assert OracleRequest.from_json(request.to_json()) == request
    assert OracleResult.from_json(result.to_json()) == result
    assert Observation.from_json(observation.to_json()) == observation
    assert re.fullmatch(r"request-[0-9a-f]{64}", request.request_id)
    assert re.fullmatch(r"result-[0-9a-f]{64}", result.result_id)
    assert re.fullmatch(r"observation-[0-9a-f]{64}", observation.observation_id)
    assert observation.constraints is None

    unknown = request.to_dict()
    unknown["unknown"] = True
    with pytest.raises(ValueError, match="schema mismatch"):
        OracleRequest.from_dict(unknown)


def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        strict_json_loads('{"x":1,"x":2}')
    for constant in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValueError, match="non-finite"):
            strict_json_loads(f'{{"x":{constant}}}')

    request = _request().to_dict()
    request["candidate"] = {"x": float("nan")}
    with pytest.raises(ValueError, match="non-finite"):
        OracleRequest.from_dict(request)


def test_stable_ids_ignore_mapping_order_and_seed_derivation_is_domain_separated() -> None:
    first = stable_id("fixture", {"a": 1, "b": [2, 3]})
    second = stable_id("fixture", {"b": [2, 3], "a": 1})

    assert first == second
    assert derive_seed(7, "oracle", 1) == derive_seed(7, "oracle", 1)
    assert derive_seed(7, "oracle", 1) != derive_seed(7, "candidate", 1)
    assert derive_seed(7, "oracle", 1) != derive_seed(8, "oracle", 1)
    json.dumps({"seed": derive_seed(7, "oracle", 1)}, allow_nan=False)


def test_failed_result_and_observation_cannot_fabricate_objective_or_penalty() -> None:
    request = _request()
    failed = OracleResult.create(
        request_id=request.request_id,
        attempt_id="attempt-failed",
        status=EvaluationStatus.FAILED,
        objective=None,
        constraints=None,
        feasible=None,
        failure={"type": "mock_failure", "message": "fixture"},
        actual_cost={
            "amount": 1.0,
            "unit": "mock-evaluation-unit",
            "source": "mock-v1",
        },
        oracle_metadata={},
    )
    observation = Observation.from_result(request, failed)
    assert observation.objective is None
    assert observation.constraints is None
    assert observation.feasible is None

    tampered = failed.to_dict()
    tampered["objective"] = 999.0
    with pytest.raises(ValueError, match="cannot fabricate"):
        OracleResult.from_dict(tampered)


@pytest.mark.parametrize("derived_id", ["reservation_id", "deduplication_key"])
def test_request_rejects_rehashed_but_inconsistent_derived_id(derived_id: str) -> None:
    request = _request().to_dict()
    request[derived_id] = stable_id("forged", {"value": 1})
    request["request_id"] = stable_id(
        "request",
        {
            key: value
            for key, value in request.items()
            if key not in {"request_id", "created_at_utc"}
        },
    )
    with pytest.raises(ValueError, match=derived_id):
        OracleRequest.from_dict(request)
