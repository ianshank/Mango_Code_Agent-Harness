#!/usr/bin/env python3
"""Which files the coverage floors judge -- the scope half of the coverage gate.

`coverage_gate.py` answers "what must the numbers be": it reads the policy's
`coverage.lines` / `coverage.branches` and compares them against the report's
totals. This module answers the prior question, "which files are those numbers
computed over", and it is a separate concern because every defect found in this
area has been a *scope* defect rather than a threshold one:

* a per-file waiver prefix written without its trailing slash silently waived
  every sibling whose name merely began the same way (DEC-032),
* a waiver set broad enough to cover everything reported ``[PASS] 0 file(s)``
  (DEC-032),
* an ``omit`` entry dropped a file from the per-file floor *and* raised the
  aggregate, because the uncovered lines it contributed vanished with it
  (gate-truthfulness R-GT-3).

Split out when `coverage_gate.py` reached 470 lines against a 500-line
`limits.size_budget_lines`, leaving one edit of headroom. The seam is the one
the defects already drew, not a line count: everything here decides membership,
nothing here decides a threshold.

Fail-closed throughout, and for the same reason as its sibling: absence of
evidence is never a pass. A report with no ``files`` block, a policy whose
extras block is malformed, a ``pyproject.toml`` with no declared source roots,
and a measured set that ends up empty each exit 1 with a reason.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import sys
from pathlib import Path, PurePath

logger = logging.getLogger(__name__)


def _read_text(path: Path, what: str) -> str:
    """Fail-closed read: an unreadable input exits 1 with a reason, never a default."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        logger.error("[FAIL] Could not read %s from %s: %s", what, path, e)
        raise SystemExit(1) from e


