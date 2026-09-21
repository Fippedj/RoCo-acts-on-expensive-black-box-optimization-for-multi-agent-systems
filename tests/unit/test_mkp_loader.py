from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from roco_ebbo.benchmarks import (
    FrozenMKPFile,
    MKPDataError,
    MKPInventoryContract,
    load_mkp_dataset,
)


def _write_fixture(root: Path, contents: dict[str, bytes]) -> MKPInventoryContract:
    root.mkdir()
    roles = {"c": "capacity", "w": "weight", "p": "profit", "s": "reference"}
    files: list[FrozenMKPFile] = []
    for filename, content in contents.items():
        (root / filename).write_bytes(content)
        suffix = filename.removesuffix(".txt").rsplit("_", 1)[1]
        files.append(
            FrozenMKPFile(
                instance_id="p99",
                filename=filename,
                role=roles[suffix],  # type: ignore[arg-type]
                byte_count=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                required=suffix != "s",
            )
        )
    return MKPInventoryContract(
        source_version="fixture-source-v1",
        protocol_version="fixture-protocol-v1",
        split_policy_version="fixture-protocol-only-v1",
        files=tuple(files),
    )


def _valid_contents() -> dict[str, bytes]:
    return {
        "p99_c.txt": b"5 7\n",
        "p99_w.txt": b"2 3 4\n",
        "p99_p.txt": b"4 5 8\n",
        "p99_s.txt": b"1 0\n0 1\n0 0\n",
    }


def test_loader_parses_explicit_checksum_contract_and_protocol_only_split(tmp_path: Path) -> None:
    contract = _write_fixture(tmp_path / "data", _valid_contents())

    dataset = load_mkp_dataset(tmp_path / "data", contract)

    assert len(dataset.instances) == 1
    instance = dataset.instances[0]
    assert instance.capacities == (5, 7)
    assert instance.weights == (2, 3, 4)
    assert instance.profits == (4, 5, 8)
    assert instance.split == "protocol-only"
    assert instance.reference_file is not None
    assert "optional_reference" in dataset.to_dict()["instances"][0]
    assert len(instance.checksum) == len(dataset.checksum) == 64


def test_loader_rejects_bad_hash_missing_and_unknown_files(tmp_path: Path) -> None:
    root = tmp_path / "bad-hash"
    contract = _write_fixture(root, _valid_contents())
    (root / "p99_c.txt").write_bytes(b"6 7\n")
    with pytest.raises(MKPDataError, match="checksum_mismatch") as checksum_error:
        load_mkp_dataset(root, contract)
    assert checksum_error.value.to_dict()["filename"] == "p99_c.txt"

    missing_root = tmp_path / "missing"
    missing_contract = _write_fixture(missing_root, _valid_contents())
    (missing_root / "p99_w.txt").unlink()
    with pytest.raises(MKPDataError, match="missing_file"):
        load_mkp_dataset(missing_root, missing_contract)

    unknown_root = tmp_path / "unknown"
    unknown_contract = _write_fixture(unknown_root, _valid_contents())
    (unknown_root / "unexpected.txt").write_text("1\n", encoding="utf-8")
    with pytest.raises(MKPDataError, match="unknown_file"):
        load_mkp_dataset(unknown_root, unknown_contract)


@pytest.mark.parametrize(
    ("updates", "error"),
    [
        ({"p99_p.txt": b"4 nope 8\n"}, "non_integer_token"),
        ({"p99_p.txt": b"4 5\n"}, "length_mismatch"),
        ({"p99_c.txt": b"5 -7\n"}, "negative_capacity"),
        ({"p99_w.txt": b"2 -3 4\n"}, "negative_weight"),
    ],
)
def test_loader_rejects_bad_numeric_structure(
    tmp_path: Path, updates: dict[str, bytes], error: str
) -> None:
    contents = {**_valid_contents(), **updates}
    contract = _write_fixture(tmp_path / error, contents)

    with pytest.raises(MKPDataError, match=error):
        load_mkp_dataset(tmp_path / error, contract)


def test_loader_rejects_an_empty_numeric_file(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    contract = _write_fixture(root, _valid_contents())
    (root / "p99_p.txt").write_bytes(b"")

    with pytest.raises(MKPDataError, match="empty_file"):
        load_mkp_dataset(root, contract)


def test_optional_reference_may_be_absent_but_must_be_valid_when_present(tmp_path: Path) -> None:
    root = tmp_path / "optional"
    contract = _write_fixture(root, _valid_contents())
    (root / "p99_s.txt").unlink()
    dataset = load_mkp_dataset(root, contract)
    assert dataset.instances[0].reference_file is not None
    assert dataset.instances[0].reference_file["present"] is False

    invalid_root = tmp_path / "duplicate-reference"
    invalid = {**_valid_contents(), "p99_s.txt": b"1 1\n0 0\n0 0\n"}
    invalid_contract = _write_fixture(invalid_root, invalid)
    with pytest.raises(MKPDataError, match="duplicate_reference_assignment"):
        load_mkp_dataset(invalid_root, invalid_contract)
