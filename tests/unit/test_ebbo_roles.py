"""P9b role permissions, audited fallback, and unique dispatch capability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from roco_ebbo.ebbo import (
    CandidatePool,
    DuplicateDispatchError,
    EBBOLedger,
    MockExpensiveOracle,
    MockSearchSpace,
    NearestObservationSurrogate,
    ObservationStore,
    SerialScheduler,
    build_candidate_pool,
)
from roco_ebbo.ebbo.contracts import canonical_json
from roco_ebbo.ebbo.ledger import EBBOBudgetExceeded
from roco_ebbo.ebbo.role_scheduler import RestrictedRoleScheduler
from roco_ebbo.ebbo.roles import (
    DeterministicFakeRoleProvider,
    RoleContractError,
    RoleController,
    RoleDecision,
    RoleKind,
    RoleRequest,
    RoleResponse,
    mock_token_count,
)


def _setup(
    tmp_path: Path, *, calls: int = 5, role_calls: int = 20
) -> tuple[CandidatePool, EBBOLedger, ObservationStore, SerialScheduler]:
    space = MockSearchSpace(-5, 5)
    ledger = EBBOLedger(
        calls,
        20,
        5.0,
        "mock-evaluation-unit",
        max_role_calls=role_calls,
        max_role_tokens=50000,
    )
    store = ObservationStore(tmp_path)
    scheduler = SerialScheduler(
        oracle=MockExpensiveOracle(space),
        ledger=ledger,
        store=store,
        run_id="role-test",
        root_seed=9061,
    )
    pool = build_candidate_pool(
        search_space=space,
        surrogate=NearestObservationSurrogate(space, 10.0),
        root_seed=9061,
        iteration=0,
        pool_size=4,
        beta=2.0,
        excluded_candidate_ids=set(),
        ledger=ledger,
    )
    return pool, ledger, store, scheduler


def _request(pool: CandidatePool, role: RoleKind) -> RoleRequest:
    return RoleRequest.create(
        role=role,
        pool=pool,
        iteration=0,
        root_seed=9061,
        observation_ids=(),
        remaining_oracle_calls=5,
    )


def test_role_request_and_response_are_strict_replayable_and_pool_bounded(
    tmp_path: Path,
) -> None:
    pool, _, _, _ = _setup(tmp_path)
    request = _request(pool, RoleKind.GLOBAL_EXPLORER)
    assert RoleRequest.from_json(json.dumps(request.to_dict())) == request
    assert RoleRequest.from_json(json.dumps(request.to_dict())).request_id == request.request_id
    assert request.entries[0]["entry_id"] == pool.entries[0].candidate_id
    assert "candidate" not in request.to_dict()
    with pytest.raises(TypeError):
        request.entries[0]["entry_id"] = "forged"  # type: ignore[index]
    detached = request.to_dict()
    detached_entries = detached["entries"]
    assert isinstance(detached_entries, list)
    assert isinstance(detached_entries[0], dict)
    detached_entries[0]["entry_id"] = "forged"
    assert request.entries[0]["entry_id"] == pool.entries[0].candidate_id
    response = RoleResponse.from_json(DeterministicFakeRoleProvider().respond(request), request)
    assert response.pool_id == pool.pool_id

    unknown = request.to_dict()
    unknown["extra"] = 1
    with pytest.raises(RoleContractError, match="role_request_schema"):
        RoleRequest.from_json(json.dumps(unknown))
    with pytest.raises(ValueError, match="duplicate JSON key"):
        RoleRequest.from_json('{"schema_version":1,"schema_version":2}')
    with pytest.raises(ValueError, match="non-finite"):
        RoleResponse.from_json('{"weight":NaN}', request)

    malformed_region = request.to_dict()
    entries = malformed_region["entries"]
    assert isinstance(entries, list)
    assert isinstance(entries[0], dict)
    entries[0]["region_id"] = []
    with pytest.raises(RoleContractError, match="region_id"):
        RoleRequest.from_dict(malformed_region)

    critic = _request(pool, RoleKind.MODEL_CRITIC)
    malformed_risk = json.loads(DeterministicFakeRoleProvider().respond(critic))
    malformed_risk["payload"]["reviews"][0]["constraint_risk"] = []
    with pytest.raises(RoleContractError, match="risk_level"):
        RoleResponse.from_dict(malformed_risk, critic)


@pytest.mark.parametrize(
    ("role", "payload", "reason"),
    [
        (RoleKind.GLOBAL_EXPLORER, {"candidate": {"x": 2}}, "preference_schema"),
        (
            RoleKind.GLOBAL_EXPLORER,
            {
                "entry_id": "not-in-pool",
                "region_id": "positive",
                "strategy_id": "ebbo-lower-confidence-bound-v1",
                "weight": 1.0,
            },
            "unknown_pool_entry",
        ),
        (
            RoleKind.GLOBAL_EXPLORER,
            {
                "entry_id": "PLACEHOLDER",
                "region_id": "PLACEHOLDER",
                "strategy_id": "PLACEHOLDER",
                "weight": float("inf"),
            },
            "non-finite",
        ),
        (RoleKind.MODEL_CRITIC, {"veto": True, "acquisition_score": 1}, "critic_schema"),
        (
            RoleKind.RESOURCE_INTEGRATOR,
            {
                "ordered_entry_ids": ["PLACEHOLDER", "PLACEHOLDER"],
                "selected_entry_id": "PLACEHOLDER",
            },
            "duplicate_selection",
        ),
        (
            RoleKind.RESOURCE_INTEGRATOR,
            {
                "ordered_entry_ids": ["not-in-pool"],
                "selected_entry_id": "not-in-pool",
            },
            "unknown_pool_entry",
        ),
    ],
)
def test_roles_reject_unauthorized_fields_ids_duplicates_and_weights(
    tmp_path: Path,
    role: RoleKind,
    payload: dict[str, Any],
    reason: str,
) -> None:
    pool, _, _, _ = _setup(tmp_path)
    request = _request(pool, role)
    first = request.entries[0]
    payload = {
        key: (
            first["entry_id"]
            if value == "PLACEHOLDER" and key != "region_id"
            else first["region_id"]
            if value == "PLACEHOLDER"
            else [first["entry_id"], first["entry_id"]]
            if key == "ordered_entry_ids" and value == ["PLACEHOLDER", "PLACEHOLDER"]
            else value
        )
        for key, value in payload.items()
    }
    if (
        role is RoleKind.GLOBAL_EXPLORER
        and "weight" in payload
        and payload["weight"] == float("inf")
    ):
        payload["strategy_id"] = first["strategy_id"]
    raw = {
        "schema_version": "ebbo-role-response-v1",
        "response_id": "untrusted",
        "request_id": request.request_id,
        "role": role.value,
        "pool_id": pool.pool_id,
        "payload": payload,
    }
    with pytest.raises(ValueError, match=reason):
        RoleResponse.from_dict(raw, request)


class FaultProvider:
    def __init__(self, fault: str) -> None:
        self.fault = fault
        self.delegate = DeterministicFakeRoleProvider()

    def respond(self, request: RoleRequest) -> str:
        if self.fault == "timeout":
            raise TimeoutError("local scripted timeout")
        if self.fault == "error":
            raise RuntimeError("local scripted error")
        if self.fault == "invalid_json":
            return '{"x":'
        valid = json.loads(self.delegate.respond(request))
        if self.fault == "unknown_field":
            valid["payload"]["candidate"] = {"x": 2}
        elif self.fault == "unknown_pool":
            valid["pool_id"] = "wrong"
        elif self.fault == "duplicate_json_key":
            return '{"role":1,"role":2}'
        elif self.fault == "non_finite_weight":
            valid["payload"]["weight"] = float("inf")
            return json.dumps(valid)
        return json.dumps(valid)


@pytest.mark.parametrize(
    "fault",
    [
        "timeout",
        "error",
        "invalid_json",
        "unknown_field",
        "unknown_pool",
        "duplicate_json_key",
        "non_finite_weight",
    ],
)
def test_role_faults_audit_and_fallback_without_oracle_call(
    tmp_path: Path,
    fault: str,
) -> None:
    pool, ledger, store, _ = _setup(tmp_path)
    controller = RoleController(
        provider=FaultProvider(fault),
        ledger=ledger,
        store=store,
        root_seed=9061,
    )
    decision = controller.choose(pool, iteration=0, mode="full")
    assert decision.selected_entry_id == pool.selected.candidate_id
    assert decision.source == "acquisition_fallback"
    assert ledger.oracle_calls == 0
    assert ledger.llm_calls == 1
    assert ledger.tokens > 0
    with pytest.raises(ValueError, match="unique accepted role call"):
        ledger.settle_role_call(1)
    assert any(event.kind == "role_failure" for event in store.events)
    assert store.events[-1].kind == "role_decision"
    assert all(
        event.payload["role_audit_version"] == "ebbo-role-audit-v1" for event in store.events
    )


def test_role_call_budget_exhaustion_audits_without_oracle_or_fake_call(
    tmp_path: Path,
) -> None:
    pool, ledger, store, _ = _setup(tmp_path, role_calls=0)
    decision = RoleController(
        provider=DeterministicFakeRoleProvider(),
        ledger=ledger,
        store=store,
        root_seed=9061,
    ).choose(pool, iteration=0, mode="full")
    assert decision.source == "acquisition_fallback"
    assert ledger.oracle_calls == ledger.llm_calls == ledger.tokens == 0
    assert store.events[1].payload["reason"] == "role_budget_exhausted"


class VetoProvider:
    def __init__(self, *, all_entries: bool) -> None:
        self.all_entries = all_entries
        self.delegate = DeterministicFakeRoleProvider()

    def respond(self, request: RoleRequest) -> str:
        if request.role is not RoleKind.MODEL_CRITIC:
            return self.delegate.respond(request)
        original = RoleResponse.from_json(self.delegate.respond(request), request)
        reviews = original.payload["reviews"]
        assert isinstance(reviews, list)
        changed = [
            {**review, "veto": self.all_entries or index == 0}
            for index, review in enumerate(reviews)
        ]
        return json.dumps(RoleResponse.create(request, {"reviews": changed}).to_dict())


def test_configured_hard_veto_excludes_and_all_veto_stops_dispatch(
    tmp_path: Path,
) -> None:
    pool, ledger, store, scheduler = _setup(tmp_path / "hard")
    decision = RoleController(
        provider=VetoProvider(all_entries=False),
        ledger=ledger,
        store=store,
        root_seed=9061,
        veto_mode="hard",
    ).choose(pool, iteration=0, mode="full")
    assert pool.entries[0].candidate_id in decision.vetoed_ids
    assert decision.selected_entry_id not in decision.vetoed_ids
    RestrictedRoleScheduler(scheduler).dispatch(pool, decision)
    assert ledger.oracle_calls == 1

    pool, ledger, store, _ = _setup(tmp_path / "all")
    decision = RoleController(
        provider=VetoProvider(all_entries=True),
        ledger=ledger,
        store=store,
        root_seed=9061,
        veto_mode="hard",
    ).choose(pool, iteration=0, mode="full")
    assert decision.selected_entry_id is None
    assert decision.source == "hard_veto_all"
    assert ledger.oracle_calls == 0

    pool, ledger, store, _ = _setup(tmp_path / "advisory")
    decision = RoleController(
        provider=VetoProvider(all_entries=True),
        ledger=ledger,
        store=store,
        root_seed=9061,
        veto_mode="advisory",
    ).choose(pool, iteration=0, mode="full")
    assert not decision.vetoed_ids
    assert decision.selected_entry_id is not None


def test_restricted_scheduler_rechecks_membership_duplicate_constraints_and_budget(
    tmp_path: Path,
) -> None:
    pool, ledger, store, serial = _setup(tmp_path / "gate")
    gate = RestrictedRoleScheduler(serial)
    with pytest.raises(ValueError, match="current finite pool"):
        gate.dispatch(pool, RoleDecision("unknown", "integrator", ()))
    assert ledger.oracle_calls == 0
    assert store.events[-1].kind == "role_dispatch_rejected"
    chosen = RoleDecision(pool.selected.candidate_id, "integrator", ())
    gate.dispatch(pool, chosen)
    with pytest.raises(DuplicateDispatchError):
        gate.dispatch(pool, chosen)
    assert ledger.oracle_calls == 1

    pool, ledger, _, serial = _setup(tmp_path / "budget", calls=0)
    with pytest.raises(EBBOBudgetExceeded):
        RestrictedRoleScheduler(serial).dispatch(
            pool, RoleDecision(pool.selected.candidate_id, "integrator", ())
        )
    assert ledger.oracle_calls == 0

    pool, ledger, _, serial = _setup(tmp_path / "forged")
    forged = CandidatePool(
        pool_id=pool.pool_id,
        entries=tuple(reversed(pool.entries)),
        proposals_received=pool.proposals_received,
        duplicates_removed=pool.duplicates_removed,
    )
    with pytest.raises(ValueError):
        RestrictedRoleScheduler(serial).dispatch(
            forged, RoleDecision(pool.selected.candidate_id, "integrator", ())
        )
    assert ledger.oracle_calls == 0


def test_role_token_ceiling_is_audited_and_does_not_consume_oracle(
    tmp_path: Path,
) -> None:
    pool, ledger, store, _ = _setup(tmp_path)
    request = _request(pool, RoleKind.GLOBAL_EXPLORER)
    ledger.max_role_tokens = mock_token_count(canonical_json(request.to_dict()))
    decision = RoleController(
        provider=DeterministicFakeRoleProvider(),
        ledger=ledger,
        store=store,
        root_seed=9061,
    ).choose(pool, iteration=0, mode="full")
    assert decision.source == "acquisition_fallback"
    assert ledger.llm_calls == 1
    assert ledger.oracle_calls == 0
    assert ledger.tokens > ledger.max_role_tokens
    assert any(
        event.kind == "role_failure" and event.payload["reason"] == "role_token_budget_exceeded"
        for event in store.events
    )


class DuplicateIntegratorProvider:
    def respond(self, request: RoleRequest) -> str:
        valid = DeterministicFakeRoleProvider().respond(request)
        if request.role is not RoleKind.RESOURCE_INTEGRATOR:
            return valid
        raw = json.loads(valid)
        selected = request.entries[0]["entry_id"]
        raw["payload"] = {
            "ordered_entry_ids": [selected, selected],
            "selected_entry_id": selected,
        }
        return json.dumps(raw)


def test_integrator_duplicate_selection_falls_back_and_preserves_oracle_budget(
    tmp_path: Path,
) -> None:
    pool, ledger, store, _ = _setup(tmp_path)
    decision = RoleController(
        provider=DuplicateIntegratorProvider(),
        ledger=ledger,
        store=store,
        root_seed=9061,
    ).choose(pool, iteration=0, mode="full")
    assert decision.source == "acquisition_fallback"
    assert decision.selected_entry_id == pool.selected.candidate_id
    assert ledger.llm_calls == 4
    assert ledger.oracle_calls == 0
    assert any(
        event.kind == "role_failure" and event.payload["reason"] == "duplicate_selection"
        for event in store.events
    )
