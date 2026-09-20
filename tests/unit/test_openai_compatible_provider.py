from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from decimal import Decimal
from typing import Any

import pytest

from roco_ebbo.core import BudgetExceededError, BudgetLedger, Candidate
from roco_ebbo.evolution import EoHOperator
from roco_ebbo.llm import (
    EOH_PROMPT_VERSION,
    PROMPT_VERSION,
    REQUEST_CONTRACT_VERSION,
    ROLE_TEMPERATURES,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    OpenAICompatibleProviderError,
    OpenAICompatibleRequest,
    OpenAICompatibleResponse,
    OpenAITransportError,
    PricingTable,
    ProviderErrorCode,
    RoCoRole,
    RoleRequest,
    TokenUsage,
    TransportErrorKind,
    prompt_for,
)

MODEL = "offline-test-model-v1"
TOKEN_CONTRACT = "offline-semantic-counter-v7"
INPUT_TOKENS = 17
OUTPUT_TOKENS = 5
CODE = "def heuristic(distance_matrix):\n    return list(range(len(distance_matrix)))\n"


class _ScriptedTransport:
    """A transport fake with no HTTP implementation or credential surface."""

    def __init__(self, *script: OpenAICompatibleResponse | Exception) -> None:
        self.script = deque(script)
        self.calls: list[tuple[OpenAICompatibleRequest, float]] = []

    def send(
        self,
        request: OpenAICompatibleRequest,
        *,
        timeout_seconds: float,
    ) -> OpenAICompatibleResponse:
        self.calls.append((request, timeout_seconds))
        if not self.script:
            raise AssertionError("fake transport received an unexpected call")
        result = self.script.popleft()
        if isinstance(result, Exception):
            raise result
        return result


class _FixedSemanticCounter:
    """A deliberately non-character-based model token counter."""

    contract_version = TOKEN_CONTRACT
    model_name = MODEL

    def __init__(self, value: int = INPUT_TOKENS) -> None:
        self.value = value
        self.calls: list[OpenAICompatibleRequest] = []

    def count_request(self, request: OpenAICompatibleRequest) -> int:
        self.calls.append(request)
        return self.value


class _OptionalFieldCounter:
    """Count semantic fields so context tests never equate characters with tokens."""

    contract_version = "offline-field-counter-v3"
    model_name = MODEL

    def __init__(self) -> None:
        self.calls: list[OpenAICompatibleRequest] = []

    def count_request(self, request: OpenAICompatibleRequest) -> int:
        self.calls.append(request)
        envelope = json.loads(request.messages[-1].content)
        optional_items = sum(item is not None for item in envelope.get("feedback", []))
        for candidate in envelope.get("candidates", envelope.get("parents", [])):
            optional_items += candidate.get("description") is not None
            optional_items += candidate.get("code") is not None
        return 8 + 7 * optional_items


def _candidate(*, description: str = "seed candidate") -> Candidate:
    return Candidate(
        id="seed-1",
        description=description,
        code=CODE,
        parents=(),
        operator="seed",
        generation=0,
        score=12.5,
        metadata={"evaluation": {"valid": True, "score": 12.5}},
    )


def _usage(input_tokens: int = INPUT_TOKENS, output_tokens: int = OUTPUT_TOKENS) -> dict[str, int]:
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _completion_payload(
    output: dict[str, Any] | str,
    *,
    input_tokens: int = INPUT_TOKENS,
    output_tokens: int = OUTPUT_TOKENS,
    request_id: str = "fake-request-1",
) -> dict[str, Any]:
    content = output if isinstance(output, str) else json.dumps(output, allow_nan=False)
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": 1_800_000_000,
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": _usage(input_tokens, output_tokens),
    }


def _completion(
    output: dict[str, Any] | str,
    *,
    input_tokens: int = INPUT_TOKENS,
    output_tokens: int = OUTPUT_TOKENS,
    request_id: str = "fake-request-1",
) -> OpenAICompatibleResponse:
    return OpenAICompatibleResponse(
        200,
        json.dumps(
            _completion_payload(
                output,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                request_id=request_id,
            ),
            allow_nan=False,
        ),
    )


