"""Tests for harness/shared/governance_json.py - the shared, non-raising JSON classifier.

governance/broker.py's and check_dedup.py's own test suites exercise this module only
indirectly, through their respective callers, and neither ever triggers a non-missing
OSError (e.g. a permission error) -- the "unreadable" branch has no direct coverage
anywhere else. These tests exercise every branch of read_json_object() directly.
"""

import dataclasses
from pathlib import Path

import pytest

from harness.shared import governance_json as gj


def test_reads_a_valid_json_object(tmp_path: Path) -> None:
    target = tmp_path / "policy.json"
    target.write_text('{"a": 1, "b": [2, 3]}', encoding="utf-8")

    result = gj.read_json_object(target)

    assert result.error is None
    assert result.value == {"a": 1, "b": [2, 3]}


def test_missing_file_is_classified_not_found(tmp_path: Path) -> None:
    target = tmp_path / "absent.json"

    result = gj.read_json_object(target)

    assert result.error == "not_found"
    assert result.value is None
    assert str(target) in result.detail


def test_unreadable_path_is_classified_unreadable_not_not_found(tmp_path: Path) -> None:
    """A directory is a portable way to force a non-FileNotFoundError OSError:
    unlike a chmod'd file, IsADirectoryError fires the same way whether or not
    the caller happens to be running as root, where permission bits are bypassed.
    """
    target = tmp_path / "a_directory"
    target.mkdir()

    result = gj.read_json_object(target)

    assert result.error == "unreadable"
    assert result.value is None
    assert result.detail


def test_invalid_utf8_bytes_are_classified_malformed_not_raised(tmp_path: Path) -> None:
    """UnicodeDecodeError surfaces from `read_text()`, before `json.loads()` ever
    runs, and it is not an OSError -- a naive `except OSError` around the read
    would let it escape uncaught, breaking this function's own "never raises"
    contract. It is a ValueError subclass, the same family as a JSON syntax
    error, so it is classified the same way check_dedup treated it before this
    module existed: a present, readable file that is not valid policy content.
    """
    target = tmp_path / "bad_encoding.json"
    target.write_bytes(b"\xff\xfe{not valid utf-8")

    result = gj.read_json_object(target)

    assert result.error == "malformed"
    assert result.value is None
    assert result.detail


def test_invalid_json_syntax_is_classified_malformed(tmp_path: Path) -> None:
    target = tmp_path / "broken.json"
    target.write_text("{not json", encoding="utf-8")

    result = gj.read_json_object(target)

    assert result.error == "malformed"
    assert result.value is None


def test_valid_json_that_is_not_an_object_is_classified_malformed(tmp_path: Path) -> None:
    target = tmp_path / "array.json"
    target.write_text("[1, 2, 3]", encoding="utf-8")

    result = gj.read_json_object(target)

    assert result.error == "malformed"
    assert result.value is None
    assert "list" in result.detail


def test_valid_json_scalar_is_classified_malformed(tmp_path: Path) -> None:
    target = tmp_path / "scalar.json"
    target.write_text("42", encoding="utf-8")

    result = gj.read_json_object(target)

    assert result.error == "malformed"
    assert "int" in result.detail


def test_result_is_frozen(tmp_path: Path) -> None:
    """The dataclass is deliberately immutable -- a classification is a fact
    about one read, not a value a caller should mutate and reuse."""
    target = tmp_path / "policy.json"
    target.write_text("{}", encoding="utf-8")
    result = gj.read_json_object(target)

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.value = {"mutated": True}  # type: ignore[misc]
