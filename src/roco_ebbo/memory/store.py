"""Immutable generation storage and recovery for Stage 4 memory."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from roco_ebbo.memory.models import MemoryEvent, RoleMemorySummary

CHECKPOINT_SCHEMA_VERSION = "roco-memory-checkpoint-v1"
COMMIT_SCHEMA_VERSION = "roco-memory-commit-v1"
MEMORY_ROLES = ("explorer", "exploiter", "integrator")
_ARTIFACT_KEYS = (
    "events",
    "summary_explorer",
    "summary_exploiter",
    "summary_integrator",
    "checkpoint",
)
_EVENT_NAME = re.compile(r"^generation-(\d{6,})\.jsonl$")
_SUMMARY_NAME = re.compile(r"^generation-(\d{6,})-(explorer|exploiter|integrator)\.json$")
_JSON_NAME = re.compile(r"^generation-(\d{6,})\.json$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MemoryStoreError(RuntimeError):
    """Base class for immutable memory-store failures."""


class StoreValidationError(MemoryStoreError):
    """An on-disk generation or persistence payload failed validation."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_artifact",
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


class GenerationNotCommittedError(StoreValidationError):
    """The requested generation has no commit marker."""

    def __init__(self, generation: int, path: str) -> None:
        super().__init__(
            f"generation {generation} has no commit marker",
            code="missing_commit",
            path=path,
        )
        self.generation = generation


class StoreConflictError(MemoryStoreError):
    """An immutable path already contains different or invalid content."""