def _http_error(
    status_code: int,
    *,
    input_tokens: int = INPUT_TOKENS,
    output_tokens: int = 2,
    message: str = "sanitized by the adapter",
) -> OpenAICompatibleResponse:
    return OpenAICompatibleResponse(
        status_code,
        json.dumps(
            {
                "error": {"message": message},
                "usage": _usage(input_tokens, output_tokens),
            }
        ),
        accepted=True,
    )


def _ledger(**overrides: Any) -> BudgetLedger:
    values: dict[str, Any] = {
        "max_llm_calls": 20,
        "max_tokens": 10_000,
        "max_generated_candidates": 20,
        "max_cost": 10.0,
    }
    values.update(overrides)
    return BudgetLedger(**values)


def _provider(
    *script: OpenAICompatibleResponse | Exception,
    counter: _FixedSemanticCounter | _OptionalFieldCounter | None = None,
    **config_overrides: Any,
) -> tuple[OpenAICompatibleProvider, _ScriptedTransport, Any]:
    config_values: dict[str, Any] = {
        "model_name": MODEL,
        "timeout_seconds": 2.75,
        "max_retries": 0,
        "max_output_tokens": 40,
        "context_window_tokens": 200,
        "eoh_temperature": 0.65,
    }
    config_values.update(config_overrides)
    transport = _ScriptedTransport(*script)
    resolved_counter = counter or _FixedSemanticCounter()
    provider = OpenAICompatibleProvider(
        config=OpenAICompatibleConfig(**config_values),
        transport=transport,
        token_counter=resolved_counter,
        pricing=PricingTable(
            version="offline-prices-2026-09-v1",
            currency="USD",
            input_per_million=Decimal("2"),
            output_per_million=Decimal("6"),
        ),
    )
    return provider, transport, resolved_counter


def _role_request(
    role: RoCoRole,
    *,
    action: str,
    target_branch: str,
    feedback: tuple[str, ...] = ("validated feedback",),
) -> RoleRequest:
    return RoleRequest(
        role=role,
        action=action,  # type: ignore[arg-type]
        generation=2,
        round_index=1,
        target_branch=target_branch,  # type: ignore[arg-type]
        prompt=prompt_for(role),
        temperature=ROLE_TEMPERATURES[role],
        candidates=(_candidate(),),
        feedback=feedback,
    )


def test_eoh_success_preserves_request_contract_usage_cost_and_audit() -> None:
    provider, transport, counter = _provider(
        _completion({"description": "offline result", "code": CODE})
    )
    ledger = _ledger()

    result = provider.generate(
        EoHOperator.E1,
        generation=0,
        parents=(),
        ledger=ledger,
    )

    assert result.description == "offline result"
    assert result.code == CODE
    assert result.request_index == 0
    assert len(transport.calls) == len(counter.calls) == 1
    request, timeout = transport.calls[0]
    request_dict = request.to_dict()
    envelope = json.loads(request.messages[1].content)
    assert timeout == 2.75
    assert request.model == MODEL
    assert request.temperature == 0.65
    assert request.max_output_tokens == 40
    assert len(request.messages[1].content) > INPUT_TOKENS
    assert envelope == {
        "contract_version": REQUEST_CONTRACT_VERSION,
        "generation": 0,
        "objective": "minimize",
        "operation": "eoh",
        "operator": "E1",
        "parents": [],
    }
    json_schema = request_dict["response_format"]["json_schema"]
    assert json_schema["strict"] is True
    assert json_schema["schema"]["required"] == ["description", "code"]
    assert json_schema["schema"]["additionalProperties"] is False
    assert request_dict["n"] == 1
    assert request_dict["stream"] is False

    expected_cost = (INPUT_TOKENS * 2 + OUTPUT_TOKENS * 6) / 1_000_000
    assert ledger.llm_calls == 1
    assert ledger.input_tokens == INPUT_TOKENS
    assert ledger.output_tokens == OUTPUT_TOKENS
    assert ledger.generated_candidates == 1
    assert ledger.cost == pytest.approx(expected_cost)

    assert len(provider.audits) == 1
    audit = provider.audits[0]
    assert audit.operation == "eoh:E1"
    assert audit.prompt_version == EOH_PROMPT_VERSION
    assert audit.provider_name == "openai-compatible"
    assert audit.adapter_contract_version == REQUEST_CONTRACT_VERSION
    assert audit.model_name == MODEL
    assert audit.pricing_version == "offline-prices-2026-09-v1"
    assert audit.token_counter_version == TOKEN_CONTRACT
    assert audit.usage == TokenUsage(INPUT_TOKENS, OUTPUT_TOKENS)
    assert audit.cost == pytest.approx(expected_cost)
    assert audit.status == "success"
    assert audit.accounting_complete is True
    assert audit.error_code is None
    assert audit.context.decision == "within_limit"
    assert audit.context.original_input_tokens == audit.context.final_input_tokens == INPUT_TOKENS
    assert re.fullmatch(r"[0-9a-f]{64}", audit.request_sha256)
    assert re.fullmatch(r"[0-9a-f]{64}", audit.response_sha256 or "")
    assert audit.provider_request_id_sha256 == hashlib.sha256(b"fake-request-1").hexdigest()


