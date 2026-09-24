"""Strict, offline P9b role protocol and restricted candidate-pool control."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, cast

from roco_ebbo.ebbo.baseline import ACQUISITION_VERSION, CandidatePool
from roco_ebbo.ebbo.contracts import (
    JsonValue,
    canonical_json,
    derive_seed,
    require_json_safe,
    stable_id,
    strict_json_loads,
)
from roco_ebbo.ebbo.ledger import EBBOLedger
from roco_ebbo.ebbo.store import AuditEvent, ObservationStore

ROLE_REQUEST_VERSION = "ebbo-role-request-v1"
ROLE_RESPONSE_VERSION = "ebbo-role-response-v1"
ROLE_CONTROL_VERSION = "ebbo-restricted-role-control-v1"
ROLE_PROVIDER_VERSION = "ebbo-deterministic-fake-role-provider-v1"
ROLE_AUDIT_VERSION = "ebbo-role-audit-v1"
RISK_LEVELS = frozenset({"low", "medium", "high"})


class RoleKind(StrEnum):
    GLOBAL_EXPLORER = "global_explorer"
    LOCAL_EXPLOITER = "local_exploiter"
    MODEL_CRITIC = "model_critic"
    RESOURCE_INTEGRATOR = "resource_integrator"


class RoleContractError(ValueError):
    """A role attempted an invalid or unauthorized protocol action."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _exact(value: Any, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise RoleContractError(f"{name}_schema")
    require_json_safe(value)
    return value


def _region(x: int) -> str:
    return "negative" if x < 0 else ("positive" if x > 0 else "zero")


def mock_token_count(value: str) -> int:
    """Synthetic character-derived accounting; never a billing token count."""
    return (len(value.encode("utf-8")) + 3) // 4