@dataclass(frozen=True, slots=True)
class MemoryCheckpoint:
    """Portable state required to resume after one committed generation."""

    generation: int
    population: dict[str, Any]
    budget_ledger: dict[str, Any]
    random_streams: dict[str, dict[str, Any]]
    provider_snapshots: dict[str, dict[str, Any]]

    schema_version: ClassVar[str] = CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_generation(self.generation)
        _require_mapping(self.population, "checkpoint population")
        _validate_checkpoint_population(self.population)
        _require_mapping(self.budget_ledger, "checkpoint budget_ledger")
        _require_snapshot_collection(self.random_streams, "checkpoint random_streams")
        _require_snapshot_collection(self.provider_snapshots, "checkpoint provider_snapshots")
        object.__setattr__(self, "population", _clone_json(self.population))
        object.__setattr__(self, "budget_ledger", _clone_json(self.budget_ledger))
        object.__setattr__(self, "random_streams", _clone_json(self.random_streams))
        object.__setattr__(self, "provider_snapshots", _clone_json(self.provider_snapshots))

    @classmethod
    def create(
        cls,
        generation: int,
        population: Any,
        budget_ledger: Any,
        *,
        random_streams: Mapping[str, Any] | None = None,
        provider_snapshots: Mapping[str, Any] | None = None,
    ) -> MemoryCheckpoint:
        """Capture explicit public snapshots, never private RNG or pickle state."""

        return cls(
            generation=generation,
            population=_take_snapshot(population, "population"),
            budget_ledger=_take_snapshot(budget_ledger, "budget ledger"),
            random_streams=_take_named_snapshots(random_streams or {}, "random stream"),
            provider_snapshots=_take_named_snapshots(provider_snapshots or {}, "provider"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generation": self.generation,
            "population": _clone_json(self.population),
            "budget_ledger": _clone_json(self.budget_ledger),
            "random_streams": _clone_json(self.random_streams),
            "provider_snapshots": _clone_json(self.provider_snapshots),
        }

    def to_json(self) -> str:
        return _canonical_json_text(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> MemoryCheckpoint:
        data = _require_mapping(value, "memory checkpoint")
        _require_exact_keys(
            data,
            {
                "schema_version",
                "generation",
                "population",
                "budget_ledger",
                "random_streams",
                "provider_snapshots",
            },
            "memory checkpoint",
        )
        if data["schema_version"] != cls.schema_version:
            raise ValueError("unsupported memory checkpoint schema_version")
        return cls(
            generation=data["generation"],
            population=_require_mapping(data["population"], "checkpoint population"),
            budget_ledger=_require_mapping(data["budget_ledger"], "checkpoint budget_ledger"),
            random_streams=_require_mapping(data["random_streams"], "checkpoint random_streams"),
            provider_snapshots=_require_mapping(
                data["provider_snapshots"], "checkpoint provider_snapshots"
            ),
        )

    @classmethod
    def from_json(cls, value: str | bytes) -> MemoryCheckpoint:
        return cls.from_dict(_strict_json_object(value, "memory checkpoint"))

    def restore(self) -> RestoredCheckpoint:
        """Restore Stage 3 runtime values through their public snapshot APIs."""

        from roco_ebbo.core.models import BudgetLedger
        from roco_ebbo.evolution.engine import Population

        return RestoredCheckpoint(
            population=Population.from_snapshot(_clone_json(self.population)),
            budget_ledger=BudgetLedger.from_snapshot(_clone_json(self.budget_ledger)),
            random_streams=_clone_json(self.random_streams),
            provider_snapshots=_clone_json(self.provider_snapshots),
        )

    def restore_population(self) -> Any:
        return self.restore().population

    def restore_budget_ledger(self) -> Any:
        return self.restore().budget_ledger


@dataclass(frozen=True, slots=True)
class RestoredCheckpoint:
    """Decoded checkpoint state with tuple-unpacking compatibility."""

    population: Any
    budget_ledger: Any
    random_streams: dict[str, dict[str, Any]]
    provider_snapshots: dict[str, dict[str, Any]]

    def __iter__(self) -> Iterator[Any]:
        yield self.population
        yield self.budget_ledger


@dataclass(frozen=True, slots=True)
class ArtifactDigest:
    """Hash and byte length for one path relative to the store root."""

    path: str
    byte_length: int
    sha256: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.path)
        if type(self.byte_length) is not int or self.byte_length < 0:
            raise ValueError("artifact byte_length must be a non-negative integer")
        if not isinstance(self.sha256, str) or _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("artifact sha256 must be a lowercase SHA-256 digest")

    @classmethod
    def from_bytes(cls, path: str, value: bytes) -> ArtifactDigest:
        return cls(path, len(value), hashlib.sha256(value).hexdigest())

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ArtifactDigest:
        data = _require_mapping(value, "artifact manifest entry")
        _require_exact_keys(data, {"path", "byte_length", "sha256"}, "artifact manifest")
        return cls(data["path"], data["byte_length"], data["sha256"])


@dataclass(frozen=True, slots=True)
class GenerationCommit:
    """Commit-last marker for one immutable generation."""

    generation: int
    artifacts: dict[str, ArtifactDigest]
    event_count: int
    config_hash: str
    population_ids: tuple[str, ...]
    budget_snapshot: dict[str, Any]

    schema_version: ClassVar[str] = COMMIT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_generation(self.generation)
        if set(self.artifacts) != set(_ARTIFACT_KEYS):
            raise ValueError("commit artifact keys do not match the generation schema")
        if not all(isinstance(item, ArtifactDigest) for item in self.artifacts.values()):
            raise ValueError("commit artifacts must contain ArtifactDigest values")
        if type(self.event_count) is not int or self.event_count < 0:
            raise ValueError("commit event_count must be a non-negative integer")
        _require_sha256(self.config_hash, "commit config_hash")
        if not all(isinstance(item, str) for item in self.population_ids):
            raise ValueError("commit population_ids must contain strings")
        _require_mapping(self.budget_snapshot, "commit budget_snapshot")
        object.__setattr__(self, "artifacts", dict(self.artifacts))
        object.__setattr__(self, "budget_snapshot", _clone_json(self.budget_snapshot))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generation": self.generation,
            "artifacts": {key: self.artifacts[key].to_dict() for key in _ARTIFACT_KEYS},
            "event_count": self.event_count,
            "config_hash": self.config_hash,
            "population_ids": list(self.population_ids),
            "budget_snapshot": _clone_json(self.budget_snapshot),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GenerationCommit:
        data = _require_mapping(value, "generation commit")
        _require_exact_keys(
            data,
            {
                "schema_version",
                "generation",
                "artifacts",
                "event_count",
                "config_hash",
                "population_ids",
                "budget_snapshot",
            },
            "generation commit",
        )
        if data["schema_version"] != cls.schema_version:
            raise ValueError("unsupported generation commit schema_version")
        artifacts = _require_mapping(data["artifacts"], "commit artifacts")
        population_ids = data["population_ids"]
        if not isinstance(population_ids, list):
            raise ValueError("commit population_ids must be a list")
        return cls(
            generation=data["generation"],
            artifacts={key: ArtifactDigest.from_dict(item) for key, item in artifacts.items()},
            event_count=data["event_count"],
            config_hash=data["config_hash"],
            population_ids=tuple(population_ids),
            budget_snapshot=_require_mapping(data["budget_snapshot"], "commit budget_snapshot"),
        )


@dataclass(frozen=True, slots=True)
class GenerationRecord:
    """A fully validated generation and its decoded artifacts."""

    generation: int
    events: tuple[MemoryEvent, ...]
    summaries: dict[str, RoleMemorySummary]
    checkpoint: MemoryCheckpoint
    commit: GenerationCommit

    def summary(self, role: str) -> RoleMemorySummary:
        return self.summaries[_role_name(role)]


GenerationReadResult = GenerationRecord


@dataclass(frozen=True, slots=True)
class CommitResult:
    """Outcome of publishing or replaying one generation commit."""

    generation: int
    commit_path: Path
    idempotent: bool
    record: GenerationRecord

    @property
    def created(self) -> bool:
        return not self.idempotent


@dataclass(frozen=True, slots=True)
class ScanIssue:
    """A non-mutating diagnostic found while scanning the store."""

    code: str
    message: str
    generation: int | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True)