@pytest.mark.parametrize(
    ("role", "action", "target_branch", "output", "required", "candidate_count"),
    [
        (
            RoCoRole.EXPLORER,
            "propose",
            "explorer",
            {"description": "explore", "code": CODE},
            ["description", "code"],
            1,
        ),
        (
            RoCoRole.EXPLOITER,
            "propose",
            "exploiter",
            {"description": "exploit", "code": CODE},
            ["description", "code"],
            1,
        ),
        (
            RoCoRole.CRITIC,
            "compare",
            "both",
            {"feedback": "candidate one has the lower validated score"},
            ["feedback"],
            0,
        ),
        (
            RoCoRole.INTEGRATOR,
            "integrate",
            "both",
            {"description": "integrate", "code": CODE},
            ["description", "code"],
            1,
        ),
    ],
)
def test_four_roles_preserve_temperature_prompt_and_strict_output_contract(
    role: RoCoRole,
    action: str,
    target_branch: str,
    output: dict[str, str],
    required: list[str],
    candidate_count: int,
) -> None:
    provider, transport, _ = _provider(_completion(output))
    ledger = _ledger()
    request = _role_request(role, action=action, target_branch=target_branch)

    response = provider.generate_role(request, ledger)

    sent = transport.calls[0][0]
    envelope = json.loads(sent.messages[1].content)
    schema = sent.to_dict()["response_format"]["json_schema"]["schema"]
    assert sent.messages[0].content == prompt_for(role)
    assert sent.temperature == ROLE_TEMPERATURES[role]
    assert envelope["role"] == role.value
    assert envelope["action"] == action
    assert envelope["contract_version"] == REQUEST_CONTRACT_VERSION
    assert schema["required"] == required
    assert schema["additionalProperties"] is False
    assert ledger.llm_calls == 1
    assert ledger.generated_candidates == candidate_count
    assert response.metadata == {"provider_audit_index": 0}
    if role is RoCoRole.CRITIC:
        assert response.feedback == output["feedback"]
        assert response.candidate is None
    else:
        assert response.feedback is None
        assert response.candidate is not None
        assert response.candidate.description == output["description"]
        assert response.candidate.code == output["code"]
    audit = provider.audits[0]
    assert audit.role == role.value
    assert audit.temperature == ROLE_TEMPERATURES[role]
    assert audit.prompt_version == PROMPT_VERSION