@dataclass(frozen=True, slots=True)
class RoleRequest:
    request_id: str
    role: RoleKind
    pool_id: str
    iteration: int
    role_seed: int
    entries: tuple[Mapping[str, JsonValue], ...]
    observation_ids: tuple[str, ...]
    posterior_id: str
    guidance_ids: tuple[str, ...]
    vetoed_ids: tuple[str, ...]
    remaining_oracle_calls: int

    @classmethod
    def create(
        cls,
        *,
        role: RoleKind,
        pool: CandidatePool,
        iteration: int,
        root_seed: int,
        observation_ids: tuple[str, ...],
        guidance_ids: tuple[str, ...] = (),
        vetoed_ids: tuple[str, ...] = (),
        remaining_oracle_calls: int,
    ) -> RoleRequest:
        entries: tuple[dict[str, JsonValue], ...] = tuple(
            {
                "entry_id": entry.candidate_id,
                "region_id": _region(cast(int, entry.candidate["x"])),
                "strategy_id": ACQUISITION_VERSION,
                "predicted_mean": entry.predicted_mean,
                "uncertainty": entry.uncertainty,
                "acquisition_score": entry.acquisition_score,
            }
            for entry in pool.entries
        )
        fields: dict[str, JsonValue] = {
            "schema_version": ROLE_REQUEST_VERSION,
            "role": role.value,
            "pool_id": pool.pool_id,
            "iteration": iteration,
            "role_seed": derive_seed(root_seed, "ebbo-role", iteration, role.value),
            "entries": list(entries),
            "observation_ids": list(observation_ids),
            "posterior_id": stable_id("posterior-view", list(observation_ids)),
            "guidance_ids": list(guidance_ids),
            "vetoed_ids": list(vetoed_ids),
            "remaining_oracle_calls": remaining_oracle_calls,
        }
        return cls.from_dict({**fields, "request_id": stable_id("role-request", fields)})

    @classmethod
    def from_json(cls, raw: str | bytes) -> RoleRequest:
        return cls.from_dict(strict_json_loads(raw))

    @classmethod
    def from_dict(cls, raw: Any) -> RoleRequest:
        data = _exact(
            raw,
            {
                "schema_version",
                "request_id",
                "role",
                "pool_id",
                "iteration",
                "role_seed",
                "entries",
                "observation_ids",
                "posterior_id",
                "guidance_ids",
                "vetoed_ids",
                "remaining_oracle_calls",
            },
            "role_request",
        )
        if data["schema_version"] != ROLE_REQUEST_VERSION:
            raise RoleContractError("request_version")
        try:
            role = RoleKind(data["role"])
        except (ValueError, TypeError) as exc:
            raise RoleContractError("unknown_role") from exc
        if not isinstance(data["pool_id"], str) or not data["pool_id"]:
            raise RoleContractError("pool_id")
        for name in ("iteration", "role_seed", "remaining_oracle_calls"):
            if type(data[name]) is not int or data[name] < 0:
                raise RoleContractError(name)
        entries = data["entries"]
        if not isinstance(entries, list) or not entries:
            raise RoleContractError("entries")
        entry_ids: list[str] = []
        for entry in entries:
            item = _exact(
                entry,
                {
                    "entry_id",
                    "region_id",
                    "strategy_id",
                    "predicted_mean",
                    "uncertainty",
                    "acquisition_score",
                },
                "entry",
            )
            if not isinstance(item["entry_id"], str) or not item["entry_id"]:
                raise RoleContractError("entry_id")
            if not isinstance(item["region_id"], str) or item["region_id"] not in {
                "negative",
                "zero",
                "positive",
            }:
                raise RoleContractError("region_id")
            if item["strategy_id"] != ACQUISITION_VERSION:
                raise RoleContractError("strategy_id")
            for name in ("predicted_mean", "uncertainty", "acquisition_score"):
                if type(item[name]) not in (int, float) or not math.isfinite(item[name]):
                    raise RoleContractError(name)
            entry_ids.append(item["entry_id"])
        if len(set(entry_ids)) != len(entry_ids):
            raise RoleContractError("duplicate_entry")
        for name in ("observation_ids", "guidance_ids", "vetoed_ids"):
            ids = data[name]
            if not isinstance(ids, list) or any(not isinstance(x, str) or not x for x in ids):
                raise RoleContractError(name)
            if len(set(ids)) != len(ids):
                raise RoleContractError(f"duplicate_{name}")
        if any(x not in entry_ids for x in [*data["guidance_ids"], *data["vetoed_ids"]]):
            raise RoleContractError("unknown_pool_entry")
        if data["posterior_id"] != stable_id("posterior-view", data["observation_ids"]):
            raise RoleContractError("posterior_id")
        content = {key: value for key, value in data.items() if key != "request_id"}
        if data["request_id"] != stable_id("role-request", content):
            raise RoleContractError("request_id")
        return cls(
            request_id=data["request_id"],
            role=role,
            pool_id=data["pool_id"],
            iteration=data["iteration"],
            role_seed=data["role_seed"],
            entries=tuple(MappingProxyType(dict(entry)) for entry in entries),
            observation_ids=tuple(data["observation_ids"]),
            posterior_id=data["posterior_id"],
            guidance_ids=tuple(data["guidance_ids"]),
            vetoed_ids=tuple(data["vetoed_ids"]),
            remaining_oracle_calls=data["remaining_oracle_calls"],
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": ROLE_REQUEST_VERSION,
            "request_id": self.request_id,
            "role": self.role.value,
            "pool_id": self.pool_id,
            "iteration": self.iteration,
            "role_seed": self.role_seed,
            "entries": [dict(entry) for entry in self.entries],
            "observation_ids": list(self.observation_ids),
            "posterior_id": self.posterior_id,
            "guidance_ids": list(self.guidance_ids),
            "vetoed_ids": list(self.vetoed_ids),
            "remaining_oracle_calls": self.remaining_oracle_calls,
        }


