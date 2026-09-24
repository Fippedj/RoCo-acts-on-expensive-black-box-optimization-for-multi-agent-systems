"""Dependency-free deterministic surrogate, acquisition, and candidate pool."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from roco_ebbo.ebbo.contracts import JsonValue, derive_seed, stable_id
from roco_ebbo.ebbo.ledger import EBBOLedger

MOCK_SEARCH_SPACE_VERSION = "ebbo-mock-integer-space-v1"
SURROGATE_VERSION = "ebbo-nearest-observation-surrogate-v1"
ACQUISITION_VERSION = "ebbo-lower-confidence-bound-v1"
CANDIDATE_POOL_VERSION = "ebbo-candidate-pool-v1"


@dataclass(frozen=True, slots=True)
class MockSearchSpace:
    """Finite engineering-only integer space; it is not an external benchmark."""

    lower: int = -5
    upper: int = 5

    def __post_init__(self) -> None:
        if type(self.lower) is not int or type(self.upper) is not int or self.lower >= self.upper:
            raise ValueError("mock integer bounds must be integers with lower < upper")

    @property
    def problem_id(self) -> str:
        return f"mock-quadratic-engineering-v1:x={self.lower}..{self.upper}"

    @property
    def diameter(self) -> int:
        return self.upper - self.lower

    def candidate(self, x: int) -> dict[str, JsonValue]:
        if type(x) is not int or x < self.lower or x > self.upper:
            raise ValueError("candidate x is outside the finite mock search space")
        return {"x": x}

    def candidate_id(self, candidate: dict[str, JsonValue]) -> str:
        self.validate_candidate(candidate)
        return stable_id(
            "candidate",
            {"search_space_version": MOCK_SEARCH_SPACE_VERSION, "candidate": candidate},
        )

    def validate_candidate(self, candidate: dict[str, JsonValue]) -> int:
        if set(candidate) != {"x"} or type(candidate["x"]) is not int:
            raise ValueError("mock candidate must contain exactly one integer x")
        x = candidate["x"]
        assert isinstance(x, int)
        if x < self.lower or x > self.upper:
            raise ValueError("candidate x is outside the finite mock search space")
        return x

    def ordered_unseen(
        self,
        *,
        root_seed: int,
        iteration: int,
        excluded_candidate_ids: set[str],
    ) -> tuple[dict[str, JsonValue], ...]:
        candidates = [
            self.candidate(x)
            for x in range(self.lower, self.upper + 1)
            if self.candidate_id(self.candidate(x)) not in excluded_candidate_ids
        ]
        candidates.sort(
            key=lambda item: (
                derive_seed(root_seed, "candidate-order", iteration, self.candidate_id(item)),
                self.candidate_id(item),
            )
        )
        return tuple(candidates)


@dataclass(frozen=True, slots=True)
class SurrogateSample:
    candidate_id: str
    x: int
    objective: float
    observation_id: str

    def __post_init__(self) -> None:
        if type(self.x) is not int or not math.isfinite(self.objective):
            raise ValueError("surrogate sample must contain an integer x and finite objective")


@dataclass(frozen=True, slots=True)
class SurrogatePrediction:
    mean: float
    uncertainty: float
    source_observation_id: str | None


@dataclass(frozen=True, slots=True)
class NearestObservationSurrogate:
    """Auditable 1-nearest-observation engineering surrogate."""

    search_space: MockSearchSpace
    prior_mean: float
    samples: tuple[SurrogateSample, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.prior_mean):
            raise ValueError("prior_mean must be finite")
        candidate_ids = [sample.candidate_id for sample in self.samples]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("surrogate samples must have unique candidate IDs")

    def predict(self, candidate: dict[str, JsonValue]) -> SurrogatePrediction:
        x = self.search_space.validate_candidate(candidate)
        if not self.samples:
            return SurrogatePrediction(self.prior_mean, 1.0, None)
        nearest = min(
            self.samples,
            key=lambda sample: (abs(sample.x - x), sample.observation_id),
        )
        uncertainty = abs(nearest.x - x) / self.search_space.diameter
        return SurrogatePrediction(nearest.objective, uncertainty, nearest.observation_id)

    def updated(self, sample: SurrogateSample) -> NearestObservationSurrogate:
        return NearestObservationSurrogate(
            search_space=self.search_space,
            prior_mean=self.prior_mean,
            samples=(*self.samples, sample),
        )


@dataclass(frozen=True, slots=True)
class CandidatePoolEntry:
    candidate_id: str
    candidate: Mapping[str, JsonValue]
    predicted_mean: float
    uncertainty: float
    acquisition_score: float

    def __post_init__(self) -> None:
        if set(self.candidate) != {"x"} or type(self.candidate["x"]) is not int:
            raise ValueError("P9a pool entry requires exactly one integer x")
        object.__setattr__(self, "candidate", MappingProxyType(dict(self.candidate)))
        values = (self.predicted_mean, self.uncertainty, self.acquisition_score)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("candidate-pool scores must be finite")
        if self.uncertainty < 0:
            raise ValueError("candidate-pool uncertainty must be non-negative")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "candidate_id": self.candidate_id,
            "candidate": dict(self.candidate),
            "predicted_mean": self.predicted_mean,
            "uncertainty": self.uncertainty,
            "acquisition_score": self.acquisition_score,
        }


@dataclass(frozen=True, slots=True)
class CandidatePool:
    """Finite immutable pool sorted by acquisition score then stable candidate ID."""

    pool_id: str
    entries: tuple[CandidatePoolEntry, ...]
    proposals_received: int
    duplicates_removed: int

    @classmethod
    def create(
        cls,
        proposals: tuple[CandidatePoolEntry, ...],
        *,
        ledger: EBBOLedger,
    ) -> CandidatePool:
        ledger.record_candidate_proposal(len(proposals))
        unique: dict[str, CandidatePoolEntry] = {}
        for proposal in proposals:
            existing = unique.get(proposal.candidate_id)
            if existing is not None and existing.to_dict() != proposal.to_dict():
                raise ValueError("candidate ID collision inside candidate pool")
            unique.setdefault(proposal.candidate_id, proposal)
        entries = tuple(
            sorted(unique.values(), key=lambda item: (item.acquisition_score, item.candidate_id))
        )
        content: JsonValue = {
            "schema_version": CANDIDATE_POOL_VERSION,
            "entries": [entry.to_dict() for entry in entries],
            "proposals_received": len(proposals),
            "duplicates_removed": len(proposals) - len(entries),
        }
        return cls(
            pool_id=stable_id("pool", content),
            entries=entries,
            proposals_received=len(proposals),
            duplicates_removed=len(proposals) - len(entries),
        )

    @property
    def selected(self) -> CandidatePoolEntry:
        if not self.entries:
            raise LookupError("candidate pool has no entries")
        return self.entries[0]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": CANDIDATE_POOL_VERSION,
            "pool_id": self.pool_id,
            "entries": [entry.to_dict() for entry in self.entries],
            "proposals_received": self.proposals_received,
            "duplicates_removed": self.duplicates_removed,
            "tie_break": "acquisition_score-ascending-then-candidate_id-ascending",
        }


def lower_confidence_bound(prediction: SurrogatePrediction, beta: float) -> float:
    """Return minimization LCB = mean - beta * uncertainty."""

    if not math.isfinite(beta) or beta < 0:
        raise ValueError("LCB beta must be finite and non-negative")
    score = prediction.mean - beta * prediction.uncertainty
    if not math.isfinite(score):
        raise ValueError("LCB score must be finite")
    return score


def build_candidate_pool(
    *,
    search_space: MockSearchSpace,
    surrogate: NearestObservationSurrogate,
    root_seed: int,
    iteration: int,
    pool_size: int,
    beta: float,
    excluded_candidate_ids: set[str],
    ledger: EBBOLedger,
) -> CandidatePool:
    if type(pool_size) is not int or pool_size < 1:
        raise ValueError("pool_size must be a positive integer")
    candidates = search_space.ordered_unseen(
        root_seed=root_seed,
        iteration=iteration,
        excluded_candidate_ids=excluded_candidate_ids,
    )[:pool_size]
    proposals: list[CandidatePoolEntry] = []
    for candidate in candidates:
        prediction = surrogate.predict(candidate)
        proposals.append(
            CandidatePoolEntry(
                candidate_id=search_space.candidate_id(candidate),
                candidate=candidate,
                predicted_mean=prediction.mean,
                uncertainty=prediction.uncertainty,
                acquisition_score=lower_confidence_bound(prediction, beta),
            )
        )
    return CandidatePool.create(tuple(proposals), ledger=ledger)