@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        (TransportErrorKind.TIMEOUT, ProviderErrorCode.TIMEOUT),
        (TransportErrorKind.RETRYABLE, ProviderErrorCode.RETRYABLE_TRANSPORT),
    ],
)
def test_timeout_and_retryable_transport_stop_at_the_finite_retry_limit(
    kind: TransportErrorKind,
    expected_code: ProviderErrorCode,
) -> None:
    failures = tuple(
        OpenAITransportError(kind, accepted=False, request_id=f"attempt-{index}")
        for index in range(3)
    )
    provider, transport, _ = _provider(*failures, max_retries=2)
    ledger = _ledger()

    with pytest.raises(OpenAICompatibleProviderError) as caught:
        provider.generate(EoHOperator.E1, 0, (), ledger)

    assert caught.value.code is expected_code
    assert caught.value.attempts == 3
    assert caught.value.accepted is False
    assert caught.value.retryable is True
    assert len(transport.calls) == 3
    assert all(timeout == 2.75 for _, timeout in transport.calls)
    assert ledger.llm_calls == ledger.tokens == 0
    assert [audit.retry_scheduled for audit in provider.audits] == [True, True, False]
    assert [audit.error_code for audit in provider.audits] == [expected_code.value] * 3


def test_accepted_then_error_accounts_for_call_usage_and_cost() -> None:
    accepted_error = OpenAITransportError(
        TransportErrorKind.RETRYABLE,
        accepted=True,
        usage=TokenUsage(INPUT_TOKENS, 3),
        request_id="accepted-request",
    )
    provider, transport, _ = _provider(accepted_error)
    ledger = _ledger()

    with pytest.raises(OpenAICompatibleProviderError) as caught:
        provider.generate(EoHOperator.E1, 0, (), ledger)

    expected_cost = (INPUT_TOKENS * 2 + 3 * 6) / 1_000_000
    assert caught.value.code is ProviderErrorCode.RETRYABLE_TRANSPORT
    assert caught.value.accepted is True
    assert len(transport.calls) == 1
    assert ledger.llm_calls == 1
    assert ledger.input_tokens == INPUT_TOKENS
    assert ledger.output_tokens == 3
    assert ledger.generated_candidates == 0
    assert ledger.cost == pytest.approx(expected_cost)
    audit = provider.audits[0]
    assert audit.accepted is True
    assert audit.usage == TokenUsage(INPUT_TOKENS, 3)
    assert audit.cost == pytest.approx(expected_cost)


def test_2xx_provider_error_with_usage_is_fully_accounted_without_retry() -> None:
    response = OpenAICompatibleResponse(
        200,
        json.dumps(
            {
                "id": "fake-error-request",
                "error": {"message": "untrusted upstream detail"},
                "usage": _usage(output_tokens=3),
            }
        ),
    )
    provider, transport, _ = _provider(response, max_retries=2)
    ledger = _ledger()

    with pytest.raises(OpenAICompatibleProviderError) as caught:
        provider.generate(EoHOperator.E1, 0, (), ledger)

    expected_cost = (INPUT_TOKENS * 2 + 3 * 6) / 1_000_000
    assert caught.value.code is ProviderErrorCode.PROVIDER_ERROR
    assert caught.value.retryable is False
    assert len(transport.calls) == 1
    assert ledger.llm_calls == 1
    assert ledger.input_tokens == INPUT_TOKENS
    assert ledger.output_tokens == 3
    assert ledger.cost == pytest.approx(expected_cost)
    audit = provider.audits[0]
    assert audit.accounting_complete is True
    assert audit.usage == TokenUsage(INPUT_TOKENS, 3)
    assert audit.cost == pytest.approx(expected_cost)
    assert audit.provider_request_id_sha256 == hashlib.sha256(b"fake-error-request").hexdigest()


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (401, ProviderErrorCode.AUTH_PERMISSION, False),
        (403, ProviderErrorCode.AUTH_PERMISSION, False),
        (429, ProviderErrorCode.RATE_LIMIT, True),
        (500, ProviderErrorCode.PROVIDER_ERROR, True),
    ],
)
def test_http_failures_have_distinct_sanitized_classifications(
    status_code: int,
    expected_code: ProviderErrorCode,
    retryable: bool,
) -> None:
    provider, transport, _ = _provider(_http_error(status_code))
    ledger = _ledger()

    with pytest.raises(OpenAICompatibleProviderError) as caught:
        provider.generate(EoHOperator.E1, 0, (), ledger)

    assert caught.value.code is expected_code
    assert caught.value.retryable is retryable
    assert caught.value.accepted is True
    assert len(transport.calls) == 1
    assert ledger.llm_calls == 1
    assert ledger.input_tokens == INPUT_TOKENS
    assert ledger.output_tokens == 2
    assert provider.audits[0].error_code == expected_code.value