@dataclass(frozen=True, slots=True)
class RoleResponse:
    response_id: str
    request_id: str
    role: RoleKind
    pool_id: str
    payload: dict[str, JsonValue]

    @classmethod
    def create(cls, request: RoleRequest, payload: dict[str, JsonValue]) -> RoleResponse:
        fields: dict[str, JsonValue] = {
            "schema_version": ROLE_RESPONSE_VERSION,
            "request_id": request.request_id,
            "role": request.role.value,
            "pool_id": request.pool_id,
            "payload": payload,
        }
        return cls.from_dict({**fields, "response_id": stable_id("role-response", fields)}, request)

    @classmethod
    def from_json(cls, raw: str | bytes, request: RoleRequest) -> RoleResponse:
        return cls.from_dict(strict_json_loads(raw), request)

    @classmethod
    def from_dict(cls, raw: Any, request: RoleRequest) -> RoleResponse:
        data = _exact(
            raw,
            {"schema_version", "response_id", "request_id", "role", "pool_id", "payload"},
            "role_response",
        )
        if data["schema_version"] != ROLE_RESPONSE_VERSION:
            raise RoleContractError("response_version")
        if data["request_id"] != request.request_id or data["role"] != request.role.value:
            raise RoleContractError("response_identity")
        if data["pool_id"] != request.pool_id:
            raise RoleContractError("unknown_pool_id")
        payload = data["payload"]
        ids = {entry["entry_id"] for entry in request.entries}
        if request.role in {RoleKind.GLOBAL_EXPLORER, RoleKind.LOCAL_EXPLOITER}:
            item = _exact(payload, {"entry_id", "region_id", "strategy_id", "weight"}, "preference")
            match = next((e for e in request.entries if e["entry_id"] == item["entry_id"]), None)
            if match is None:
                raise RoleContractError("unknown_pool_entry")
            if (
                item["region_id"] != match["region_id"]
                or item["strategy_id"] != match["strategy_id"]
            ):
                raise RoleContractError("unknown_region_or_strategy")
            if type(item["weight"]) not in (int, float) or not math.isfinite(item["weight"]):
                raise RoleContractError("non_finite_weight")
            if item["weight"] < 0:
                raise RoleContractError("negative_weight")
        elif request.role is RoleKind.MODEL_CRITIC:
            item = _exact(payload, {"reviews"}, "critic")
            reviews = item["reviews"]
            if not isinstance(reviews, list):
                raise RoleContractError("reviews")
            seen: set[str] = set()
            for review in reviews:
                risk = _exact(
                    review,
                    {
                        "entry_id",
                        "uncertainty_risk",
                        "constraint_risk",
                        "failure_risk",
                        "cost_risk",
                        "veto",
                    },
                    "risk_review",
                )
                entry_id = risk["entry_id"]
                if not isinstance(entry_id, str) or entry_id not in ids:
                    raise RoleContractError("unknown_pool_entry")
                if entry_id in seen:
                    raise RoleContractError("duplicate_review")
                seen.add(entry_id)
                if any(
                    not isinstance(risk[k], str) or risk[k] not in RISK_LEVELS
                    for k in ("uncertainty_risk", "constraint_risk", "failure_risk", "cost_risk")
                ):
                    raise RoleContractError("risk_level")
                if type(risk["veto"]) is not bool:
                    raise RoleContractError("veto")
            if seen != ids:
                raise RoleContractError("incomplete_review")
        else:
            item = _exact(payload, {"ordered_entry_ids", "selected_entry_id"}, "integrator")
            ordered = item["ordered_entry_ids"]
            if not isinstance(ordered, list) or not ordered:
                raise RoleContractError("ordered_entry_ids")
            if any(not isinstance(x, str) or x not in ids for x in ordered):
                raise RoleContractError("unknown_pool_entry")
            if len(set(ordered)) != len(ordered):
                raise RoleContractError("duplicate_selection")
            if item["selected_entry_id"] != ordered[0]:
                raise RoleContractError("selection_not_first")
            if item["selected_entry_id"] in request.vetoed_ids:
                raise RoleContractError("vetoed_selection")
        content = {key: value for key, value in data.items() if key != "response_id"}
        if data["response_id"] != stable_id("role-response", content):
            raise RoleContractError("response_id")
        return cls(
            response_id=data["response_id"],
            request_id=request.request_id,
            role=request.role,
            pool_id=request.pool_id,
            payload=cast(dict[str, JsonValue], payload),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": ROLE_RESPONSE_VERSION,
            "response_id": self.response_id,
            "request_id": self.request_id,
            "role": self.role.value,
            "pool_id": self.pool_id,
            "payload": self.payload,
        }


