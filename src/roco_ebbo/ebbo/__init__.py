"""Offline deterministic Stage 6 P9a EBBO engineering runtime."""

from roco_ebbo.ebbo.baseline import (
    ACQUISITION_VERSION,
    SURROGATE_VERSION,
    CandidatePool,
    CandidatePoolEntry,
    MockSearchSpace,
    NearestObservationSurrogate,
    SurrogatePrediction,
    SurrogateSample,
    build_candidate_pool,
    lower_confidence_bound,
)
from roco_ebbo.ebbo.contracts import (
    CANONICAL_JSON_VERSION,
    EvaluationStatus,
    Observation,
    OracleRequest,
    OracleResult,
    canonical_json,
    derive_seed,
    stable_id,
    strict_json_loads,
)
from roco_ebbo.ebbo.ledger import EBBOBudgetExceeded, EBBOLedger
from roco_ebbo.ebbo.oracle import (
    MOCK_COST_UNIT,
    MOCK_ORACLE_VERSION,
    MockExpensiveOracle,
    MockOracleOutcome,
)
from roco_ebbo.ebbo.runtime import (
    EBBOSmokeRun,
    EBBOSmokeSettings,
    load_ebbo_smoke_settings,
    run_ebbo_smoke,
)
from roco_ebbo.ebbo.scheduler import (
    DuplicateDispatchError,
    NoCandidateError,
    SerialScheduler,
)
from roco_ebbo.ebbo.store import AuditEvent, ObservationStore

__all__ = [
    "ACQUISITION_VERSION",
    "AuditEvent",
    "CANONICAL_JSON_VERSION",
    "CandidatePool",
    "CandidatePoolEntry",
    "DuplicateDispatchError",
    "EBBOBudgetExceeded",
    "EBBOLedger",
    "EBBOSmokeRun",
    "EBBOSmokeSettings",
    "EvaluationStatus",
    "MOCK_COST_UNIT",
    "MOCK_ORACLE_VERSION",
    "MockExpensiveOracle",
    "MockOracleOutcome",
    "MockSearchSpace",
    "NearestObservationSurrogate",
    "NoCandidateError",
    "Observation",
    "ObservationStore",
    "OracleRequest",
    "OracleResult",
    "SURROGATE_VERSION",
    "SerialScheduler",
    "SurrogatePrediction",
    "SurrogateSample",
    "build_candidate_pool",
    "canonical_json",
    "derive_seed",
    "load_ebbo_smoke_settings",
    "lower_confidence_bound",
    "run_ebbo_smoke",
    "stable_id",
    "strict_json_loads",
]