@pytest.mark.parametrize(
    "content",
    [
        "{",
        '{"description":"first","description":"second","code":"x"}',
        '{"description":NaN,"code":"x"}',
    ],
    ids=["invalid-json", "duplicate-key", "non-finite-json"],
)
def test_malformed_duplicate_and_nonfinite_content_fail_closed(content: str) -> None:
    provider, _, _ = _provider(_completion(content))
    ledger = _ledger()

    with pytest.raises(OpenAICompatibleProviderError) as caught:
        provider.generate(EoHOperator.E1, 0, (), ledger)

    assert caught.value.code is ProviderErrorCode.MALFORMED_JSON
    assert ledger.llm_calls == 1
    assert ledger.tokens == INPUT_TOKENS + OUTPUT_TOKENS
    assert ledger.generated_candidates == 0
    assert provider.audits[0].error_code == ProviderErrorCode.MALFORMED_JSON.value


def _schema_failure(case: str) -> OpenAICompatibleResponse:
    if case == "unknown-output":
        return _completion({"description": "candidate", "code": CODE, "unexpected": "value"})
    if case == "missing-output":
        return _completion({"description": "candidate"})
    payload = _completion_payload({"description": "candidate", "code": CODE})
    if case == "unknown-envelope":
        payload["unexpected"] = "value"
    elif case == "missing-envelope":
        del payload["choices"]
    else:
        raise AssertionError(f"unknown schema test case: {case}")
    return OpenAICompatibleResponse(200, json.dumps(payload))


@pytest.mark.parametrize(
    "case",
    ["unknown-output", "missing-output", "unknown-envelope", "missing-envelope"],
)
def test_unknown_and_missing_schema_fields_fail_closed_after_accounting(case: str) -> None:
    provider, _, _ = _provider(_schema_failure(case))
    ledger = _ledger()

    with pytest.raises(OpenAICompatibleProviderError) as caught:
        provider.generate(EoHOperator.E1, 0, (), ledger)

    assert caught.value.code is ProviderErrorCode.SCHEMA_ERROR
    assert ledger.llm_calls == 1
    assert ledger.tokens == INPUT_TOKENS + OUTPUT_TOKENS
    assert ledger.generated_candidates == 0
    assert provider.audits[0].usage == TokenUsage(INPUT_TOKENS, OUTPUT_TOKENS)


def _usage_failure(case: str) -> OpenAICompatibleResponse:
    payload = _completion_payload({"description": "candidate", "code": CODE})
    if case == "missing":
        del payload["usage"]
    elif case == "unknown":
        payload["usage"]["cached_tokens"] = 1
    elif case == "negative":
        payload["usage"] = _usage(-1, OUTPUT_TOKENS)
    elif case == "boolean":
        payload["usage"]["prompt_tokens"] = True
    elif case == "wrong-total":
        payload["usage"]["total_tokens"] += 1
    else:
        raise AssertionError(f"unknown usage test case: {case}")
    return OpenAICompatibleResponse(200, json.dumps(payload))


@pytest.mark.parametrize("case", ["missing", "unknown", "negative", "boolean", "wrong-total"])
def test_missing_and_invalid_usage_count_only_the_accepted_call(case: str) -> None:
    provider, _, _ = _provider(_usage_failure(case))
    ledger = _ledger()

    with pytest.raises(OpenAICompatibleProviderError) as caught:
        provider.generate(EoHOperator.E1, 0, (), ledger)

    assert caught.value.code is ProviderErrorCode.USAGE_ERROR
    assert caught.value.accepted is True
    assert ledger.llm_calls == 1
    assert ledger.tokens == 0
    assert ledger.generated_candidates == 0
    assert ledger.cost == 0.0
    audit = provider.audits[0]
    assert audit.usage is None
    assert audit.cost is None
    assert audit.accounting_complete is False
    assert audit.error_code == ProviderErrorCode.USAGE_ERROR.value