class RoleProvider(Protocol):
    def respond(self, request: RoleRequest) -> str:
        """Return one strict JSON response; no oracle capability is provided."""


class DeterministicFakeRoleProvider:
    """Injected local fake; no LLM, transport, credential, or network surface."""

    version = ROLE_PROVIDER_VERSION

    def respond(self, request: RoleRequest) -> str:
        entries = request.entries
        if request.role is RoleKind.GLOBAL_EXPLORER:
            selected = min(entries, key=lambda e: (-cast(float, e["uncertainty"]), e["entry_id"]))
            payload: dict[str, JsonValue] = self._preference(selected)
        elif request.role is RoleKind.LOCAL_EXPLOITER:
            selected = min(entries, key=lambda e: (cast(float, e["predicted_mean"]), e["entry_id"]))
            payload = self._preference(selected)
        elif request.role is RoleKind.MODEL_CRITIC:
            payload = {
                "reviews": [
                    {
                        "entry_id": e["entry_id"],
                        "uncertainty_risk": "high"
                        if cast(float, e["uncertainty"]) > 0.5
                        else "low",
                        "constraint_risk": "low",
                        "failure_risk": "low",
                        "cost_risk": "low",
                        "veto": False,
                    }
                    for e in entries
                ]
            }
        else:
            admissible = [e["entry_id"] for e in entries if e["entry_id"] not in request.vetoed_ids]
            guided = [x for x in request.guidance_ids if x in admissible]
            ordered = [*dict.fromkeys(guided), *(x for x in admissible if x not in guided)]
            if not ordered:
                raise RoleContractError("no_admissible_entry")
            payload = {"ordered_entry_ids": ordered, "selected_entry_id": ordered[0]}
        return canonical_json(RoleResponse.create(request, payload).to_dict())

    @staticmethod
    def _preference(entry: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return {
            "entry_id": entry["entry_id"],
            "region_id": entry["region_id"],
            "strategy_id": entry["strategy_id"],
            "weight": 1.0,
        }


@dataclass(frozen=True, slots=True)
class RoleDecision:
    selected_entry_id: str | None
    source: str
    vetoed_ids: tuple[str, ...]


class RoleController:
    """Read-only role collaboration; decisions never dispatch an oracle."""

    def __init__(
        self,
        *,
        provider: RoleProvider,
        ledger: EBBOLedger,
        store: ObservationStore,
        root_seed: int,
        veto_mode: str = "advisory",
    ) -> None:
        if veto_mode not in {"advisory", "hard"}:
            raise ValueError("veto_mode must be advisory or hard")
        self.provider = provider
        self.ledger = ledger
        self.store = store
        self.root_seed = root_seed
        self.veto_mode = veto_mode

    def choose(
        self,
        pool: CandidatePool,
        *,
        iteration: int,
        mode: str,
    ) -> RoleDecision:
        if mode not in {"full", "no_roles", "no_critic", "no_integrator"}:
            raise ValueError("unknown P9b control mode")
        if not pool.entries:
            return RoleDecision(None, "empty_pool", ())
        if mode == "no_roles":
            return RoleDecision(pool.selected.candidate_id, "acquisition", ())
        roles = [RoleKind.GLOBAL_EXPLORER, RoleKind.LOCAL_EXPLOITER]
        if mode != "no_critic":
            roles.append(RoleKind.MODEL_CRITIC)
        if mode != "no_integrator":
            roles.append(RoleKind.RESOURCE_INTEGRATOR)
        guidance: list[str] = []
        vetoed: set[str] = set()
        fallback = False
        chosen: str | None = None
        for role in roles:
            request = RoleRequest.create(
                role=role,
                pool=pool,
                iteration=iteration,
                root_seed=self.root_seed,
                observation_ids=tuple(o.observation_id for o in self.store.observations),
                guidance_ids=tuple(dict.fromkeys(guidance)),
                vetoed_ids=tuple(sorted(vetoed)) if self.veto_mode == "hard" else (),
                remaining_oracle_calls=max(
                    0, (self.ledger.max_oracle_calls or 0) - self.ledger.oracle_calls
                ),
            )
            self._audit(
                "role_request",
                {
                    "request": request.to_dict(),
                    "provider_version": ROLE_PROVIDER_VERSION,
                    "veto_mode": self.veto_mode,
                },
            )
            encoded = canonical_json(request.to_dict())
            input_tokens = mock_token_count(encoded)
            if not self.ledger.can_accept_role_call(input_tokens):
                self._audit(
                    "role_failure",
                    {
                        "request_id": request.request_id,
                        "role": role.value,
                        "reason": "role_budget_exhausted",
                    },
                )
                fallback = True
                break
            self.ledger.accept_role_call(input_tokens)
            settled = False
            try:
                raw = self.provider.respond(request)
                if not isinstance(raw, str):
                    raise RoleContractError("provider_non_json")
                output_tokens = mock_token_count(raw)
                self.ledger.settle_role_call(output_tokens)
                settled = True
                if (
                    self.ledger.max_role_tokens is not None
                    and self.ledger.tokens > self.ledger.max_role_tokens
                ):
                    raise RoleContractError("role_token_budget_exceeded")
                response = RoleResponse.from_json(raw, request)
            except TimeoutError:
                if not settled:
                    self.ledger.settle_role_call(0)
                self._audit(
                    "role_failure",
                    {
                        "request_id": request.request_id,
                        "role": role.value,
                        "reason": "provider_timeout",
                    },
                )
                fallback = True
                break
            except Exception as exc:
                if not settled:
                    self.ledger.settle_role_call(0)
                reason = (
                    exc.code
                    if isinstance(exc, RoleContractError)
                    else ("invalid_json" if isinstance(exc, ValueError) else "provider_error")
                )
                self._audit(
                    "role_failure",
                    {
                        "request_id": request.request_id,
                        "role": role.value,
                        "reason": reason,
                        "error_type": type(exc).__name__,
                    },
                )
                fallback = True
                break
            self._audit("role_response", {"response": response.to_dict()})
            if role in {RoleKind.GLOBAL_EXPLORER, RoleKind.LOCAL_EXPLOITER}:
                guidance.append(cast(str, response.payload["entry_id"]))
            elif role is RoleKind.MODEL_CRITIC:
                reviews = cast(list[dict[str, JsonValue]], response.payload["reviews"])
                suggested = {cast(str, r["entry_id"]) for r in reviews if r["veto"]}
                self._audit(
                    "critic_review",
                    {
                        "request_id": request.request_id,
                        "suggested_veto_ids": cast(list[JsonValue], sorted(suggested)),
                        "effective_veto_ids": cast(list[JsonValue], sorted(suggested))
                        if self.veto_mode == "hard"
                        else [],
                    },
                )
                if self.veto_mode == "hard":
                    vetoed.update(suggested)
            else:
                chosen = cast(str, response.payload["selected_entry_id"])
        admissible = [e.candidate_id for e in pool.entries if e.candidate_id not in vetoed]
        if not admissible:
            self._audit("role_no_admissible_candidate", {"pool_id": pool.pool_id})
            return RoleDecision(None, "hard_veto_all", tuple(sorted(vetoed)))
        if fallback or chosen is None or chosen not in admissible:
            selected = admissible[0]
            source = "acquisition_fallback" if fallback else "acquisition"
        else:
            selected = chosen
            source = "integrator"
        self._audit(
            "role_decision",
            {
                "pool_id": pool.pool_id,
                "selected_entry_id": selected,
                "source": source,
                "vetoed_ids": cast(list[JsonValue], sorted(vetoed)),
            },
        )
        return RoleDecision(selected, source, tuple(sorted(vetoed)))

    def _audit(self, kind: str, payload: dict[str, JsonValue]) -> None:
        self.store.append_audit(
            AuditEvent.create(
                len(self.store.events),
                kind,
                {"role_audit_version": ROLE_AUDIT_VERSION, **payload},
            )
        )
