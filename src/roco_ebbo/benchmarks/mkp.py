"""Fail-closed loader for the frozen FSU 01 Multiple Knapsack snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

FSU_MKP_SOURCE_VERSION = "mkp-fsu-knapsack-multiple-v1"
FSU_MKP_PROTOCOL_VERSION = "mkp-fsu-protocol-v1"
FSU_MKP_SPLIT_POLICY_VERSION = "mkp-fsu-protocol-only-v1"
FSU_MKP_SOURCE_ID = "fsu-john-burkardt-knapsack-multiple"
FSU_MKP_SOURCE_RELEASE = "page-revised-2009-12-08;frozen-2026-09-21"
FSU_MKP_LICENSE_ID = "LGPL-3.0-only"
FSU_MKP_SOURCE_URL = "https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/"

FileRole = Literal["capacity", "weight", "profit", "reference"]
_INTEGER_TOKEN = re.compile(rb"[+-]?[0-9]+")
_MIN_INT64 = -(2**63)
_MAX_INT64 = 2**63 - 1


class MKPDataError(ValueError):
    """Safe structured error for provenance or parser failures."""

    def __init__(self, code: str, safe_message: str, *, filename: str | None = None) -> None:
        self.code = code
        self.safe_message = safe_message
        self.filename = filename
        suffix = "" if filename is None else f" ({filename})"
        super().__init__(f"{code}: {safe_message}{suffix}")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "phase": "dataset_load",
            "type": self.code,
            "safe_message": self.safe_message,
            "filename": self.filename,
        }


@dataclass(frozen=True, slots=True)
class FrozenMKPFile:
    """One byte-exact file in a versioned inventory contract."""

    instance_id: str
    filename: str
    role: FileRole
    byte_count: int
    sha256: str
    required: bool = True

    def __post_init__(self) -> None:
        if not self.instance_id or not self.filename or Path(self.filename).name != self.filename:
            raise ValueError("frozen MKP filenames and instance IDs must be non-empty basenames")
        if self.role not in {"capacity", "weight", "profit", "reference"}:
            raise ValueError("frozen MKP file role is invalid")
        if self.byte_count < 1 or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("frozen MKP file size/checksum is invalid")
        if self.role != "reference" and not self.required:
            raise ValueError("capacity, weight, and profit inputs must be required")

    @property
    def url(self) -> str:
        return f"{FSU_MKP_SOURCE_URL}{self.filename}"


@dataclass(frozen=True, slots=True)
class MKPInventoryContract:
    """Explicit inventory supplied to the parser; production uses the frozen constant."""

    source_version: str
    protocol_version: str
    split_policy_version: str
    files: tuple[FrozenMKPFile, ...]

    def __post_init__(self) -> None:
        if not self.source_version or not self.protocol_version or not self.split_policy_version:
            raise ValueError("MKP inventory versions must be non-empty")
        if not self.files:
            raise ValueError("MKP inventory must contain files")
        names = [item.filename for item in self.files]
        if len(names) != len(set(names)):
            raise ValueError("MKP inventory filenames must be unique")
        grouped: dict[str, set[str]] = {}
        for item in self.files:
            grouped.setdefault(item.instance_id, set()).add(item.role)
        for instance_id, roles in grouped.items():
            if not {"capacity", "weight", "profit"}.issubset(roles):
                raise ValueError(f"MKP inventory {instance_id} lacks a required input role")


def _file(
    instance_id: str,
    suffix: str,
    role: FileRole,
    byte_count: int,
    sha256: str,
    *,
    required: bool = True,
) -> FrozenMKPFile:
    return FrozenMKPFile(
        instance_id=instance_id,
        filename=f"{instance_id}_{suffix}.txt",
        role=role,
        byte_count=byte_count,
        sha256=sha256,
        required=required,
    )


FSU_MKP_V1_CONTRACT = MKPInventoryContract(
    source_version=FSU_MKP_SOURCE_VERSION,
    protocol_version=FSU_MKP_PROTOCOL_VERSION,
    split_policy_version=FSU_MKP_SPLIT_POLICY_VERSION,
    files=(
        _file(
            "p01",
            "c",
            "capacity",
            8,
            "d6c953e90bd72846a1505608d59e96e6fb8406e4dd6250e6368bbfa8aef83aaa",
        ),
        _file(
            "p01",
            "w",
            "weight",
            30,
            "5eb586c0c659c6d746e6eda5da0795812afc4c63791259a7c2a274fef6af5e60",
        ),
        _file(
            "p01",
            "p",
            "profit",
            29,
            "d9f102a31d73849425c2ce4a970a82f7b4b591f497980578dc4b1da3d1f110c8",
        ),
        _file(
            "p01",
            "s",
            "reference",
            40,
            "e65b1c47da5ca36f650c5a804d089d7187ed4665369fb24fb26477af885990c7",
            required=False,
        ),
        _file(
            "p02",
            "c",
            "capacity",
            12,
            "fd7f9550a013dc6b35c3ed6d9a87102965b5b3794953589f68f36fd564b1f9ab",
        ),
        _file(
            "p02",
            "w",
            "weight",
            30,
            "5eb586c0c659c6d746e6eda5da0795812afc4c63791259a7c2a274fef6af5e60",
        ),
        _file(
            "p02",
            "p",
            "profit",
            29,
            "d9f102a31d73849425c2ce4a970a82f7b4b591f497980578dc4b1da3d1f110c8",
        ),
        _file(
            "p03",
            "c",
            "capacity",
            13,
            "0f1114f6530d66a2785aba56885195818c8c5ee1998fac30a524a464dafa8a3c",
        ),
        _file(
            "p03",
            "w",
            "weight",
            30,
            "5eb586c0c659c6d746e6eda5da0795812afc4c63791259a7c2a274fef6af5e60",
        ),
        _file(
            "p03",
            "p",
            "profit",
            29,
            "d9f102a31d73849425c2ce4a970a82f7b4b591f497980578dc4b1da3d1f110c8",
        ),
        _file(
            "p04",
            "c",
            "capacity",
            4,
            "167918ace289465acd4dd6ab6587fe10bfe54bc475ad8074b049ac358f98f9e2",
        ),
        _file(
            "p04",
            "w",
            "weight",
            30,
            "5eb586c0c659c6d746e6eda5da0795812afc4c63791259a7c2a274fef6af5e60",
        ),
        _file(
            "p04",
            "p",
            "profit",
            29,
            "d9f102a31d73849425c2ce4a970a82f7b4b591f497980578dc4b1da3d1f110c8",
        ),
        _file(
            "p05",
            "c",
            "capacity",
            7,
            "3248423c1f2097f6592fd824017e5ef163e701066f3c2ee0b829e63159d4d518",
        ),
        _file(
            "p05",
            "w",
            "weight",
            18,
            "5820062de6534969e9eadad7d51f9ca47f057d3e78a9798f8d33d9b146915f03",
        ),
        _file(
            "p05",
            "p",
            "profit",
            24,
            "2fa85603a75194604399f7275c67dc5d1e020842008d6487398af8e7c4c6ab4d",
        ),
        _file(
            "p05",
            "s",
            "reference",
            24,
            "1c563c0ee92386add0ad598c2e2c9ff7df078f749e6384e20a8e15bbca44c95f",
            required=False,
        ),
        _file(
            "p06",
            "c",
            "capacity",
            9,
            "af1915196cb9572f0b4009a82d45ec3653dd8200bbae4475919c9cad6a6d2774",
        ),
        _file(
            "p06",
            "w",
            "weight",
            30,
            "7c7a64be6b196a1be701b413585679ef1826c2e9963cc9b81b52c73e7a8c8856",
        ),
        _file(
            "p06",
            "p",
            "profit",
            30,
            "72fc12193721214ff34fc1dec98af63dcf3d76cb3a71659b3d6458d8cea435cb",
        ),
        _file(
            "p06",
            "s",
            "reference",
            40,
            "e80639098e548ef7abe683b21ba2946ccbed4826a6c39c884b0e8818b1d563d8",
            required=False,
        ),
    ),
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MKPInstance:
    """Parsed immutable instance; optional reference contents are intentionally absent."""

    instance_id: str
    capacities: tuple[int, ...]
    weights: tuple[int, ...]
    profits: tuple[int, ...]
    input_files: tuple[dict[str, Any], ...]
    reference_file: dict[str, Any] | None
    protocol_version: str = FSU_MKP_PROTOCOL_VERSION
    split: str = "protocol-only"

    def __post_init__(self) -> None:
        if not self.instance_id or self.split != "protocol-only" or not self.protocol_version:
            raise MKPDataError("invalid_instance", "instance identity or protocol split is invalid")
        if not self.capacities or not self.weights or len(self.weights) != len(self.profits):
            raise MKPDataError(
                "length_mismatch",
                "capacities must be non-empty and weight/profit lengths must match",
            )
        if any(value < 0 for value in self.capacities):
            raise MKPDataError("negative_capacity", "capacities must be non-negative")
        if any(value < 0 for value in self.weights):
            raise MKPDataError("negative_weight", "weights must be non-negative")

    @property
    def item_count(self) -> int:
        return len(self.weights)

    @property
    def knapsack_count(self) -> int:
        return len(self.capacities)

    @property
    def checksum(self) -> str:
        return _canonical_sha256(
            {
                "protocol_version": self.protocol_version,
                "instance_id": self.instance_id,
                "split": self.split,
                "capacities": list(self.capacities),
                "weights": list(self.weights),
                "profits": list(self.profits),
                "input_files": list(self.input_files),
            }
        )

    def to_manifest_record(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "split": self.split,
            "knapsacks": self.knapsack_count,
            "items": self.item_count,
            "input_files": list(self.input_files),
            "optional_reference": self.reference_file,
            "instance_checksum": self.checksum,
        }


@dataclass(frozen=True, slots=True)
class MKPDatasetManifest:
    """Verified local inventory and protocol-only integration split."""

    source_version: str
    protocol_version: str
    split_policy_version: str
    files: tuple[dict[str, Any], ...]
    instances: tuple[MKPInstance, ...]

    def __post_init__(self) -> None:
        if not self.instances or any(
            instance.split != "protocol-only" for instance in self.instances
        ):
            raise MKPDataError(
                "invalid_split",
                "every frozen FSU MKP instance must use the protocol-only split",
            )
        ids = [instance.instance_id for instance in self.instances]
        checksums = [instance.checksum for instance in self.instances]
        if len(ids) != len(set(ids)) or len(checksums) != len(set(checksums)):
            raise MKPDataError(
                "duplicate_instance", "dataset instances and checksums must be unique"
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": "roco-mkp-dataset-manifest-v1",
            "benchmark": {
                "id": "mkp-01",
                "version": self.protocol_version,
                "source_id": FSU_MKP_SOURCE_ID,
                "source_version": self.source_version,
                "release": FSU_MKP_SOURCE_RELEASE,
                "license_id": FSU_MKP_LICENSE_ID,
            },
            "split_policy": {
                "version": self.split_policy_version,
                "only_split": "protocol-only",
                "train": False,
                "validation": False,
                "test": False,
                "purpose": "small offline integration validation only",
            },
            "files": list(self.files),
            "instances": [instance.to_manifest_record() for instance in self.instances],
        }

    @property
    def checksum(self) -> str:
        return _canonical_sha256(self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "inventory_checksum": self.checksum}


def load_fsu_mkp_dataset(data_root: str | Path) -> MKPDatasetManifest:
    """Load only the frozen P01--P06 snapshot from an explicit local directory."""

    dataset = load_mkp_dataset(data_root, FSU_MKP_V1_CONTRACT)
    if tuple(instance.instance_id for instance in dataset.instances) != (
        "p01",
        "p02",
        "p03",
        "p04",
        "p05",
        "p06",
    ):
        raise MKPDataError("inventory_mismatch", "FSU protocol requires exactly P01 through P06")
    return dataset


def load_mkp_dataset(
    data_root: str | Path,
    contract: MKPInventoryContract,
) -> MKPDatasetManifest:
    """Parse one explicit inventory contract; useful for self-contained fixture tests."""

    root = Path(data_root)
    if not root.is_dir() or root.is_symlink():
        raise MKPDataError("invalid_data_root", "data root must be an existing real directory")
    allowed_names = {item.filename for item in contract.files}
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise MKPDataError("data_root_unreadable", "data root cannot be enumerated") from exc
    unknown = [entry.name for entry in entries if entry.name not in allowed_names]
    if unknown:
        raise MKPDataError(
            "unknown_file",
            "data root contains a file outside the frozen inventory",
            filename=unknown[0],
        )

    parsed: dict[tuple[str, FileRole], tuple[int, ...]] = {}
    file_records: list[dict[str, Any]] = []
    for specification in contract.files:
        path = root / specification.filename
        if path.is_symlink():
            raise MKPDataError(
                "invalid_file_type",
                "inventory entry must be a regular non-symlink file",
                filename=specification.filename,
            )
        if not path.exists():
            if specification.required:
                raise MKPDataError(
                    "missing_file",
                    "required frozen input is missing",
                    filename=specification.filename,
                )
            file_records.append(_file_record(specification, present=False))
            continue
        if not path.is_file():
            raise MKPDataError(
                "invalid_file_type",
                "inventory entry must be a regular non-symlink file",
                filename=specification.filename,
            )
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise MKPDataError(
                "unreadable_file",
                "inventory entry cannot be read",
                filename=specification.filename,
            ) from exc
        values = _verify_and_parse(content, specification)
        parsed[(specification.instance_id, specification.role)] = values
        file_records.append(_file_record(specification, present=True))

    instances: list[MKPInstance] = []
    instance_ids = sorted({item.instance_id for item in contract.files})
    for instance_id in instance_ids:
        capacities = parsed[(instance_id, "capacity")]
        weights = parsed[(instance_id, "weight")]
        profits = parsed[(instance_id, "profit")]
        if len(weights) != len(profits):
            raise MKPDataError(
                "length_mismatch",
                "weight and profit token counts differ",
                filename=f"{instance_id}_w.txt/{instance_id}_p.txt",
            )
        if not capacities or not weights:
            raise MKPDataError("empty_vector", "capacity and item vectors must be non-empty")
        if any(value < 0 for value in capacities):
            raise MKPDataError(
                "negative_capacity",
                "capacity values must be non-negative",
                filename=f"{instance_id}_c.txt",
            )
        if any(value < 0 for value in weights):
            raise MKPDataError(
                "negative_weight",
                "weight values must be non-negative",
                filename=f"{instance_id}_w.txt",
            )
        reference = parsed.get((instance_id, "reference"))
        if reference is not None:
            _validate_reference_shape(reference, len(weights), len(capacities), instance_id)
        instance_specs = [item for item in contract.files if item.instance_id == instance_id]
        input_records = tuple(
            _file_record(item, present=True) for item in instance_specs if item.role != "reference"
        )
        reference_spec = next((item for item in instance_specs if item.role == "reference"), None)
        reference_record = (
            None
            if reference_spec is None
            else _file_record(reference_spec, present=reference is not None)
        )
        instances.append(
            MKPInstance(
                instance_id=instance_id,
                capacities=capacities,
                weights=weights,
                profits=profits,
                input_files=input_records,
                reference_file=reference_record,
                protocol_version=contract.protocol_version,
            )
        )
    return MKPDatasetManifest(
        source_version=contract.source_version,
        protocol_version=contract.protocol_version,
        split_policy_version=contract.split_policy_version,
        files=tuple(file_records),
        instances=tuple(instances),
    )


def _file_record(specification: FrozenMKPFile, *, present: bool) -> dict[str, Any]:
    return {
        "instance_id": specification.instance_id,
        "filename": specification.filename,
        "role": specification.role,
        "required": specification.required,
        "present": present,
        "byte_count": specification.byte_count,
        "sha256": specification.sha256,
        "url": specification.url,
    }


def _verify_and_parse(content: bytes, specification: FrozenMKPFile) -> tuple[int, ...]:
    if not content:
        raise MKPDataError(
            "empty_file", "inventory entry is empty", filename=specification.filename
        )
    if len(content) != specification.byte_count:
        raise MKPDataError(
            "byte_count_mismatch",
            "raw byte count does not match frozen provenance",
            filename=specification.filename,
        )
    checksum = hashlib.sha256(content).hexdigest()
    if checksum != specification.sha256:
        raise MKPDataError(
            "checksum_mismatch",
            "raw SHA-256 does not match frozen provenance",
            filename=specification.filename,
        )
    tokens = content.split()
    if not tokens:
        raise MKPDataError(
            "empty_file",
            "inventory entry contains no numeric tokens",
            filename=specification.filename,
        )
    values: list[int] = []
    for token in tokens:
        if _INTEGER_TOKEN.fullmatch(token) is None:
            raise MKPDataError(
                "non_integer_token",
                "inventory entry contains a non-integer token",
                filename=specification.filename,
            )
        value = int(token)
        if value < _MIN_INT64 or value > _MAX_INT64:
            raise MKPDataError(
                "integer_out_of_range",
                "integer token is outside the signed 64-bit contract",
                filename=specification.filename,
            )
        values.append(value)
    return tuple(values)


def _validate_reference_shape(
    values: tuple[int, ...],
    item_count: int,
    knapsack_count: int,
    instance_id: str,
) -> None:
    if len(values) != item_count * knapsack_count:
        raise MKPDataError(
            "reference_shape_mismatch",
            "optional reference shape does not match items times knapsacks",
            filename=f"{instance_id}_s.txt",
        )
    if any(value not in {0, 1} for value in values):
        raise MKPDataError(
            "invalid_reference",
            "optional reference must contain only zero/one assignment markers",
            filename=f"{instance_id}_s.txt",
        )
    for item in range(item_count):
        start = item * knapsack_count
        if sum(values[start : start + knapsack_count]) > 1:
            raise MKPDataError(
                "duplicate_reference_assignment",
                "optional reference assigns an item more than once",
                filename=f"{instance_id}_s.txt",
            )