class ScanReport:
    """Continuous committed prefix plus diagnostics for discovered files."""

    records: tuple[GenerationRecord, ...]
    issues: tuple[ScanIssue, ...]

    @property
    def visible_generations(self) -> tuple[int, ...]:
        return tuple(record.generation for record in self.records)

    @property
    def generations(self) -> tuple[int, ...]:
        return self.visible_generations

    @property
    def latest(self) -> GenerationRecord | None:
        return self.records[-1] if self.records else None


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Runtime objects and portable cursors restored from a checkpoint."""

    generation: int
    population: Any
    budget_ledger: Any
    random_streams: dict[str, dict[str, Any]]
    provider_snapshots: dict[str, dict[str, Any]]
    checkpoint: MemoryCheckpoint
    scan_report: ScanReport

    @property
    def next_generation(self) -> int:
        return self.generation + 1


class GenerationMemoryStore:
    """Commit and recover immutable, hash-verified generation artifacts."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self._root_anchor = self.root.resolve(strict=False)

    def commit_generation(
        self,
        generation: int,
        events: Sequence[MemoryEvent],
        summaries: Mapping[Any, RoleMemorySummary],
        checkpoint: MemoryCheckpoint | Mapping[str, Any],
        config_hash: str,
    ) -> CommitResult:
        """Publish all artifacts and then the commit marker."""

        _require_generation(generation)
        _require_sha256(config_hash, "config_hash")
        resolved_checkpoint = (
            checkpoint
            if isinstance(checkpoint, MemoryCheckpoint)
            else MemoryCheckpoint.from_dict(checkpoint)
        )
        resolved_checkpoint = MemoryCheckpoint.from_dict(resolved_checkpoint.to_dict())
        if resolved_checkpoint.generation != generation:
            raise ValueError("checkpoint generation does not match commit generation")

        ordered_events = _normalize_events(events, generation)
        normalized_summaries = _normalize_summaries(summaries, generation)
        resolved_checkpoint.restore()

        relative_paths = _generation_artifact_paths(generation)
        payloads: dict[str, bytes] = {
            "events": _event_segment_bytes(ordered_events),
            "summary_explorer": _json_document_bytes(normalized_summaries["explorer"].to_dict()),
            "summary_exploiter": _json_document_bytes(normalized_summaries["exploiter"].to_dict()),
            "summary_integrator": _json_document_bytes(
                normalized_summaries["integrator"].to_dict()
            ),
            "checkpoint": _json_document_bytes(resolved_checkpoint.to_dict()),
        }
        commit = GenerationCommit(
            generation=generation,
            artifacts={
                key: ArtifactDigest.from_bytes(relative_paths[key], payloads[key])
                for key in _ARTIFACT_KEYS
            },
            event_count=len(ordered_events),
            config_hash=config_hash,
            population_ids=_population_ids(resolved_checkpoint.population),
            budget_snapshot=resolved_checkpoint.budget_ledger,
        )
        commit_payload = _json_document_bytes(commit.to_dict())
        commit_relative = _commit_path(generation)
        commit_path = self._path(commit_relative)

        if commit_path.exists() or commit_path.is_symlink():
            try:
                current = self._read_generation_independent(generation)
            except MemoryStoreError as exc:
                raise StoreConflictError(
                    f"generation {generation} has an existing invalid commit: {exc}"
                ) from exc
            if current.commit.to_dict() != commit.to_dict():
                raise StoreConflictError(
                    f"generation {generation} is already committed with different content"
                )
            for key, payload in payloads.items():
                path = self._path(relative_paths[key])
                if _read_regular_file(path, relative_paths[key]) != payload:
                    raise StoreConflictError(f"committed artifact differs at {relative_paths[key]}")
            return CommitResult(generation, commit_path, True, current)

        self._ensure_layout()
        # Check every orphan final before publishing anything.
        for key, payload in payloads.items():
            path = self._path(relative_paths[key])
            if path.exists() or path.is_symlink():
                if _read_regular_file(path, relative_paths[key]) != payload:
                    raise StoreConflictError(
                        f"uncommitted artifact differs at {relative_paths[key]}"
                    )

        artifact_directories: set[Path] = set()
        for key in _ARTIFACT_KEYS:
            path = self._path(relative_paths[key])
            self._publish_if_absent(path, payloads[key], relative_paths[key])
            artifact_directories.add(path.parent)
        # Matching orphan finals are reused rather than rewritten, but their
        # directory entries must still be durable before the marker is visible.
        for directory in sorted(artifact_directories, key=str):
            _fsync_directory(directory)

        # The marker is intentionally the final rename and directory fsync.
        if not self._publish_if_absent(commit_path, commit_payload, commit_relative):
            if _read_regular_file(commit_path, commit_relative) != commit_payload:
                raise StoreConflictError(
                    f"generation {generation} commit appeared with different content"
                )
        _fsync_directory(commit_path.parent)
        record = self._read_generation_independent(generation)
        return CommitResult(generation, commit_path, False, record)

    def read_generation(self, generation: int) -> GenerationRecord:
        """Read a generation only when it belongs to the valid continuous prefix."""

        _require_generation(generation)
        report = self.scan()
        for record in report.records:
            if record.generation == generation:
                return record
        for issue in report.issues:
            if issue.generation == generation:
                raise StoreValidationError(
                    f"generation {generation} is not visible: {issue.message}",
                    code=issue.code,
                    path=issue.path,
                )
        raise GenerationNotCommittedError(generation, _commit_path(generation))

    def scan(self) -> ScanReport:
        """Return the valid prefix from generation zero without mutating files."""

        discovered, commits, artifacts, issues = self._discover()
        visible: list[GenerationRecord] = []
        valid_commits: set[int] = set()
        expected = 0
        continuous = True
        for generation in sorted(discovered):
            if continuous and generation > expected:
                issues.append(
                    ScanIssue(
                        "noncontinuous_generation",
                        f"generation {generation} occurs after missing generation {expected}",
                        generation,
                    )
                )
                continuous = False

            record: GenerationRecord | None = None
            if generation not in commits:
                issues.append(
                    ScanIssue(
                        "missing_commit",
                        f"generation {generation} has artifacts but no commit marker",
                        generation,
                        _commit_path(generation),
                    )
                )
            else:
                try:
                    record = self._read_generation_independent(generation)
                    valid_commits.add(generation)
                except StoreValidationError as exc:
                    issues.append(ScanIssue(exc.code, str(exc), generation, exc.path))
                except MemoryStoreError as exc:
                    issues.append(
                        ScanIssue(
                            "invalid_commit",
                            str(exc),
                            generation,
                            _commit_path(generation),
                        )
                    )

            if continuous and generation == expected and record is not None:
                visible.append(record)
                expected += 1
            else:
                if record is not None and not any(
                    issue.code == "noncontinuous_generation" and issue.generation == generation
                    for issue in issues
                ):
                    issues.append(
                        ScanIssue(
                            "noncontinuous_generation",
                            (f"generation {generation} is valid but outside the continuous prefix"),
                            generation,
                            _commit_path(generation),
                        )
                    )
                continuous = False

        for generation, paths in sorted(artifacts.items()):
            if generation in valid_commits:
                continue
            for relative_path in sorted(paths):
                issues.append(
                    ScanIssue(
                        "orphan_artifact",
                        f"artifact is not covered by a valid commit: {relative_path}",
                        generation,
                        relative_path,
                    )
                )
        return ScanReport(tuple(visible), tuple(issues))

    scan_committed = scan

    def recover(self) -> RecoveryResult | None:
        """Restore the last checkpoint in the valid continuous prefix."""

        report = self.scan()
        latest = report.latest
        if latest is None:
            return None
        restored = latest.checkpoint.restore()
        return RecoveryResult(
            generation=latest.generation,
            population=restored.population,
            budget_ledger=restored.budget_ledger,
            random_streams=restored.random_streams,
            provider_snapshots=restored.provider_snapshots,
            checkpoint=latest.checkpoint,
            scan_report=report,
        )

    def _read_generation_independent(self, generation: int) -> GenerationRecord:
        relative_paths = _generation_artifact_paths(generation)
        commit_relative = _commit_path(generation)
        commit_path = self._path(commit_relative)
        if not commit_path.exists() and not commit_path.is_symlink():
            raise GenerationNotCommittedError(generation, commit_relative)

        commit_bytes = _read_regular_file(commit_path, commit_relative)
        try:
            commit_value = _strict_json_object(commit_bytes, "generation commit")
            if commit_bytes != _json_document_bytes(commit_value):
                raise ValueError("commit marker is not canonical JSON with one trailing newline")
            commit = GenerationCommit.from_dict(commit_value)
        except (TypeError, ValueError) as exc:
            raise StoreValidationError(
                f"invalid commit marker for generation {generation}: {exc}",
                code="invalid_commit",
                path=commit_relative,
            ) from exc
        if commit.generation != generation:
            raise StoreValidationError(
                "commit generation does not match its filename",
                code="invalid_commit",
                path=commit_relative,
            )

        artifact_bytes: dict[str, bytes] = {}
        for key in _ARTIFACT_KEYS:
            manifest = commit.artifacts[key]
            expected_relative = relative_paths[key]
            if manifest.path != expected_relative:
                raise StoreValidationError(
                    f"commit artifact path mismatch for {key}",
                    code="invalid_commit",
                    path=commit_relative,
                )
            artifact_path = self._path(manifest.path)
            if not artifact_path.exists() and not artifact_path.is_symlink():
                raise StoreValidationError(
                    f"committed artifact is missing: {manifest.path}",
                    code="missing_artifact",
                    path=manifest.path,
                )
            value = _read_regular_file(artifact_path, manifest.path)
            if (
                len(value) != manifest.byte_length
                or hashlib.sha256(value).hexdigest() != manifest.sha256
            ):
                raise StoreValidationError(
                    f"artifact hash or length mismatch: {manifest.path}",
                    code="bad_hash",
                    path=manifest.path,
                )
            artifact_bytes[key] = value

        try:
            events = _parse_event_segment(artifact_bytes["events"])
            summaries = {
                role: _parse_summary(artifact_bytes[f"summary_{role}"], role, generation)
                for role in MEMORY_ROLES
            }
            checkpoint = _parse_checkpoint(artifact_bytes["checkpoint"])
            _validate_loaded_generation(generation, events, summaries, checkpoint)
            checkpoint.restore()
        except (TypeError, ValueError) as exc:
            raise StoreValidationError(
                f"invalid generation {generation} artifact content: {exc}",
                code="invalid_artifact",
            ) from exc

        if len(events) != commit.event_count:
            raise StoreValidationError(
                "commit event_count does not match the event segment",
                code="invalid_commit",
                path=commit_relative,
            )
        if commit.population_ids != _population_ids(checkpoint.population):
            raise StoreValidationError(
                "commit population_ids do not match the checkpoint",
                code="invalid_commit",
                path=commit_relative,
            )
        if _canonical_json_bytes(commit.budget_snapshot) != _canonical_json_bytes(
            checkpoint.budget_ledger
        ):
            raise StoreValidationError(
                "commit budget_snapshot does not match the checkpoint",
                code="invalid_commit",
                path=commit_relative,
            )
        return GenerationRecord(generation, events, summaries, checkpoint, commit)

    def _ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise StoreValidationError("memory store root is not a directory")
        for name in ("events", "summaries", "checkpoints", "commits"):
            path = self.root / name
            path.mkdir(exist_ok=True)
            self._assert_contained(path)
            if not path.is_dir() or path.is_symlink():
                raise StoreValidationError(
                    f"memory store component is not a real directory: {name}",
                    code="unsafe_path",
                    path=name,
                )
        _fsync_directory(self.root)

    def _path(self, relative_path: str) -> Path:
        _validate_relative_path(relative_path)
        path = self.root.joinpath(*PurePosixPath(relative_path).parts)
        self._assert_contained(path)
        return path

    def _assert_contained(self, path: Path) -> None:
        try:
            path.resolve(strict=False).relative_to(self._root_anchor)
        except ValueError as exc:
            raise StoreValidationError(
                f"path escapes memory store root: {path}", code="unsafe_path"
            ) from exc

    def _publish_if_absent(self, path: Path, value: bytes, relative_path: str) -> bool:
        if path.exists() or path.is_symlink():
            if _read_regular_file(path, relative_path) == value:
                return False
            raise StoreConflictError(f"immutable artifact differs at {relative_path}")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            if path.exists() or path.is_symlink():
                if _read_regular_file(path, relative_path) == value:
                    return False
                raise StoreConflictError(f"immutable artifact differs at {relative_path}")
            os.replace(temporary_path, path)
            return True
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

    def _discover(
        self,
    ) -> tuple[set[int], set[int], dict[int, set[str]], list[ScanIssue]]:
        discovered: set[int] = set()
        commits: set[int] = set()
        artifacts: dict[int, set[str]] = {}
        issues: list[ScanIssue] = []
        if not self.root.exists():
            return discovered, commits, artifacts, issues
        if not self.root.is_dir():
            issues.append(
                ScanIssue("unsafe_path", "memory store root is not a directory", path=".")
            )
            return discovered, commits, artifacts, issues

        directories = {
            "events": _EVENT_NAME,
            "summaries": _SUMMARY_NAME,
            "checkpoints": _JSON_NAME,
            "commits": _JSON_NAME,
        }
        for directory_name, pattern in directories.items():
            directory = self.root / directory_name
            if not directory.exists():
                continue
            if not directory.is_dir() or directory.is_symlink():
                issues.append(
                    ScanIssue(
                        "unsafe_path",
                        f"store component is not a real directory: {directory_name}",
                        path=directory_name,
                    )
                )
                continue
            for item in sorted(directory.iterdir(), key=lambda child: child.name):
                relative = item.relative_to(self.root).as_posix()
                if item.name.endswith(".tmp"):
                    issues.append(
                        ScanIssue(
                            "temporary_artifact",
                            f"ignored temporary artifact: {relative}",
                            _generation_from_loose_name(item.name),
                            relative,
                        )
                    )
                    continue
                match = pattern.fullmatch(item.name)
                if match is None or item.is_dir():
                    issues.append(
                        ScanIssue(
                            "orphan_artifact",
                            f"ignored unrecognized artifact: {relative}",
                            _generation_from_loose_name(item.name),
                            relative,
                        )
                    )
                    continue
                generation = int(match.group(1))
                discovered.add(generation)
                if directory_name == "commits":
                    commits.add(generation)
                else:
                    artifacts.setdefault(generation, set()).add(relative)
        return discovered, commits, artifacts, issues


