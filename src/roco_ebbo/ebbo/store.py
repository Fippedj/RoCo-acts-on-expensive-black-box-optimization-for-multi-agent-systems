"""Append-only local audit and observation storage for P9a."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from roco_ebbo.ebbo.contracts import (
    JsonValue,
    Observation,
    canonical_json,
    require_json_safe,
    stable_id,
    strict_json_loads,
)

AUDIT_EVENT_VERSION = "ebbo-audit-event-v1"
STORE_SNAPSHOT_VERSION = "ebbo-observation-store-snapshot-v1"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One deterministic transition record; timestamp is explicitly non-replay state."""

    schema_version: str
    event_id: str
    sequence: int
    kind: str
    payload: dict[str, JsonValue]
    recorded_at_utc: str | None = None

    @classmethod
    def create(
        cls,
        sequence: int,
        kind: str,
        payload: dict[str, JsonValue],
        *,
        recorded_at_utc: str | None = None,
    ) -> AuditEvent:
        if type(sequence) is not int or sequence < 0:
            raise ValueError("audit sequence must be a non-negative integer")
        if not kind:
            raise ValueError("audit kind must be non-empty")
        require_json_safe(payload)
        content: dict[str, JsonValue] = {
            "schema_version": AUDIT_EVENT_VERSION,
            "sequence": sequence,
            "kind": kind,
            "payload": payload,
        }
        return cls(
            schema_version=AUDIT_EVENT_VERSION,
            event_id=stable_id("audit", content),
            sequence=sequence,
            kind=kind,
            payload=payload,
            recorded_at_utc=recorded_at_utc,
        )

    def replay_dict(self) -> dict[str, JsonValue]:
        value = self.to_dict()
        value.pop("recorded_at_utc")
        return value

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "kind": self.kind,
            "payload": self.payload,
            "recorded_at_utc": self.recorded_at_utc,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, value: str | bytes) -> AuditEvent:
        decoded = strict_json_loads(value)
        if not isinstance(decoded, dict):
            raise ValueError("audit JSON must contain an object")
        expected = {
            "schema_version",
            "event_id",
            "sequence",
            "kind",
            "payload",
            "recorded_at_utc",
        }
        if set(decoded) != expected:
            raise ValueError("audit event schema mismatch")
        if decoded["schema_version"] != AUDIT_EVENT_VERSION:
            raise ValueError("unsupported audit event schema")
        if type(decoded["sequence"]) is not int or decoded["sequence"] < 0:
            raise ValueError("audit sequence must be a non-negative integer")
        if not isinstance(decoded["kind"], str) or not decoded["kind"]:
            raise ValueError("audit kind must be non-empty")
        if not isinstance(decoded["payload"], dict):
            raise ValueError("audit payload must be an object")
        timestamp = decoded["recorded_at_utc"]
        if timestamp is not None and not isinstance(timestamp, str):
            raise ValueError("audit timestamp must be a string or null")
        content = {
            key: item for key, item in decoded.items() if key not in {"event_id", "recorded_at_utc"}
        }
        if decoded["event_id"] != stable_id("audit", content):
            raise ValueError("audit event_id does not match its content")
        return cls(
            schema_version=AUDIT_EVENT_VERSION,
            event_id=cast(str, decoded["event_id"]),
            sequence=cast(int, decoded["sequence"]),
            kind=cast(str, decoded["kind"]),
            payload=cast(dict[str, JsonValue], decoded["payload"]),
            recorded_at_utc=timestamp,
        )


class ObservationStore:
    """Two append-only JSONL streams with strict validation on open and append."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.root / "audit.jsonl"
        self.observations_path = self.root / "observations.jsonl"
        self._events = self._read_audit()
        self._observations = self._read_observations()
        self._event_ids = {event.event_id for event in self._events}
        self._observation_ids = {item.observation_id for item in self._observations}
        if len(self._event_ids) != len(self._events):
            raise ValueError("audit stream contains duplicate event IDs")
        if len(self._observation_ids) != len(self._observations):
            raise ValueError("observation stream contains duplicate observation IDs")
        if [event.sequence for event in self._events] != list(range(len(self._events))):
            raise ValueError("audit stream sequence is not contiguous")

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(AuditEvent.from_json(event.to_json()) for event in self._events)

    @property
    def observations(self) -> tuple[Observation, ...]:
        return tuple(Observation.from_json(item.to_json()) for item in self._observations)

    def append_audit(self, event: AuditEvent) -> None:
        if event.sequence != len(self._events):
            raise ValueError("audit sequence must append contiguously")
        if event.event_id in self._event_ids:
            raise ValueError("audit event is already present")
        encoded = event.to_json()
        validated = AuditEvent.from_json(encoded)
        self._append_line(self.audit_path, encoded)
        self._events.append(validated)
        self._event_ids.add(event.event_id)

    def append_observation(self, observation: Observation) -> None:
        if observation.observation_id in self._observation_ids:
            raise ValueError("observation is already present")
        if any(item.attempt_id == observation.attempt_id for item in self._observations):
            raise ValueError("accepted attempt already has an observation")
        if observation.completion_sequence != len(self._observations):
            raise ValueError("observation completion_sequence must append contiguously")
        encoded = observation.to_json()
        validated = Observation.from_json(encoded)
        self._append_line(self.observations_path, encoded)
        self._observations.append(validated)
        self._observation_ids.add(observation.observation_id)

    def snapshot(self) -> dict[str, JsonValue]:
        audit_bytes = self.audit_path.read_bytes() if self.audit_path.exists() else b""
        observation_bytes = (
            self.observations_path.read_bytes() if self.observations_path.exists() else b""
        )
        return {
            "schema_version": STORE_SNAPSHOT_VERSION,
            "audit_events": len(self._events),
            "observations": len(self._observations),
            "audit_sha256": hashlib.sha256(audit_bytes).hexdigest(),
            "observations_sha256": hashlib.sha256(observation_bytes).hexdigest(),
            "last_event_id": self._events[-1].event_id if self._events else None,
            "last_observation_id": (
                self._observations[-1].observation_id if self._observations else None
            ),
        }

    def semantic_snapshot(self) -> dict[str, JsonValue]:
        return {
            "schema_version": STORE_SNAPSHOT_VERSION,
            "audit": [event.replay_dict() for event in self._events],
            "observations": [item.replay_dict() for item in self._observations],
        }

    def replay_checksum(self, ledger: dict[str, JsonValue]) -> str:
        payload: JsonValue = {"store": self.semantic_snapshot(), "ledger": ledger}
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def _read_audit(self) -> list[AuditEvent]:
        if not self.audit_path.exists():
            return []
        return [AuditEvent.from_json(line) for line in _read_nonempty_lines(self.audit_path)]

    def _read_observations(self) -> list[Observation]:
        if not self.observations_path.exists():
            return []
        return [
            Observation.from_json(line) for line in _read_nonempty_lines(self.observations_path)
        ]

    @staticmethod
    def _append_line(path: Path, encoded: str) -> None:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.write("\n")


def _read_nonempty_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if any(not line for line in lines):
        raise ValueError(f"append-only store contains a blank record: {path.name}")
    return lines
