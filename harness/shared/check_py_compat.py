"""Gate: first-party Python must import on the oldest runtime the CI matrix claims to support.

Static type checkers do not catch this class of bug, because it is a *runtime* failure:
`def f(x: str | None)` is evaluated when the module is imported, so on Python 3.9/3.10 it
raises `TypeError: unsupported operand type(s) for |`. The same applies to `datetime.UTC`,
which only exists on 3.11+. Both slipped through this repo before: a 3.9 job stayed green
only because the module that would have failed was skipped.

The minimum supported version is *derived* from the CI workflow matrix rather than hard-coded,
so the gate and the matrix can never disagree. Bump the matrix and this gate follows.

Checks (each only applies when the resolved minimum version is old enough to care):

* `pep604` - PEP 604 unions (`X | Y`) in runtime-evaluated annotation positions in a module
  that lacks `from __future__ import annotations`. Requires 3.10+.
* `datetime-utc` - importing `UTC` from `datetime`. Requires 3.11+.

Exit codes: 0 = compatible, 1 = incompatible construct found.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from harness.shared.json_logging import LOG_LEVEL_ENV_VAR, resolve_log_level
except ImportError:  # direct `python harness/shared/<gate>.py`: sys.path[0] is this dir
    from json_logging import LOG_LEVEL_ENV_VAR, resolve_log_level  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_RELDIR = Path(".github") / "workflows"
POLICY_RELPATH = Path("harness") / "shared" / "governance-policy.json"

# Directories that are not first-party source under governance.
DEFAULT_SKIP_DIRS = frozenset(
    {".venv", ".git", "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache", "scratch", "build", "dist"}
)

PEP604_MIN = (3, 10)
DATETIME_UTC_MIN = (3, 11)

_MATRIX_VERSION_RE = re.compile(r"['\"](\d+)\.(\d+)['\"]")


@dataclass
class CompatReport:
    """Structured findings so CI, tests, and agents can consume the same result."""

    min_version: tuple[int, int] | None = None
    scanned: int = 0
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "min_version": ".".join(str(p) for p in self.min_version) if self.min_version else None,
            "scanned": self.scanned,
            "violations": self.violations,
        }


def _parse_matrix_versions(text: str) -> list[tuple[int, int]]:
    """Extract python-version entries from a workflow file.

    Uses PyYAML when available and falls back to a regex so the gate has no hard
    dependency the CI image might lack.
    """
    versions: list[tuple[int, int]] = []
    try:
        # Optional dependency, imported lazily: the regex fallback below keeps this gate
        # working on CI images that do not install PyYAML, so no stubs are required.
        import yaml  # type: ignore[import-untyped]  # noqa: PLC0415

        doc = yaml.safe_load(text) or {}
        for job in (doc.get("jobs") or {}).values():
            entries = (((job or {}).get("strategy") or {}).get("matrix") or {}).get("python-version")
            if isinstance(entries, list):
                for item in entries:
                    parts = str(item).split(".")
                    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                        versions.append((int(parts[0]), int(parts[1])))
        if versions:
            return versions
    except ImportError:
        logger.debug("PyYAML unavailable; falling back to regex matrix parsing")
    except Exception as e:  # noqa: BLE001 - malformed workflow must not crash the gate
        logger.debug("YAML parse failed (%s); falling back to regex", e)

    for line in text.splitlines():
        if "python-version" in line:
            versions.extend((int(a), int(b)) for a, b in _MATRIX_VERSION_RE.findall(line))
    return versions


def resolve_min_version(repo_root: Path, override: str | None = None) -> tuple[int, int] | None:
    """Resolve the oldest Python the project claims to support.

    Precedence: explicit override > `MIN_PYTHON` env > lowest version in any CI
    workflow matrix. Returns None when nothing declares a version.
    """
    raw = override or os.environ.get("MIN_PYTHON")
    if raw:
        parts = str(raw).split(".")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return (int(parts[0]), int(parts[1]))
        logger.warning("Ignoring unparseable minimum version %r", raw)

    found: list[tuple[int, int]] = []
    wf_dir = repo_root / WORKFLOW_RELDIR
    if wf_dir.is_dir():
        for wf in sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))):
            try:
                found.extend(_parse_matrix_versions(wf.read_text(encoding="utf-8")))
            except Exception as e:  # noqa: BLE001
                logger.debug("Could not read %s: %s", wf, e)
    if not found:
        logger.warning("No python-version matrix found under %s; compatibility gate is a no-op", WORKFLOW_RELDIR)
        return None
    return min(found)


def load_skip_dirs(repo_root: Path) -> frozenset[str]:
    """Skip directories, extendable via policy `py_compat.skip_dirs`."""
    skip = set(DEFAULT_SKIP_DIRS)
    try:
        policy = json.loads((repo_root / POLICY_RELPATH).read_text(encoding="utf-8"))
        if not isinstance(policy, dict):
            raise TypeError(f"policy root must be a JSON object, got {type(policy).__name__}")
        extra = (policy.get("py_compat") or {}).get("skip_dirs") or []
        if isinstance(extra, list):
            skip.update(str(x) for x in extra)
    except FileNotFoundError:
        pass  # Absent policy is the adopter path; the built-in skip set applies.
    except OSError as e:
        # Present but unreadable (permissions, I/O) is not the adopter path either.
        logger.error("[FAIL] Could not read governance policy: %s", e)
        raise SystemExit(1) from e
    except (ValueError, TypeError) as e:
        # Present but unparseable is corruption: silently using the built-in set
        # could skip directories the policy meant to scan. Fail closed.
        logger.error("[FAIL] Malformed governance policy: %s", e)
        raise SystemExit(1) from e
    return frozenset(skip)


def has_future_annotations(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def _runtime_annotations(tree: ast.Module):
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


def iter_python_files(repo_root: Path, skip_dirs: frozenset[str]):
    for path in sorted(repo_root.rglob("*.py")):
        if skip_dirs & set(path.relative_to(repo_root).parts):
            continue
        yield path


def run(repo_root: Path, min_version: tuple[int, int] | None, skip_dirs: frozenset[str] | None = None) -> CompatReport:
    """Scan first-party Python for constructs newer than `min_version`."""
    report = CompatReport(min_version=min_version)
    if min_version is None:
        return report
    skip_dirs = load_skip_dirs(repo_root) if skip_dirs is None else skip_dirs

    check_pep604 = min_version < PEP604_MIN
    check_utc = min_version < DATETIME_UTC_MIN
    if not (check_pep604 or check_utc):
        logger.info(
            "Minimum supported Python is %s; no legacy-runtime constructs to check.",
            ".".join(map(str, min_version)),
        )
        return report

    for path in iter_python_files(repo_root, skip_dirs):
        rel = path.relative_to(repo_root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            report.violations.append(f"{rel}:{e.lineno}: syntax error, cannot verify compatibility ({e.msg})")
            continue
        except Exception as e:  # noqa: BLE001
            logger.debug("Skipping unreadable %s: %s", rel, e)
            continue
        report.scanned += 1

        if check_utc:
            for lineno in find_datetime_utc(tree):
                report.violations.append(
                    f"{rel}:{lineno}: `from datetime import UTC` requires Python 3.11+, "
                    f"but the matrix supports {'.'.join(map(str, min_version))}; use `timezone.utc`"
                )
        if check_pep604:
            if not has_future_annotations(tree):
                for lineno in find_pep604(tree):
                    report.violations.append(
                        f"{rel}:{lineno}: PEP 604 union (`X | Y`) is evaluated at runtime and requires "
                        f"Python 3.10+; add `from __future__ import annotations` or use typing.Optional/Union"
                    )
            for lineno in find_pep604_assignments(tree):
                report.violations.append(
                    f"{rel}:{lineno}: runtime type alias with PEP 604 union (`X | Y`) is evaluated at import time "
                    f"and requires Python 3.10+; use typing.Union or TypeAlias with string annotations"
                )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify first-party Python imports on the oldest supported runtime.")
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--min-version", default=None, help="override the minimum version, e.g. 3.9")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    parser.add_argument("--log-level", default=os.environ.get(LOG_LEVEL_ENV_VAR, "INFO"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # resolve_log_level degrades an unusable level to the default; passing the raw
    # string to basicConfig raised ValueError, turning LOG_LEVEL=BOGUS into a red gate.
    logging.basicConfig(level=resolve_log_level(str(args.log_level)), format="%(levelname)s: %(message)s")

    repo_root = args.repo_root.resolve()
    min_version = resolve_min_version(repo_root, args.min_version)
    report = run(repo_root, min_version)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))

    for violation in report.violations:
        logger.error("[FAIL] %s", violation)

    if report.ok:
        logger.info(
            "[PASS] %d file(s) compatible with Python %s.",
            report.scanned,
            ".".join(map(str, min_version)) if min_version else "(undeclared)",
        )
        return 0
    logger.error("[FAIL] %d compatibility violation(s) found.", len(report.violations))
    return 1


if __name__ == "__main__":
    sys.exit(main())