def _generation_artifact_paths(generation: int) -> dict[str, str]:
    stem = f"generation-{generation:06d}"
    return {
        "events": f"events/{stem}.jsonl",
        "summary_explorer": f"summaries/{stem}-explorer.json",
        "summary_exploiter": f"summaries/{stem}-exploiter.json",
        "summary_integrator": f"summaries/{stem}-integrator.json",
        "checkpoint": f"checkpoints/{stem}.json",
    }


def _commit_path(generation: int) -> str:
    return f"commits/generation-{generation:06d}.json"


def _normalize_events(events: Sequence[MemoryEvent], generation: int) -> tuple[MemoryEvent, ...]:
    if isinstance(events, (str, bytes)) or not isinstance(events, Sequence):
        raise ValueError("events must be a sequence of MemoryEvent values")
    supplied = tuple(events)
    if not all(isinstance(event, MemoryEvent) for event in supplied):
        raise ValueError("events must contain only MemoryEvent values")
    seen: dict[str, bytes] = {}
    for event in supplied:
        encoded = _canonical_json_bytes(event.to_dict())
        previous = seen.get(event.event_id)
        if previous is not None:
            detail = "collision" if previous != encoded else "duplicate"
            raise StoreConflictError(f"memory event ID {detail}: {event.event_id}")
        seen[event.event_id] = encoded
    resolved = tuple(MemoryEvent.from_dict(event.to_dict()) for event in supplied)
    for event in resolved:
        if event.generation != generation:
            raise ValueError("memory event generation does not match commit generation")
    ordered = tuple(sorted(resolved, key=_event_sort_key))
    return ordered