def test_missing_usage_closes_adapter_before_any_later_transport_attempt() -> None:
    provider, transport, counter = _provider(
        _usage_failure("missing"),
        _completion({"description": "must not be requested", "code": CODE}),
    )
    ledger = _ledger()

    with pytest.raises(OpenAICompatibleProviderError) as first:
        provider.generate(EoHOperator.E1, 0, (), ledger)
    with pytest.raises(OpenAICompatibleProviderError) as second:
        provider.generate(EoHOperator.E2, 0, (), ledger)

    assert first.value.code is ProviderErrorCode.USAGE_ERROR
    assert second.value.code is ProviderErrorCode.USAGE_ERROR
    assert second.value.attempts == 0
    assert len(transport.calls) == 1
    assert len(counter.calls) == 1
    assert ledger.llm_calls == 1


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, ProviderErrorCode.AUTH_PERMISSION),
        (429, ProviderErrorCode.RATE_LIMIT),
        (500, ProviderErrorCode.PROVIDER_ERROR),
    ],
)
def test_accepted_http_error_without_usage_keeps_category_but_disables_retry(
    status_code: int,
    expected_code: ProviderErrorCode,
) -> None:
    response = OpenAICompatibleResponse(
        status_code,
        json.dumps({"error": {"message": "untrusted upstream detail"}}),
        accepted=True,
    )
    provider, transport, _ = _provider(response, max_retries=2)
    ledger = _ledger()

    with pytest.raises(OpenAICompatibleProviderError) as caught:
        provider.generate(EoHOperator.E1, 0, (), ledger)

    assert caught.value.code is expected_code
    assert caught.value.retryable is False
    assert len(transport.calls) == 1
    assert ledger.llm_calls == 1
    assert ledger.tokens == 0
    assert provider.audits[0].error_code == expected_code.value
    assert provider.audits[0].accounting_complete is False
    assert provider.audits[0].retry_scheduled is False


def test_retry_stops_when_an_accepted_attempt_exactly_reaches_call_budget() -> None:
    failure = OpenAITransportError(
        TransportErrorKind.RETRYABLE,
        accepted=True,
        usage=TokenUsage(INPUT_TOKENS, 1),
    )
    provider, transport, _ = _provider(failure, failure, max_retries=2)
    ledger = _ledger(max_llm_calls=1)

    with pytest.raises(OpenAICompatibleProviderError) as caught:
        provider.generate(EoHOperator.E1, 0, (), ledger)

    assert caught.value.code is ProviderErrorCode.RETRYABLE_TRANSPORT
    assert len(transport.calls) == 1
    assert ledger.llm_calls == 1
    assert provider.audits[0].retry_scheduled is False


def test_invalid_accepted_error_usage_is_billed_then_closes_without_retry() -> None:
    failure = OpenAITransportError(
        TransportErrorKind.RETRYABLE,
        accepted=True,
        usage=TokenUsage(INPUT_TOKENS + 1, 1),
    )
    provider, transport, _ = _provider(failure, max_retries=2)
    ledger = _ledger()

    with pytest.raises(OpenAICompatibleProviderError) as caught:
        provider.generate(EoHOperator.E1, 0, (), ledger)

    assert caught.value.code is ProviderErrorCode.USAGE_ERROR
    assert len(transport.calls) == 1
    assert ledger.llm_calls == 1
    assert ledger.input_tokens == INPUT_TOKENS + 1
    assert provider.audits[0].accounting_complete is False
    assert provider.audits[0].retry_scheduled is False


def test_outer_duplicate_and_nan_are_malformed_without_inventing_usage() -> None:
    duplicate = (
        '{"usage":{"prompt_tokens":17,"completion_tokens":5,"total_tokens":22},'
        '"usage":{"prompt_tokens":17,"completion_tokens":5,"total_tokens":22}}'
    )
    nonfinite = (
        '{"id":"fake","object":"chat.completion","created":0,'
        f'"model":"{MODEL}","choices":[],"usage":NaN}}'
    )
    for body in (duplicate, nonfinite):
        provider, _, _ = _provider(OpenAICompatibleResponse(200, body))
        ledger = _ledger()

        with pytest.raises(OpenAICompatibleProviderError) as caught:
            provider.generate(EoHOperator.E1, 0, (), ledger)

        assert caught.value.code is ProviderErrorCode.MALFORMED_JSON
        assert ledger.llm_calls == 1
        assert ledger.tokens == 0
        assert provider.audits[0].usage is None


