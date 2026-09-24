"""P9b selection gate in front of the unchanged P9a serial oracle scheduler."""

from __future__ import annotations

from roco_ebbo.ebbo.baseline import CANDIDATE_POOL_VERSION, CandidatePool
from roco_ebbo.ebbo.contracts import JsonValue, Observation, stable_id
from roco_ebbo.ebbo.ledger import EBBOBudgetExceeded
from roco_ebbo.ebbo.roles import ROLE_AUDIT_VERSION, RoleDecision
from roco_ebbo.ebbo.scheduler import DuplicateDispatchError, SerialScheduler
from roco_ebbo.ebbo.store import AuditEvent


class RestrictedRoleScheduler:
    """Only this gate passes a selected existing entry to the oracle-capable scheduler."""

    def __init__(self, serial: SerialScheduler) -> None:
        self.serial = serial

    def dispatch(self, pool: CandidatePool, decision: RoleDecision) -> Observation:
        payload: dict[str, JsonValue] = {
            "pool_id": pool.pool_id,
            "selected_entry_id": decision.selected_entry_id,
            "source": decision.source,
        }
        try:
            self._validate_pool(pool)
            selected = next(
                (
                    entry
                    for entry in pool.entries
                    if entry.candidate_id == decision.selected_entry_id
                ),
                None,
            )
            if selected is None:
                raise ValueError("selected entry is not in the current finite pool")
            if selected.candidate_id in decision.vetoed_ids:
                raise ValueError("selected entry was hard-vetoed")
            if selected.candidate_id in self.serial.dispatched_candidate_ids:
                raise DuplicateDispatchError("candidate was already dispatched")
            # P9a's Mock contract has no constraints. This is the explicit constraint gate:
            # reject invalid/out-of-domain candidates rather than inferring feasibility.
            self.serial.oracle.search_space.validate_candidate(dict(selected.candidate))
            expected = self.serial.oracle.expected_cost(dict(selected.candidate))
            amount = expected["amount"]
            if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                raise ValueError("unknown expected Mock cost")
            ledger = self.serial.ledger
            if ledger.unknown_cost_attempt_ids:
                raise EBBOBudgetExceeded("unknown prior cost closes scheduling")
            if (
                ledger.max_oracle_calls is not None
                and ledger.oracle_calls + 1 > ledger.max_oracle_calls
            ):
                raise EBBOBudgetExceeded("oracle call budget would be exceeded")
            if ledger.max_cost is not None and ledger.known_cost + amount > ledger.max_cost:
                raise EBBOBudgetExceeded("expected cost budget would be exceeded")
        except (ValueError, DuplicateDispatchError, EBBOBudgetExceeded) as exc:
            self._audit(
                "role_dispatch_rejected",
                {
                    **payload,
                    "reason": type(exc).__name__,
                    "constraint_contract": "none-v1",
                },
            )
            raise
        assert selected is not None
        self._audit(
            "role_dispatch_authorized",
            {
                **payload,
                "constraint_contract": "none-v1",
                "budget_preflight": "passed",
            },
        )
        # Ephemeral view preserves the source pool ID. It is never persisted as a new pool,
        # never consumes candidate-proposal budget, and grants no permit to a role.
        view = CandidatePool(
            pool_id=pool.pool_id,
            entries=(selected,),
            proposals_received=pool.proposals_received,
            duplicates_removed=pool.duplicates_removed,
        )
        return self.serial.dispatch(view)

    def _validate_pool(self, pool: CandidatePool) -> None:
        if not pool.entries or pool.proposals_received < len(pool.entries):
            raise ValueError("invalid finite candidate pool")
        if pool.duplicates_removed != pool.proposals_received - len(pool.entries):
            raise ValueError("candidate pool deduplication count mismatch")
        if pool.entries != tuple(
            sorted(pool.entries, key=lambda e: (e.acquisition_score, e.candidate_id))
        ):
            raise ValueError("candidate pool acquisition ordering mismatch")
        ids = [entry.candidate_id for entry in pool.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate candidate in pool")
        for entry in pool.entries:
            candidate = dict(entry.candidate)
            self.serial.oracle.search_space.validate_candidate(candidate)
            if entry.candidate_id != self.serial.oracle.search_space.candidate_id(candidate):
                raise ValueError("candidate ID does not match Mock search space")
        content: JsonValue = {
            "schema_version": CANDIDATE_POOL_VERSION,
            "entries": [entry.to_dict() for entry in pool.entries],
            "proposals_received": pool.proposals_received,
            "duplicates_removed": pool.duplicates_removed,
        }
        if pool.pool_id != stable_id("pool", content):
            raise ValueError("candidate pool ID does not match immutable content")

    def _audit(self, kind: str, payload: dict[str, JsonValue]) -> None:
        store = self.serial.store
        store.append_audit(
            AuditEvent.create(
                len(store.events),
                kind,
                {"role_audit_version": ROLE_AUDIT_VERSION, **payload},
            )
        )