def _normalize_summaries(
    summaries: Mapping[Any, RoleMemorySummary], generation: int
) -> dict[str, RoleMemorySummary]:
    if not isinstance(summaries, Mapping):
        raise ValueError("summaries must be a role mapping")
    resolved: dict[str, RoleMemorySummary] = {}
    for key, summary in summaries.items():
        role = _role_name(key)
        if role in resolved:
            raise ValueError(f"duplicate role summary: {role}")
        if not isinstance(summary, RoleMemorySummary):
            raise ValueError("summaries must contain only RoleMemorySummary values")
        summary = RoleMemorySummary.from_dict(summary.to_dict())
        if _role_name(summary.role) != role:
            raise ValueError(f"summary role does not match mapping key: {role}")
        if summary.through_generation > generation:
            raise ValueError("summary cannot include a future generation")
        resolved[role] = summary
    if set(resolved) != set(MEMORY_ROLES):
        raise ValueError("exactly one explorer, exploiter, and integrator summary is required")
    return resolved


def _validate_loaded_generation(
    generation: int,
    events: tuple[MemoryEvent, ...],
    summaries: dict[str, RoleMemorySummary],
    checkpoint: MemoryCheckpoint,
) -> None:
    if checkpoint.generation != generation:
        raise ValueError("checkpoint generation does not match its artifact filename")
    normalized = _normalize_events(events, generation)
    if tuple(event.event_id for event in events) != tuple(event.event_id for event in normalized):
        raise ValueError("event segment is not in canonical event order")
    _normalize_summaries(summaries, generation)