def test_boolean_choice_index_and_unpaired_surrogate_are_rejected_safely() -> None:
    payload = _completion_payload({"description": "candidate", "code": CODE})
    payload["choices"][0]["index"] = False
    provider, _, _ = _provider(OpenAICompatibleResponse(200, json.dumps(payload)))
    ledger = _ledger()
    with pytest.raises(OpenAICompatibleProviderError) as boolean_error:
        provider.generate(EoHOperator.E1, 0, (), ledger)
    assert boolean_error.value.code is ProviderErrorCode.SCHEMA_ERROR
    assert ledger.tokens == INPUT_TOKENS + OUTPUT_TOKENS

    surrogate, _, _ = _provider(OpenAICompatibleResponse(200, "\ud800"))
    surrogate_ledger = _ledger()
    with pytest.raises(OpenAICompatibleProviderError) as surrogate_error:
        surrogate.generate(EoHOperator.E1, 0, (), surrogate_ledger)
    assert surrogate_error.value.code is ProviderErrorCode.MALFORMED_JSON
    assert surrogate_ledger.llm_calls == 1
    assert surrogate.audits[0].response_sha256 is not None


def test_budget_preflight_blocks_transport_before_external_acceptance() -> None:
    provider, transport, _ = _provider(_completion({"description": "not sent", "code": CODE}))
    # The adapter reserves 17 input + 40 maximum output tokens before sending.
    ledger = _ledger(max_tokens=56)

    with pytest.raises(BudgetExceededError, match="would exceed"):
        provider.generate(EoHOperator.E1, 0, (), ledger)

    assert transport.calls == []
    assert provider.audits == ()
    assert ledger.llm_calls == ledger.tokens == ledger.generated_candidates == 0


def test_accepted_usage_overrun_is_recorded_then_fails_closed() -> None:
    provider, transport, _ = _provider(
        _completion(
            {"description": "must not escape", "code": CODE},
            output_tokens=6,
        ),
        max_output_tokens=5,
    )
    # Preflight reservation is exactly 17 + 5, but the fake reports 17 + 6.
    ledger = _ledger(max_tokens=22)

    with pytest.raises(BudgetExceededError, match="accepted provider usage"):
        provider.generate(EoHOperator.E1, 0, (), ledger)

    assert len(transport.calls) == 1
    assert ledger.llm_calls == 1
    assert ledger.input_tokens == INPUT_TOKENS
    assert ledger.output_tokens == 6
    assert ledger.tokens == 23
    assert ledger.generated_candidates == 0
    assert ledger.exceeded_limits == ("tokens",)
    audit = provider.audits[0]
    assert audit.status == "error"
    assert audit.error_code == ProviderErrorCode.BUDGET_EXCEEDED.value
    assert audit.usage == TokenUsage(INPUT_TOKENS, 6)


def test_context_overflow_drops_audited_optional_fields_in_deterministic_order() -> None:
    counter = _OptionalFieldCounter()
    provider, transport, _ = _provider(
        _completion(
            {"description": "bounded candidate", "code": CODE},
            input_tokens=15,
        ),
        counter=counter,
        max_output_tokens=10,
        context_window_tokens=30,
    )
    request = _role_request(
        RoCoRole.EXPLORER,
        action="propose",
        target_branch="explorer",
        feedback=("oldest optional feedback",),
    )

    response = provider.generate_role(request, _ledger())

    assert response.candidate is not None
    assert len(counter.calls) == 3
    assert len(transport.calls) == 1
    sent_envelope = json.loads(transport.calls[0][0].messages[1].content)
    assert sent_envelope["feedback"] == [None]
    assert sent_envelope["candidates"][0]["description"] is None
    assert sent_envelope["candidates"][0]["code"] == CODE
    context = provider.audits[0].context
    assert context.token_counter_version == "offline-field-counter-v3"
    assert context.original_input_tokens == 29
    assert context.final_input_tokens == 15
    assert context.dropped_fields == ("feedback:0", "candidate:0:description")
    assert context.decision == "truncated"


