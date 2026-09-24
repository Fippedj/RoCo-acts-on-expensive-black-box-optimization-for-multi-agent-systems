"""Deterministic P9c Mock pending scheduler and commit-last checkpoint boundary."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, cast

from roco_ebbo.ebbo.async_ledger import AsyncEBBOLedger
from roco_ebbo.ebbo.baseline import CANDIDATE_POOL_VERSION, CandidatePool, CandidatePoolEntry
from roco_ebbo.ebbo.contracts import (
    EvaluationStatus,
    JsonValue,
    Observation,
    OracleRequest,
    OracleResult,
    canonical_json,
    derive_seed,
    stable_id,
    strict_json_loads,
)
from roco_ebbo.ebbo.ledger import EBBOBudgetExceeded
from roco_ebbo.ebbo.oracle import (
    MOCK_COST_SOURCE,
    MOCK_COST_UNIT,
    MOCK_ORACLE_VERSION,
    AcceptedAttempt,
    MockExpensiveOracle,
)
from roco_ebbo.ebbo.scheduler import DuplicateDispatchError, NoCandidateError
from roco_ebbo.ebbo.store import AuditEvent, ObservationStore

ASYNC_SCHEDULER_VERSION = "ebbo-async-mock-scheduler-v1"
ASYNC_CHECKPOINT_VERSION = "ebbo-async-checkpoint-v1"


@dataclass(slots=True)
class PendingEvaluation:
    request: OracleRequest
    status: EvaluationStatus
    attempt: AcceptedAttempt | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "request_id": self.request.request_id,
            "status": self.status.value,
            "attempt_id": None if self.attempt is None else self.attempt.attempt_id,
        }


class AsyncMockScheduler:
    """The sole oracle permit holder on the opt-in P9c path."""

    def __init__(
        self,
        *,
        oracle: MockExpensiveOracle,
        ledger: AsyncEBBOLedger,
        store: ObservationStore,
        run_id: str,
        root_seed: int,
        config_digest: str,
    ) -> None:
        if not run_id or not config_digest:
            raise ValueError("run/config identity is required")
        self.oracle = oracle
        self.ledger = ledger
        self.store = store
        self.run_id = run_id
        self.root_seed = root_seed
        self.config_digest = config_digest
        self._permit = oracle._bind_scheduler()
        self._pending: dict[str, PendingEvaluation] = {}
        self._requests: list[OracleRequest] = []
        self._results: list[OracleResult] = []
        self._pools: list[CandidatePool] = []
        self._dispatched_candidate_ids: set[str] = set()
        self._request_index = 0

    @property
    def requests(self) -> tuple[OracleRequest, ...]:
        return tuple(self._requests)

    @property
    def results(self) -> tuple[OracleResult, ...]:
        return tuple(self._results)

    @property
    def pools(self) -> tuple[CandidatePool, ...]:
        return tuple(self._pools)

    @property
    def pending(self) -> tuple[PendingEvaluation, ...]:
        return tuple(
            sorted(self._pending.values(), key=lambda p: p.request.logical_evaluation_index)
        )

    @property
    def dispatched_candidate_ids(self) -> frozenset[str]:
        return frozenset(self._dispatched_candidate_ids)

    def reserve(self, pool: CandidatePool, *, entry_id: str | None = None) -> OracleRequest:
        try:
            self._validate_pool(pool)
            if not pool.entries:
                raise NoCandidateError("candidate pool has no entries")
            chosen = (
                pool.entries[0]
                if entry_id is None
                else next((entry for entry in pool.entries if entry.candidate_id == entry_id), None)
            )
            if chosen is None:
                raise ValueError("selected entry is not in the current candidate pool")
            if chosen.candidate_id in self._dispatched_candidate_ids or any(
                p.request.candidate_id == chosen.candidate_id for p in self._pending.values()
            ):
                raise DuplicateDispatchError("candidate is pending or was already accepted")
            candidate = dict(chosen.candidate)
            expected = self.oracle.expected_cost(candidate)
            amount = expected["amount"]
            if type(amount) not in (int, float):
                raise ValueError("Mock expected cost must be known and finite")
            request = self._new_request(chosen.candidate_id, candidate, pool.pool_id, expected)
            self.ledger.reserve(request.request_id, float(cast(float, amount)))
        except (ValueError, EBBOBudgetExceeded, DuplicateDispatchError, NoCandidateError) as exc:
            self._audit(
                "async_dispatch_rejected",
                {
                    "pool_id": pool.pool_id,
                    "entry_id": entry_id,
                    "reason": type(exc).__name__,
                },
            )
            self.checkpoint()
            raise
        self._request_index += 1
        self._requests.append(request)
        self._pools.append(pool)
        self._pending[request.request_id] = PendingEvaluation(request, EvaluationStatus.RESERVED)
        self._audit(
            "async_request_reserved", {"request": request.to_dict(), "pool": pool.to_dict()}
        )
        self.checkpoint()
        return request

    def accept(self, request_id: str) -> str:
        pending = self._pending.get(request_id)
        if pending is None or pending.status is not EvaluationStatus.RESERVED:
            self._audit(
                "async_accept_rejected",
                {
                    "request_id": request_id,
                    "reason": "not_reserved",
                },
            )
            self.checkpoint()
            raise ValueError("request is not reserved")
        try:
            accepted = self.oracle.accept(pending.request, permit=self._permit)
        except Exception as exc:
            self.ledger.cancel_before_accept(request_id)
            del self._pending[request_id]
            self._audit(
                "async_oracle_rejected_before_accept",
                {
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                },
            )
            self.checkpoint()
            raise
        self.ledger.accept(request_id, accepted.attempt_id)
        pending.attempt = accepted
        pending.status = EvaluationStatus.ACCEPTED
        self._dispatched_candidate_ids.add(pending.request.candidate_id)
        self._audit(
            "async_oracle_accepted",
            {
                "request_id": request_id,
                "attempt_id": accepted.attempt_id,
                "oracle_calls": self.ledger.oracle_calls,
            },
        )
        self.checkpoint()
        return accepted.attempt_id

    def cancel(self, request_id: str) -> EvaluationStatus:
        pending = self._pending.get(request_id)
        if pending is None:
            self._audit(
                "async_cancel_rejected", {"request_id": request_id, "reason": "not_pending"}
            )
            self.checkpoint()
            raise ValueError("request is not pending")
        if pending.status is EvaluationStatus.RESERVED:
            self.ledger.cancel_before_accept(request_id)
            del self._pending[request_id]
            self._audit(
                "async_cancelled_before_accept",
                {
                    "request_id": request_id,
                    "status": EvaluationStatus.CANCELLED_BEFORE_ACCEPT.value,
                },
            )
            self.checkpoint()
            return EvaluationStatus.CANCELLED_BEFORE_ACCEPT
        if pending.status is EvaluationStatus.CANCEL_REQUESTED:
            self._audit("async_cancel_duplicate", {"request_id": request_id})
            self.checkpoint()
            return EvaluationStatus.CANCEL_REQUESTED
        pending.status = EvaluationStatus.CANCEL_REQUESTED
        self._audit(
            "async_cancel_requested",
            {
                "request_id": request_id,
                "attempt_id": pending.attempt.attempt_id if pending.attempt else None,
            },
        )
        self.checkpoint()
        return EvaluationStatus.CANCEL_REQUESTED

    def acknowledge_cancel(self, request_id: str) -> Observation | None:
        pending = self._pending.get(request_id)
        if pending is None:
            terminal = next((r for r in self._results if r.request_id == request_id), None)
            if terminal is None:
                self._audit(
                    "async_cancel_ack_rejected",
                    {
                        "request_id": request_id,
                        "reason": "never_accepted_or_unknown",
                    },
                )
                self.checkpoint()
                raise ValueError("cancel acknowledgement has no accepted request")
            self._audit(
                "async_late_cancel_ack",
                {
                    "request_id": request_id,
                    "terminal_result_id": terminal.result_id,
                },
            )
            self.checkpoint()
            return None
        if pending.status is not EvaluationStatus.CANCEL_REQUESTED or pending.attempt is None:
            self._audit(
                "async_cancel_ack_rejected",
                {
                    "request_id": request_id,
                    "reason": "cancel_not_requested",
                },
            )
            self.checkpoint()
            raise ValueError("cancel acknowledgement requires an accepted cancel request")
        result = OracleResult.create(
            request_id=request_id,
            attempt_id=pending.attempt.attempt_id,
            status=EvaluationStatus.CANCELLED_AFTER_ACCEPT,
            objective=None,
            constraints=None,
            feasible=None,
            failure={
                "type": "mock_cancel_ack",
                "message": "local Mock cancellation confirmed",
                "retryable": False,
            },
            actual_cost={
                "amount": pending.attempt.outcome.actual_cost,
                "unit": MOCK_COST_UNIT,
                "source": MOCK_COST_SOURCE,
            },
            oracle_metadata={"adapter_version": MOCK_ORACLE_VERSION, "network": "unused"},
        )
        return self._settle(pending, result)

    def complete(self, request_id: str) -> Observation | None:
        pending = self._pending.get(request_id)
        if pending is None:
            terminal = next((r for r in self._results if r.request_id == request_id), None)
            if terminal is None:
                self._audit(
                    "async_completion_rejected",
                    {
                        "request_id": request_id,
                        "reason": "never_accepted_or_unknown",
                    },
                )
                self.checkpoint()
                raise ValueError("completion has no accepted attempt")
            self._audit(
                "async_late_result",
                {
                    "request_id": request_id,
                    "attempt_id": terminal.attempt_id,
                    "terminal_result_id": terminal.result_id,
                },
            )
            self.checkpoint()
            return None
        if pending.attempt is None or pending.status not in {
            EvaluationStatus.ACCEPTED,
            EvaluationStatus.CANCEL_REQUESTED,
        }:
            self._audit(
                "async_completion_rejected",
                {
                    "request_id": request_id,
                    "reason": "not_accepted",
                },
            )
            self.checkpoint()
            raise ValueError("request is not accepted")
        try:
            raw = self.oracle.complete(pending.attempt, permit=self._permit)
        except Exception as exc:
            raw = {"completion_error_type": type(exc).__name__}
            self._audit(
                "async_completion_exception",
                {
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                },
            )
        try:
            result = OracleResult.from_dict(raw)
            if result.request_id != request_id or result.attempt_id != pending.attempt.attempt_id:
                raise ValueError("oracle result identity mismatch")
            if result.constraints is not None or result.feasible is not None:
                raise ValueError("Mock constraint contract mismatch")
            if (
                result.actual_cost["unit"] != MOCK_COST_UNIT
                or result.actual_cost["source"] != MOCK_COST_SOURCE
            ):
                raise ValueError("Mock cost contract mismatch")
        except (ValueError, TypeError):
            amount = _recover_cost(raw)
            result = OracleResult.create(
                request_id=request_id,
                attempt_id=pending.attempt.attempt_id,
                status=EvaluationStatus.FAILED,
                objective=None,
                constraints=None,
                feasible=None,
                failure={
                    "type": "invalid_result",
                    "message": "strict Mock result rejected",
                    "retryable": False,
                },
                actual_cost={"amount": amount, "unit": MOCK_COST_UNIT, "source": MOCK_COST_SOURCE},
                oracle_metadata={"adapter_version": MOCK_ORACLE_VERSION, "network": "unused"},
            )
        return self._settle(pending, result)

    def complete_batch(self, request_ids: tuple[str, ...]) -> tuple[Observation | None, ...]:
        """Callbacks in one logical batch are processed by stable request ID."""
        return tuple(self.complete(request_id) for request_id in sorted(request_ids))

    def _settle(self, pending: PendingEvaluation, result: OracleResult) -> Observation:
        amount = result.actual_cost["amount"]
        failure_type = None if result.failure is None else result.failure.get("type")
        self.ledger.settle(
            result.attempt_id,
            status=result.status,
            actual_cost=None if amount is None else float(cast(float, amount)),
            failure_type=failure_type if isinstance(failure_type, str) else None,
        )
        self._results.append(result)
        self._audit(
            "async_result_recorded",
            {
                "result": result.to_dict(),
                "ledger": self.ledger.replay_dict(),
            },
        )
        observation = Observation.from_result(
            pending.request, result, completion_sequence=len(self.store.observations)
        )
        self.store.append_observation(observation)
        self._audit("async_observation_appended", {"observation": observation.to_dict()})
        del self._pending[pending.request.request_id]
        self.checkpoint()
        return observation

    def _new_request(
        self,
        candidate_id: str,
        candidate: dict[str, JsonValue],
        pool_id: str,
        expected: dict[str, JsonValue],
    ) -> OracleRequest:
        index = self._request_index
        oracle_seed = derive_seed(self.root_seed, "oracle", index, candidate_id)
        return OracleRequest.create(
            run_id=self.run_id,
            problem_id=self.oracle.search_space.problem_id,
            candidate_id=candidate_id,
            candidate=candidate,
            problem_version="mock-quadratic-engineering-v1",
            oracle_contract_version=MOCK_ORACLE_VERSION,
            logical_evaluation_index=index,
            replicate_index=0,
            oracle_seed=oracle_seed,
            timeout_seconds=1.0,
            seed_lineage={
                "root_seed": self.root_seed,
                "request_index": index,
                "candidate_seed": derive_seed(self.root_seed, "candidate", index, candidate_id),
                "oracle_seed": oracle_seed,
            },
            budget_reservation={
                "expected_cost": expected["amount"],
                "cost_unit": expected["unit"],
                "cost_source": expected["source"],
                "oracle_calls": 1,
            },
            provenance={
                "candidate_pool_id": pool_id,
                "acquisition_contract": "ebbo-lower-confidence-bound-v1",
                "scheduler": ASYNC_SCHEDULER_VERSION,
            },
        )

    def _validate_pool(self, pool: CandidatePool) -> None:
        if pool.proposals_received < len(pool.entries):
            raise ValueError("invalid finite pool count")
        if pool.duplicates_removed != pool.proposals_received - len(pool.entries):
            raise ValueError("invalid pool deduplication count")
        if pool.entries != tuple(
            sorted(pool.entries, key=lambda e: (e.acquisition_score, e.candidate_id))
        ):
            raise ValueError("invalid pool acquisition order")
        ids = [e.candidate_id for e in pool.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate pool candidate")
        for entry in pool.entries:
            candidate = dict(entry.candidate)
            self.oracle.search_space.validate_candidate(candidate)
            if entry.candidate_id != self.oracle.search_space.candidate_id(candidate):
                raise ValueError("pool candidate identity mismatch")
        content: JsonValue = {
            "schema_version": CANDIDATE_POOL_VERSION,
            "entries": [e.to_dict() for e in pool.entries],
            "proposals_received": pool.proposals_received,
            "duplicates_removed": pool.duplicates_removed,
        }
        if pool.pool_id != stable_id("pool", content):
            raise ValueError("pool hash mismatch")

    def _audit(self, kind: str, payload: dict[str, JsonValue]) -> None:
        self.store.append_audit(AuditEvent.create(len(self.store.events), kind, payload))

    def checkpoint(self) -> None:
        state: dict[str, JsonValue] = {
            "requests": [r.to_dict() for r in self._requests],
            "results": [r.to_dict() for r in self._results],
            "pools": [p.to_dict() for p in self._pools],
            "pending": [p.to_dict() for p in self.pending],
            "dispatched_candidate_ids": cast(
                list[JsonValue], sorted(self._dispatched_candidate_ids)
            ),
            "request_index": self._request_index,
            "ledger": self.ledger.state(),
        }
        body: dict[str, JsonValue] = {
            "schema_version": ASYNC_CHECKPOINT_VERSION,
            "run_id": self.run_id,
            "root_seed": self.root_seed,
            "config_digest": self.config_digest,
            "store_snapshot": self.store.snapshot(),
            "state": state,
        }
        encoded = (
            canonical_json({**body, "checkpoint_id": stable_id("async-checkpoint", body)}) + "\n"
        )
        root = self.store.root
        for stream_path in (self.store.audit_path, self.store.observations_path):
            if stream_path.exists():
                with stream_path.open("rb") as stream:
                    os.fsync(stream.fileno())
        temp = root / "checkpoint.json.tmp"
        target = root / "checkpoint.json"
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @classmethod
    def resume(
        cls,
        *,
        oracle: MockExpensiveOracle,
        store: ObservationStore,
        run_id: str,
        root_seed: int,
        config_digest: str,
        max_oracle_calls: int,
        max_candidate_proposals: int,
        max_cost: float,
        max_concurrency: int,
    ) -> AsyncMockScheduler:
        path = store.root / "checkpoint.json"
        if (store.root / "checkpoint.json.tmp").exists():
            raise ValueError("orphan P9c checkpoint temporary file")
        if not path.is_file():
            raise ValueError("missing P9c checkpoint")
        raw = strict_json_loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version",
            "run_id",
            "root_seed",
            "config_digest",
            "store_snapshot",
            "state",
            "checkpoint_id",
        }:
            raise ValueError("P9c checkpoint schema mismatch")
        if (
            raw["schema_version"] != ASYNC_CHECKPOINT_VERSION
            or raw["run_id"] != run_id
            or (raw["root_seed"] != root_seed or raw["config_digest"] != config_digest)
        ):
            raise ValueError("P9c checkpoint identity mismatch")
        body = {key: value for key, value in raw.items() if key != "checkpoint_id"}
        if raw["checkpoint_id"] != stable_id("async-checkpoint", body):
            raise ValueError("P9c checkpoint hash mismatch")
        if raw["store_snapshot"] != store.snapshot():
            raise ValueError("P9c checkpoint/store mismatch; orphan or corrupt tail")
        state = raw["state"]
        if not isinstance(state, dict) or set(state) != {
            "requests",
            "results",
            "pools",
            "pending",
            "dispatched_candidate_ids",
            "request_index",
            "ledger",
        }:
            raise ValueError("P9c checkpoint state schema mismatch")
        decoded_state = cast(dict[str, Any], state)
        ledger_state = decoded_state["ledger"]
        if not isinstance(ledger_state, dict):
            raise ValueError("P9c ledger state is missing")
        ledger = AsyncEBBOLedger.from_state(
            ledger_state,
            max_oracle_calls=max_oracle_calls,
            max_candidate_proposals=max_candidate_proposals,
            max_cost=max_cost,
            cost_unit=MOCK_COST_UNIT,
            max_concurrency=max_concurrency,
        )
        scheduler = cls(
            oracle=oracle,
            ledger=ledger,
            store=store,
            run_id=run_id,
            root_seed=root_seed,
            config_digest=config_digest,
        )
        try:
            scheduler._requests = [OracleRequest.from_dict(x) for x in decoded_state["requests"]]
            scheduler._results = [OracleResult.from_dict(x) for x in decoded_state["results"]]
            scheduler._pools = [scheduler._restore_pool(x) for x in decoded_state["pools"]]
            scheduler._request_index = decoded_state["request_index"]
            scheduler._dispatched_candidate_ids = set(decoded_state["dispatched_candidate_ids"])
            for item in decoded_state["pending"]:
                if not isinstance(item, dict) or set(item) != {
                    "request_id",
                    "status",
                    "attempt_id",
                }:
                    raise ValueError("checkpoint pending schema mismatch")
                request = next(r for r in scheduler._requests if r.request_id == item["request_id"])
                status = EvaluationStatus(item["status"])
                if status not in {
                    EvaluationStatus.RESERVED,
                    EvaluationStatus.ACCEPTED,
                    EvaluationStatus.CANCEL_REQUESTED,
                }:
                    raise ValueError("invalid pending status")
                attempt: AcceptedAttempt | None = None
                if status is not EvaluationStatus.RESERVED:
                    x = oracle.search_space.validate_candidate(request.candidate)
                    attempt_id = stable_id(
                        "attempt",
                        {
                            "adapter_version": MOCK_ORACLE_VERSION,
                            "request_id": request.request_id,
                            "attempt_index": 0,
                        },
                    )
                    if item["attempt_id"] != attempt_id:
                        raise ValueError("pending attempt identity mismatch")
                    from roco_ebbo.ebbo.oracle import MockOracleOutcome

                    attempt = AcceptedAttempt(
                        request,
                        attempt_id,
                        x,
                        oracle.outcomes.get(x, MockOracleOutcome()),
                    )
                elif item["attempt_id"] is not None:
                    raise ValueError("reserved request cannot have attempt")
                if request.request_id in scheduler._pending:
                    raise ValueError("checkpoint duplicate pending request")
                scheduler._pending[request.request_id] = PendingEvaluation(request, status, attempt)
        except (KeyError, TypeError, StopIteration, AttributeError) as exc:
            raise ValueError("P9c checkpoint contains malformed state") from exc
        scheduler._validate_restored()
        return scheduler

    def _restore_pool(self, raw: Any) -> CandidatePool:
        if (
            not isinstance(raw, dict)
            or set(raw)
            != {
                "schema_version",
                "pool_id",
                "entries",
                "proposals_received",
                "duplicates_removed",
                "tie_break",
            }
            or raw["schema_version"] != CANDIDATE_POOL_VERSION
        ):
            raise ValueError("checkpoint pool schema mismatch")
        if raw["tie_break"] != "acquisition_score-ascending-then-candidate_id-ascending":
            raise ValueError("checkpoint pool tie-break mismatch")
        entries = tuple(CandidatePoolEntry(**entry) for entry in raw["entries"])
        pool = CandidatePool(
            raw["pool_id"], entries, raw["proposals_received"], raw["duplicates_removed"]
        )
        self._validate_pool(pool)
        return pool

    def _validate_restored(self) -> None:
        requests = self._requests
        results = self._results
        ledger = self.ledger
        if type(self._request_index) is not int or self._request_index != len(requests):
            raise ValueError("checkpoint request index mismatch")
        if len({r.request_id for r in requests}) != len(requests):
            raise ValueError("checkpoint duplicate request")
        if [r.logical_evaluation_index for r in requests] != list(range(len(requests))):
            raise ValueError("checkpoint request logical indexes mismatch")
        if len(self._pools) != len(requests):
            raise ValueError("checkpoint pool/request count mismatch")
        if ledger.candidate_proposals < sum(p.proposals_received for p in self._pools):
            raise ValueError("checkpoint candidate proposal count mismatch")
        if any(r.run_id != self.run_id for r in requests):
            raise ValueError("checkpoint request run mismatch")
        pending_ids = set(self._pending)
        accepted_events = [e for e in self.store.events if e.kind == "async_oracle_accepted"]
        if len(accepted_events) != ledger.oracle_calls:
            raise ValueError("checkpoint accepted call audit mismatch")
        accepted_requests = {cast(str, e.payload["request_id"]) for e in accepted_events}
        accepted_attempts = {cast(str, e.payload["attempt_id"]) for e in accepted_events}
        if len(accepted_requests) != len(accepted_events) or len(accepted_attempts) != len(
            accepted_events
        ):
            raise ValueError("checkpoint duplicate accepted attempt")
        if self._dispatched_candidate_ids != {
            r.candidate_id for r in requests if r.request_id in accepted_requests
        }:
            raise ValueError("checkpoint dispatched candidate mismatch")
        if set(ledger._accepted_attempts) != {
            p.attempt.attempt_id for p in self._pending.values() if p.attempt is not None
        }:
            raise ValueError("checkpoint pending accepted attempts mismatch")
        if set(ledger._reservations) != {
            p.request.request_id
            for p in self._pending.values()
            if p.status is EvaluationStatus.RESERVED
        }:
            raise ValueError("checkpoint reservation mismatch")
        if len(results) != len(self.store.observations) or len(results) != ledger.evaluations_total:
            raise ValueError("checkpoint result/observation count mismatch")
        if {r.attempt_id for r in results} != ledger._settled_attempts:
            raise ValueError("checkpoint settled attempt mismatch")
        if {r.attempt_id for r in results} | set(ledger._accepted_attempts) != accepted_attempts:
            raise ValueError("checkpoint accepted/result relationship mismatch")
        for index, (result, observation) in enumerate(zip(results, self.store.observations)):
            request = next((r for r in requests if r.request_id == result.request_id), None)
            if (
                request is None
                or Observation.from_result(request, result, completion_sequence=index).replay_dict()
                != observation.replay_dict()
            ):
                raise ValueError("checkpoint result/observation mismatch")
        request_events = [e for e in self.store.events if e.kind == "async_request_reserved"]
        if len(request_events) != len(requests):
            raise ValueError("checkpoint reserved request audit mismatch")
        for request, pool, event in zip(requests, self._pools, request_events):
            if event.payload != {"request": request.to_dict(), "pool": pool.to_dict()}:
                raise ValueError("checkpoint request/pool audit mismatch")
            candidate = request.candidate
            self.oracle.search_space.validate_candidate(candidate)
            if request.problem_id != self.oracle.search_space.problem_id or (
                request.candidate_id != self.oracle.search_space.candidate_id(candidate)
            ):
                raise ValueError("checkpoint Mock request identity mismatch")
            if request.constraint_contract != {"enabled": False, "version": "none-v1"}:
                raise ValueError("checkpoint Mock constraint mismatch")
            if request.provenance != {
                "candidate_pool_id": pool.pool_id,
                "acquisition_contract": "ebbo-lower-confidence-bound-v1",
                "scheduler": ASYNC_SCHEDULER_VERSION,
            } or request.candidate_id not in {entry.candidate_id for entry in pool.entries}:
                raise ValueError("checkpoint pool membership mismatch")
            expected = self.oracle.expected_cost(candidate)
            if request.budget_reservation != {
                "expected_cost": expected["amount"],
                "cost_unit": expected["unit"],
                "cost_source": expected["source"],
                "oracle_calls": 1,
            }:
                raise ValueError("checkpoint Mock cost reservation mismatch")
            index = request.logical_evaluation_index
            seed = derive_seed(self.root_seed, "oracle", index, request.candidate_id)
            if request.oracle_seed != seed or request.seed_lineage != {
                "root_seed": self.root_seed,
                "request_index": index,
                "candidate_seed": derive_seed(
                    self.root_seed, "candidate", index, request.candidate_id
                ),
                "oracle_seed": seed,
            }:
                raise ValueError("checkpoint request seed mismatch")
        request_by_id = {request.request_id: request for request in requests}
        for number, event in enumerate(accepted_events, start=1):
            request_id = event.payload.get("request_id")
            request = request_by_id.get(request_id) if isinstance(request_id, str) else None
            if request is None or event.payload != {
                "request_id": request_id,
                "attempt_id": stable_id(
                    "attempt",
                    {
                        "adapter_version": MOCK_ORACLE_VERSION,
                        "request_id": request_id,
                        "attempt_index": 0,
                    },
                ),
                "oracle_calls": number,
            }:
                raise ValueError("checkpoint accepted attempt audit mismatch")
        if len(self._dispatched_candidate_ids) != ledger.oracle_calls:
            raise ValueError("checkpoint duplicate accepted candidate")
        expected_active = {
            pending.attempt.attempt_id: pending.request.request_id
            for pending in self._pending.values()
            if pending.attempt is not None
        }
        if ledger._accepted_attempts != expected_active:
            raise ValueError("checkpoint accepted request mapping mismatch")
        for pending in self._pending.values():
            request_id = pending.request.request_id
            expected_cost = pending.request.budget_reservation["expected_cost"]
            if pending.status is EvaluationStatus.RESERVED:
                if ledger._reservations.get(request_id) != expected_cost:
                    raise ValueError("checkpoint reserved cost mismatch")
            elif pending.attempt is not None:
                if ledger._pending_costs.get(pending.attempt.attempt_id) != expected_cost:
                    raise ValueError("checkpoint pending cost mismatch")
            if pending.status is EvaluationStatus.CANCEL_REQUESTED and not any(
                event.kind == "async_cancel_requested"
                and event.payload.get("request_id") == request_id
                for event in self.store.events
            ):
                raise ValueError("checkpoint cancel request audit mismatch")
        for request in requests:
            if request.request_id not in accepted_requests | pending_ids and not any(
                event.kind
                in {"async_cancelled_before_accept", "async_oracle_rejected_before_accept"}
                and event.payload.get("request_id") == request.request_id
                for event in self.store.events
            ):
                raise ValueError("checkpoint unresolved pre-accept request")
        result_events = [e for e in self.store.events if e.kind == "async_result_recorded"]
        observation_events = [
            e for e in self.store.events if e.kind == "async_observation_appended"
        ]
        if len(result_events) != len(results) or len(observation_events) != len(results):
            raise ValueError("checkpoint result audit count mismatch")
        for result, observation, result_event, observation_event in zip(
            results, self.store.observations, result_events, observation_events
        ):
            if result_event.payload.get("result") != result.to_dict() or (
                observation_event.payload != {"observation": observation.to_dict()}
            ):
                raise ValueError("checkpoint terminal audit mismatch")
        known_cost = 0.0
        unknown_cost: list[str] = []
        failures: dict[str, int] = {}
        for result in results:
            amount = result.actual_cost["amount"]
            if amount is None:
                unknown_cost.append(result.attempt_id)
            else:
                known_cost += float(cast(float, amount))
            if result.status is not EvaluationStatus.SUCCEEDED:
                category = result.status.value
                if result.status is not EvaluationStatus.CANCELLED_AFTER_ACCEPT and (
                    result.failure is not None
                ):
                    failure_type = result.failure.get("type")
                    if isinstance(failure_type, str):
                        category = failure_type
                failures[category] = failures.get(category, 0) + 1
        if (
            ledger.known_cost != known_cost
            or sorted(ledger.unknown_cost_attempt_ids) != sorted(unknown_cost)
            or ledger.evaluations_succeeded
            != sum(result.status is EvaluationStatus.SUCCEEDED for result in results)
            or ledger.failure_breakdown != failures
        ):
            raise ValueError("checkpoint terminal ledger accounting mismatch")
        if pending_ids & {r.request_id for r in results}:
            raise ValueError("checkpoint terminal request remains pending")
        if len(pending_ids) != ledger.outstanding:
            raise ValueError("checkpoint outstanding count mismatch")


def _recover_cost(raw: Any) -> float | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("actual_cost"), dict):
        return None
    cost = raw["actual_cost"]
    if cost.get("unit") != MOCK_COST_UNIT or cost.get("source") != MOCK_COST_SOURCE:
        return None
    value = cost.get("amount")
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return None
    return float(value)