def _event_sort_key(event: MemoryEvent) -> tuple[int, int, int, str]:
    return event.generation, event.round, event.sequence, event.event_id


def _event_segment_bytes(events: Sequence[MemoryEvent]) -> bytes:
    return b"".join(_canonical_json_bytes(event.to_dict()) + b"\n" for event in events)


def _parse_event_segment(value: bytes) -> tuple[MemoryEvent, ...]:
    if not value:
        return ()
    events: list[MemoryEvent] = []
    for line_number, line in enumerate(value.splitlines(keepends=True), start=1):
        if not line.endswith(b"\n") or line.endswith(b"\r\n"):
            raise ValueError(f"event line {line_number} does not have a canonical newline")
        document = line[:-1]
        if not document:
            raise ValueError(f"event line {line_number} is empty")
        item = _strict_json_object(document, f"memory event line {line_number}")
        if _canonical_json_bytes(item) != document:
            raise ValueError(f"event line {line_number} is not canonical JSON")
        events.append(MemoryEvent.from_dict(item))
    return tuple(events)


def _parse_summary(value: bytes, role: str, generation: int) -> RoleMemorySummary:
    item = _strict_json_object(value, f"{role} role summary")
    if value != _json_document_bytes(item):
        raise ValueError(f"{role} summary is not canonical JSON with one trailing newline")
    summary = RoleMemorySummary.from_dict(item)
    if _role_name(summary.role) != role:
        raise ValueError(f"{role} summary artifact contains a different role")
    if summary.through_generation > generation:
        raise ValueError(f"{role} summary includes a future generation")
    return summary


