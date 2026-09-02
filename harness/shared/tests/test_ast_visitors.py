"""Tests for harness/shared/ast_visitors.py - pure AST inspection helpers.

Extracted from `check_py_compat.py` (R-GFD-4). `test_check_py_compat.py` keeps
exercising these functions through the `check_py_compat` re-export to pin
backward compatibility (R-GFD-7); this file tests the extracted module directly
so the detection logic has coverage independent of the gate that consumes it.
"""

import ast

from harness.shared import ast_visitors as av


def test_has_future_annotations_true():
    tree = ast.parse("from __future__ import annotations\n\ndef f(x: str | None) -> None: ...\n")
    assert av.has_future_annotations(tree) is True


def test_has_future_annotations_false_without_import():
    tree = ast.parse("def f(x: str) -> None: ...\n")
    assert av.has_future_annotations(tree) is False


def test_has_future_annotations_false_for_unrelated_future_import():
    tree = ast.parse("from __future__ import division\n")
    assert av.has_future_annotations(tree) is False


def test_find_pep604_detects_arg_annotation():
    tree = ast.parse("def f(x: str | None = None): ...\n")
    assert av.find_pep604(tree) == [1]


def test_find_pep604_detects_return_annotation():
    tree = ast.parse("def f() -> int | None: ...\n")
    assert av.find_pep604(tree) == [1]


def test_find_pep604_detects_module_level_annassign():
    tree = ast.parse("x: str | None = None\n")
    assert av.find_pep604(tree) == [1]


def test_find_pep604_clean_on_legacy_safe_code():
    tree = ast.parse("from typing import Optional\n\ndef f(x: Optional[str]) -> Optional[int]: ...\n")
    assert av.find_pep604(tree) == []


def test_find_pep604_ignores_non_union_binop():
    """A plain arithmetic `|` outside annotation position must not be flagged."""
    tree = ast.parse("flags = 1 | 2\n")
    assert av.find_pep604(tree) == []


def test_find_datetime_utc_detects_import():
    tree = ast.parse("from datetime import UTC, datetime\n")
    assert av.find_datetime_utc(tree) == [1]


def test_find_datetime_utc_ignores_other_datetime_imports():
    tree = ast.parse("from datetime import datetime, timezone\n")
    assert av.find_datetime_utc(tree) == []


def test_find_datetime_utc_ignores_unrelated_module():
    tree = ast.parse("from zoneinfo import UTC\n")
    assert av.find_datetime_utc(tree) == []


def test_find_pep604_assignments_detects_type_alias():
    tree = ast.parse("MyType = str | None\n")
    assert av.find_pep604_assignments(tree) == [1]


def test_find_pep604_assignments_ignores_plain_arithmetic():
    tree = ast.parse("flags = 1 | 2\n")
    assert av.find_pep604_assignments(tree) == []


def test_find_pep604_assignments_detects_attribute_operand():
    tree = ast.parse("import types\nAlias = types.NoneType | int\n")
    assert av.find_pep604_assignments(tree) == [2]


def test_find_pep604_assignments_detects_nested_union():
    tree = ast.parse("Alias = str | int | None\n")
    assert av.find_pep604_assignments(tree) == [1]


def test_common_type_names_contains_expected_builtins():
    assert {"str", "int", "Optional", "Union"} <= av.COMMON_TYPE_NAMES
