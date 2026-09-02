"""Pure AST inspection helpers for detecting runtime-evaluated Python constructs.

Extracted from `check_py_compat.py` (R-GFD-4, `docs/specs/god-file-decomposition.md`):
these functions only walk an already-parsed `ast.Module` and return line numbers —
no file I/O, no policy loading, no CLI concerns. That separation lets the detection
logic be tested and reused (e.g. by an editor plugin or a different gate) without
pulling in `check_py_compat`'s workflow-matrix resolution or argument parsing.

Two runtime-evaluated constructs are detected:

* PEP 604 unions (`X | Y`) in annotation position (`find_pep604`) or as a runtime
  assignment (`find_pep604_assignments`) — both require Python 3.10+ unless the
  module carries `from __future__ import annotations` (which only defers
  annotation evaluation, not assignment evaluation).
* `from datetime import UTC` (`find_datetime_utc`) — requires Python 3.11+.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator


def has_future_annotations(tree: ast.Module) -> bool:
    """Return True if the module has `from __future__ import annotations`.

    That import defers annotation evaluation to string form, which is why
    `find_pep604` only applies to modules where this is False.
    """
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def _runtime_annotations(tree: ast.Module) -> Iterator[tuple[int, ast.expr]]:
    """Yield (lineno, annotation) pairs that Python evaluates at import time."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg):
                if arg is not None and arg.annotation is not None:
                    yield node.lineno, arg.annotation
            if node.returns is not None:
                yield node.lineno, node.returns
        # Module/class-level variable annotations (PEP 526) are also evaluated at
        # import time, so `x: str | None = ...` fails on 3.9 just like function args.
        elif isinstance(node, ast.AnnAssign) and node.annotation is not None:
            yield node.lineno, node.annotation


def find_pep604(tree: ast.Module) -> list[int]:
    """Return line numbers where a PEP 604 union is evaluated at runtime."""
    lines: set[int] = set()
    for lineno, annotation in _runtime_annotations(tree):
        for sub in ast.walk(annotation):
            if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                lines.add(lineno)
    return sorted(lines)


def find_datetime_utc(tree: ast.Module) -> list[int]:
    """Return line numbers importing `UTC` from datetime (3.11+ only)."""
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "datetime"
        and any(alias.name == "UTC" for alias in node.names)
    )


COMMON_TYPE_NAMES = frozenset(
    {"str", "int", "float", "bool", "bytes", "dict", "list", "set", "tuple", "Any", "Optional", "Union", "Path"}
)


def _is_type_name_identifier(name: str) -> bool:
    if name in COMMON_TYPE_NAMES:
        return True
    # PascalCase type names like MyClass, Path, TreeNode: starts with uppercase, but not ALL-CAPS constant
    if len(name) > 1 and name[0].isupper() and not name.isupper():
        return True
    return False


def _is_type_union_binop(binop: ast.BinOp) -> bool:
    """Check if a BinOp(BitOr) represents a PEP 604 type union in an assignment."""
    for side in (binop.left, binop.right):
        if isinstance(side, ast.Constant) and side.value is None:
            return True
        if isinstance(side, ast.Name) and _is_type_name_identifier(side.id):
            return True
        if isinstance(side, ast.Attribute) and _is_type_name_identifier(side.attr):
            return True
        if isinstance(side, ast.BinOp) and isinstance(side.op, ast.BitOr) and _is_type_union_binop(side):
            return True
    return False


def find_pep604_assignments(tree: ast.Module) -> list[int]:
    """Return line numbers where a runtime assignment creates a PEP 604 union (e.g. Alias = str | None)."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.AST):
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr) and _is_type_union_binop(sub):
                    lines.add(node.lineno)
    return sorted(lines)


__all__ = [
    "COMMON_TYPE_NAMES",
    "find_datetime_utc",
    "find_pep604",
    "find_pep604_assignments",
    "has_future_annotations",
]