def _parse_checkpoint(value: bytes) -> MemoryCheckpoint:
    item = _strict_json_object(value, "memory checkpoint")
    if value != _json_document_bytes(item):
        raise ValueError("checkpoint is not canonical JSON with one trailing newline")
    return MemoryCheckpoint.from_dict(item)


def _population_ids(population: Mapping[str, Any]) -> tuple[str, ...]:
    candidates = population.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("population snapshot candidates must be a list")
    identifiers: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str):
            raise ValueError("population snapshot candidate must contain a string id")
        identifiers.append(candidate["id"])
    return tuple(identifiers)


def _validate_checkpoint_population(population: Mapping[str, Any]) -> None:
    _require_exact_keys(population, {"size", "minimize", "candidates"}, "checkpoint population")
    size = population["size"]
    candidates = population["candidates"]
    if type(size) is not int or size < 2:
        raise ValueError("checkpoint population size must be an integer of at least 2")
    if population["minimize"] is not True:
        raise ValueError("checkpoint population must use the minimize objective")
    if not isinstance(candidates, list) or len(candidates) != size:
        raise ValueError("checkpoint population must contain its complete selected population")
    identifiers: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("checkpoint population candidates must be JSON objects")
        identifier = candidate.get("id")
        score = candidate.get("score")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("checkpoint population candidate IDs must be non-empty strings")
        if identifier in identifiers:
            raise ValueError("checkpoint population candidate IDs must be unique")
        identifiers.add(identifier)
        if type(score) not in (int, float):
            raise ValueError("checkpoint population candidates must have finite selected scores")
        assert isinstance(score, (int, float))
        if not math.isfinite(score):
            raise ValueError("checkpoint population candidates must have finite selected scores")