def _load_json_object(path: Path, what: str) -> dict:
    """Fail-closed read: any unreadable or non-object input exits 1 with a reason."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError(f"root must be a JSON object, got {type(data).__name__}")
        return data
    except (OSError, ValueError, TypeError) as e:
        logger.error("[FAIL] Could not read %s from %s: %s", what, path, e)
        raise SystemExit(1) from e


OPTIONAL_EXTRAS_KEY = "optional_extras"
_EXTRA_FIELDS = ("import_name", "deselect_env", "path_prefixes")


def _malformed_extra(policy_path: Path, name: object, why: str) -> SystemExit:
    logger.error(
        "[FAIL] Governance policy %s: coverage.%s[%r] %s", policy_path, OPTIONAL_EXTRAS_KEY, name, why
    )
    return SystemExit(1)


def optional_extra_waivers(
    policy_path: Path, environ: dict[str, str] | None = None
) -> dict[str, tuple[str, ...]]:
    """Per-file waivers for optional extras whose tests cannot run on this leg.

    Policy shape (``coverage.optional_extras``)::

        "optional_extras": {
          "langgraph": {
            "import_name": "langgraph",
            "deselect_env": "MANGO_CI_DESELECT_LANGGRAPH",
            "path_prefixes": ["harness/shared/langgraph/"]
          }
        }

    A CI leg whose interpreter cannot install an extra sets ``deselect_env`` to
    ``"1"``; conftest.py deselects the extra's tests on the same signal. The
    modules under ``path_prefixes`` then have no test that could execute, so
    holding them to the per-file lines floor there measures the interpreter,
    not the code. The waiver applies only when the env is set AND the extra is
    genuinely not importable, so a leg that has the library keeps enforcing.
    Aggregate floors and every other file are unaffected.

    Returns ``{extra: path_prefixes}`` for the extras waived in this process.
    An absent block waives nothing; a malformed one exits 1 (fail-closed, like
    every other reader in this module).
    """
    env = os.environ if environ is None else environ
    coverage = _load_json_object(policy_path, "governance policy").get("coverage")
    if not isinstance(coverage, dict):
        logger.error("[FAIL] Governance policy %s has no coverage block", policy_path)
        raise SystemExit(1)
    extras = coverage.get(OPTIONAL_EXTRAS_KEY, {})
    if not isinstance(extras, dict):
        raise _malformed_extra(policy_path, "*", "must be an object keyed by extra name")
    waived: dict[str, tuple[str, ...]] = {}
    for name, spec in extras.items():
        if not isinstance(spec, dict) or any(not isinstance(spec.get(f), (str, list)) for f in _EXTRA_FIELDS):
            raise _malformed_extra(policy_path, name, f"must declare {', '.join(_EXTRA_FIELDS)}")
        import_name, deselect_env, prefixes = (spec[f] for f in _EXTRA_FIELDS)
        if not isinstance(import_name, str) or not import_name or not isinstance(deselect_env, str) or not deselect_env:
            raise _malformed_extra(policy_path, name, "import_name and deselect_env must be non-empty strings")
        if not isinstance(prefixes, list) or not prefixes or any(not isinstance(p, str) or not p for p in prefixes):
            raise _malformed_extra(policy_path, name, "path_prefixes must be a non-empty list of non-empty strings")
        if env.get(deselect_env) != "1":
            continue
        if _importable(import_name):
            logger.info(
                "Coverage per-file: %s=1 but %r is importable; extra %r stays enforced",
                deselect_env, import_name, name,
            )
            continue
        logger.warning(
            "[WAIVED] Coverage per-file: extra %r is not installed and %s=1; files under %s "
            "are not held to the lines floor on this leg",
            name, deselect_env, ", ".join(prefixes),
        )
        waived[name] = tuple(prefixes)
    return waived


def _importable(name: str) -> bool:
    """True when `name` resolves to a real, installed module in this interpreter.

    Two things made a naive `find_spec` lie on the 3.9 leg. First, invoked as
    `python harness/shared/coverage_gate.py`, Python puts `harness/shared/` at
    the head of `sys.path`, where `harness/shared/langgraph/` shadows the real
    `langgraph` distribution: the probe reported the extra importable while
    nothing was installed, and the waiver was refused. The lookup therefore runs
    with this script's own directory removed and any cached module of that name
    set aside, then restores both. Second, a namespace-only hit (a directory with
    no `__init__.py`, which a sibling distribution can leave behind) proves
    nothing, so a spec without an origin reads as absent. Policies name a concrete
    module (`langgraph.graph`) so a dotted lookup whose parent is missing is
    simply absent too.
    """
    top = name.split(".", 1)[0]
    own_dir = Path(__file__).resolve().parent
    saved_path = sys.path[:]
    set_aside = {k: sys.modules.pop(k) for k in list(sys.modules) if k == top or k.startswith(f"{top}.")}
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != own_dir]
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        spec = None
    finally:
        sys.path[:] = saved_path
        for key in [k for k in sys.modules if k == top or k.startswith(f"{top}.")]:
            del sys.modules[key]  # whatever the probe imported; the gate does not use it
        sys.modules.update(set_aside)
    return spec is not None and spec.origin is not None


def _waiving_extra(path: str, waived: dict[str, tuple[str, ...]]) -> str | None:
    """The extra waiving ``path``, or None. Matches whole path segments only.

    A raw ``str.startswith`` let a prefix written without its trailing slash --
    ``harness/shared/langgraph`` instead of ``harness/shared/langgraph/`` -- waive
    every sibling whose name merely starts the same way (``langgraph_helpers.py``,
    ``langgraphX.py``). Nothing caught it: the policy check only asserts the prefix
    names a real directory, which the slashless form does. Widening a coverage
    waiver by deleting one character is not a change anyone would review.
    """
    posix = PurePath(path).as_posix()
    for name, prefixes in waived.items():
        for prefix in prefixes:
            boundary = prefix if prefix.endswith("/") else f"{prefix}/"
            if posix == prefix or posix.startswith(boundary):
                return name
    return None


def check_per_file(
    coverage_json: Path, lines_floor: float, waived: dict[str, tuple[str, ...]] | None = None
) -> bool:
    """Enforce the lines floor per measured file (policy coverage.per_file).

    Fail-closed: a report without a ``files`` block cannot prove per-file
    compliance the policy declares, so it exits 1 rather than passing on
    absence of evidence. Files with zero statements (empty ``__init__.py``)
    have nothing to measure and are skipped. Files under a prefix in
    ``waived`` (see ``optional_extra_waivers``) are reported, not enforced.
    """
    report = _load_json_object(coverage_json, "coverage report")
    files = report.get("files")
    if not isinstance(files, dict) or not files:
        logger.error(
            "[FAIL] Coverage report %s has no files block; the policy declares "
            "per_file enforcement, so absence of per-file evidence is a failure",
            coverage_json,
        )
        raise SystemExit(1)
    waived = waived or {}
    ok = True
    measured_count = 0
    waived_count = 0
    for path, data in sorted(files.items()):
        summary = data.get("summary") if isinstance(data, dict) else None
        if not isinstance(summary, dict):
            logger.error("[FAIL] Coverage report entry for %s has no summary block", path)
            raise SystemExit(1)
        numerator, denominator = summary.get("covered_lines"), summary.get("num_statements")
        if not isinstance(numerator, int) or not isinstance(denominator, int):
            logger.error("[FAIL] Coverage report entry for %s lacks covered_lines/num_statements", path)
            raise SystemExit(1)
        if denominator == 0:
            continue
        actual = 100.0 * numerator / denominator
        extra = _waiving_extra(path, waived)
        if extra is not None:
            waived_count += 1
            logger.warning(
                "[WAIVED] Coverage per-file: %s at %.2f%% lines (extra %r deselected on this leg)",
                path, actual, extra,
            )
            continue
        measured_count += 1
        if actual < lines_floor:
            logger.error(
                "[FAIL] Coverage per-file: %s at %.2f%% lines is below the policy floor of %.2f%%",
                path, actual, lines_floor,
            )
            ok = False
    if ok and measured_count == 0:
        # Absence of evidence is never a pass (this module's own contract). A
        # waiver set broad enough to cover every measured file -- one policy edit,
        # e.g. path_prefixes ["harness/"] -- turned per-file enforcement off
        # entirely while the gate still printed [PASS] with a 0 in it.
        logger.error(
            "[FAIL] Coverage per-file: 0 file(s) measured against the lines floor (%d waived); "
            "the policy declares per_file enforcement, so a waiver set covering everything "
            "is not compliance",
            waived_count,
        )
        return False
    if ok:
        logger.info(
            "[PASS] Coverage per-file: %d file(s) meet the lines floor of %.2f%% (%d waived)",
            measured_count, lines_floor, waived_count,
        )
    return ok


def declared_source_roots(pyproject: Path) -> list[str]:
    """The `[tool.coverage.run] source` roots, as declared.

    Parsed with a scoped regex rather than a TOML library on purpose: this gate
    is standalone-stdlib by decision (policy-single-source.md), it runs on the
    3.9 leg where `tomllib` does not exist, and adding `tomli` would make the
    gate depend on a package the run it is gating might not have installed. The
    table scoping mirrors `test_ci_gate_pipeline_shape.py`'s parse of the same
    block: an unscoped search takes the first `source = [` in the file, which
    any other `[tool.*]` table could silently become.
    """
    text = _read_text(pyproject, "pyproject")
    # `\Z` in the lookahead is load-bearing: without it a pyproject whose last
    # table is [tool.coverage.run] matches nothing and this fails closed with
    # "declares no table" -- true of the file's shape, false about its content.
    table = re.search(r"^\[tool\.coverage\.run\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if table is None:
        logger.error("[FAIL] %s declares no [tool.coverage.run] table", pyproject)
        raise SystemExit(1)
    block = re.search(r"^source\s*=\s*\[(.*?)\]", table.group(1), re.M | re.S)
    if block is None:
        logger.error("[FAIL] %s declares no [tool.coverage.run] source roots", pyproject)
        raise SystemExit(1)
    return re.findall(r'"([^"]+)"', block.group(1))


def first_party_sources(repo_root: Path, roots: list[str]) -> set[str]:
    """Every first-party module under the declared roots, as posix paths.

    "First party" is every ``.py`` under a declared source root that is not part
    of a test tree. That is exactly what the `omit` list expresses today, which
    is the point: stating the rule independently is what lets the two be
    compared. Caches are excluded because they are not source.
    """
    found: set[str] = set()
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            relative = PurePath(path.relative_to(repo_root)).as_posix()
            parts = relative.split("/")
            if "tests" in parts or "__pycache__" in parts:
                continue
            found.add(relative)
    return found


def check_measured_set(coverage_json: Path, repo_root: Path, pyproject: Path) -> bool:
    """Fail when the measured file set diverges from the first-party source set.

    The per-file floor only judges files the report contains. Adding a source
    file to `[tool.coverage.run] omit` removes it from that set, removes it from
    the floor, and *raises* the aggregate, because the uncovered lines it
    contributed are gone -- a regression that makes every number look better.
    Nothing detected it: `check_per_file` iterates whatever `files` holds, and
    its only emptiness guard fires when a waiver swallows everything.

    Fails closed on an empty expected set, per this module's own contract that
    absence of evidence is never a pass (C-GT-1).
    """
    report = _load_json_object(coverage_json, "coverage report")
    files = report.get("files")
    if not isinstance(files, dict):
        logger.error("[FAIL] Coverage report %s has no files block to bound", coverage_json)
        return False
    expected = first_party_sources(repo_root, declared_source_roots(pyproject))
    if not expected:
        logger.error(
            "[FAIL] Coverage measured-set: no first-party sources found under the declared "
            "roots; the comparison would pass vacuously"
        )
        return False
    measured = {PurePath(path).as_posix() for path in files}
    unmeasured = sorted(expected - measured)
    unexpected = sorted(measured - expected)
    if unmeasured:
        logger.error(
            "[FAIL] Coverage measured-set: %d first-party source file(s) are not measured, so "
            "they face no per-file floor and their uncovered lines raise the aggregate: %s",
            len(unmeasured),
            ", ".join(unmeasured),
        )
    if unexpected:
        logger.error(
            "[FAIL] Coverage measured-set: %d measured file(s) are not first-party sources; "
            "test code counted as source inflates every number: %s",
            len(unexpected),
            ", ".join(unexpected),
        )
    if not unmeasured and not unexpected:
        logger.info("[PASS] Coverage measured-set: %d first-party source file(s) measured", len(expected))
    return not unmeasured and not unexpected