def test_irreducible_context_is_rejected_with_audit_and_without_transport() -> None:
    counter = _FixedSemanticCounter(value=21)
    provider, transport, _ = _provider(
        counter=counter,
        max_output_tokens=10,
        context_window_tokens=30,
    )
    ledger = _ledger()

    with pytest.raises(OpenAICompatibleProviderError) as caught:
        provider.generate(EoHOperator.E1, 0, (), ledger)

    assert caught.value.code is ProviderErrorCode.CONTEXT_LENGTH
    assert caught.value.attempts == 0
    assert caught.value.accepted is False
    assert transport.calls == []
    assert ledger.llm_calls == ledger.tokens == 0
    assert len(provider.audits) == 1
    audit = provider.audits[0]
    assert audit.attempt == 0
    assert audit.error_code == ProviderErrorCode.CONTEXT_LENGTH.value
    assert audit.context.decision == "rejected"
    assert audit.context.original_input_tokens == audit.context.final_input_tokens == 21


def test_secret_bearing_request_response_exception_and_audit_are_not_echoed(caplog: Any) -> None:
    secret = "sk-offline-sentinel-never-log"
    provider, transport, _ = _provider(_http_error(500, message=f"Authorization: Bearer {secret}"))
    request = _role_request(
        RoCoRole.EXPLORER,
        action="propose",
        target_branch="explorer",
        feedback=(f"OPENAI_API_KEY={secret}",),
    )

    with pytest.raises(OpenAICompatibleProviderError) as caught:
        provider.generate_role(request, _ledger())

    assert secret in transport.calls[0][0].messages[1].content
    public_surfaces = "\n".join(
        [
            str(caught.value),
            repr(caught.value),
            json.dumps(caught.value.to_dict(), sort_keys=True),
            provider.audits[0].to_json(),
            repr(provider.audits),
            caplog.text,
        ]
    )
    assert secret not in public_surfaces
    assert "Authorization" not in public_surfaces
    assert provider.audits[0].response_sha256 is not None

    generic, _, _ = _provider(RuntimeError(f"raw transport leaked {secret}"))
    with pytest.raises(OpenAICompatibleProviderError) as generic_error:
        generic.generate(EoHOperator.E1, 0, (), _ledger())
    assert generic_error.value.code is ProviderErrorCode.PROVIDER_ERROR
    assert secret not in str(generic_error.value)
    assert secret not in repr(generic_error.value)
    assert secret not in generic.audits[0].to_json()


def test_secret_bearing_candidate_output_is_rejected_and_never_returned() -> None:
    secret = "sk-output-sentinel"
    provider, _, _ = _provider(
        _completion(
            {
                "description": f"OPENAI_API_KEY={secret}",
                "code": CODE,
            }
        )
    )

    with pytest.raises(OpenAICompatibleProviderError) as caught:
        provider.generate(EoHOperator.E1, 0, (), _ledger())

    assert caught.value.code is ProviderErrorCode.SCHEMA_ERROR
    surfaces = f"{caught.value!s}\n{caught.value!r}\n{provider.audits[0].to_json()}"
    assert secret not in surfaces


def test_stage4_memory_action_is_outside_this_adapter_boundary() -> None:
    provider, transport, _ = _provider()
    request = _role_request(
        RoCoRole.EXPLORER,
        action="memory_mutation",
        target_branch="explorer",
    )

    with pytest.raises(ValueError, match="incompatible"):
        provider.generate_role(request, _ledger())

    assert transport.calls == []


def test_construction_is_inert_and_performs_no_transport_or_tokenizer_call() -> None:
    provider, transport, counter = _provider()

    assert transport.calls == []
    assert counter.calls == []
    assert provider.audits == ()