def _take_snapshot(value: Any, name: str) -> dict[str, Any]:
    method = getattr(value, "to_snapshot", None)
    if not callable(method):
        raise ValueError(f"{name} does not expose to_snapshot()")
    return _require_mapping(method(), f"{name} snapshot")


def _take_named_snapshots(values: Mapping[str, Any], name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(values, Mapping) or not all(isinstance(key, str) for key in values):
        raise ValueError(f"{name} snapshots must be a string-keyed mapping")
    snapshots: dict[str, dict[str, Any]] = {}
    for key, value in values.items():
        method = getattr(value, "to_snapshot", None)
        snapshot = method() if callable(method) else value
        snapshots[key] = _require_mapping(snapshot, f"{name} snapshot {key!r}")
    return snapshots


def _require_snapshot_collection(value: Any, name: str) -> None:
    mapping = _require_mapping(value, name)
    for key, snapshot in mapping.items():
        if not isinstance(key, str):
            raise ValueError(f"{name} keys must be strings")
        _require_mapping(snapshot, f"{name} entry {key!r}")


def _role_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    if not isinstance(raw, str):
        raise ValueError("memory role must be a string or string-valued enum")
    role = raw.lower()
    if role not in MEMORY_ROLES:
        raise ValueError(f"unsupported memory role: {raw!r}")
    return role


def _canonical_json_text(value: Any) -> str:
    _require_json_safe(value)
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_json_bytes(value: Any) -> bytes:
    return _canonical_json_text(value).encode("utf-8")


def _json_document_bytes(value: Any) -> bytes:
    return _canonical_json_bytes(value) + b"\n"


def _strict_json_object(value: str | bytes, name: str) -> dict[str, Any]:
    try:
        decoded = json.loads(
            value,
            parse_constant=_raise_nonfinite,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{name} is not strict JSON: {exc}") from exc
    return _require_mapping(decoded, name)


def _raise_nonfinite(token: str) -> Any:
    raise ValueError(f"non-finite JSON number is forbidden: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} keys must be strings")
    result = dict(value)
    _require_json_safe(result)
    return result


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{name} keys do not match its schema")


def _require_generation(value: Any) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("generation must be a non-negative integer")


def _require_sha256(value: Any, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_json_safe(value: Any) -> None:
    if value is None or type(value) is bool or type(value) is int:
        return
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("JSON strings must be valid UTF-8") from exc
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite numbers are forbidden at the JSON boundary")
        return
    if isinstance(value, list):
        for item in value:
            _require_json_safe(item)
        return
    if isinstance(value, dict):
        if not all(type(key) is str for key in value):
            raise ValueError("JSON object keys must be plain strings")
        for key, item in value.items():
            try:
                key.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("JSON object keys must be valid UTF-8") from exc
            _require_json_safe(item)
        return
    raise ValueError(f"non-JSON value is forbidden: {type(value).__name__}")


def _clone_json(value: Any) -> Any:
    _require_json_safe(value)
    if isinstance(value, list):
        return [_clone_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _clone_json(item) for key, item in value.items()}
    return value


def _validate_relative_path(value: Any) -> None:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("artifact path must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("artifact path traversal is forbidden")
    if path.as_posix() != value:
        raise ValueError("artifact path must be normalized POSIX syntax")


def _read_regular_file(path: Path, display_path: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise StoreValidationError(
            f"artifact is missing: {display_path}",
            code="missing_artifact",
            path=display_path,
        ) from None
    except OSError as exc:
        raise StoreValidationError(
            f"artifact cannot be opened safely: {display_path}: {exc}",
            code="unsafe_path",
            path=display_path,
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise StoreValidationError(
                f"artifact is not a regular file: {display_path}",
                code="unsafe_path",
                path=display_path,
            )
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _generation_from_loose_name(name: str) -> int | None:
    match = re.search(r"generation-(\d{6,})", name)
    return int(match.group(1)) if match is not None else None


__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "COMMIT_SCHEMA_VERSION",
    "MEMORY_ROLES",
    "ArtifactDigest",
    "CommitResult",
    "GenerationCommit",
    "GenerationMemoryStore",
    "GenerationNotCommittedError",
    "GenerationReadResult",
    "GenerationRecord",
    "MemoryCheckpoint",
    "MemoryStoreError",
    "RecoveryResult",
    "RestoredCheckpoint",
    "ScanIssue",
    "ScanReport",
    "StoreConflictError",
    "StoreValidationError",
]
