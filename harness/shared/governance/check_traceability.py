#!/usr/bin/env python3
"""Bidirectional requirement traceability gate.

Every requirement ID declared in the spec globs must be cited by both an
implementation file and a test file. Failures name each ID *and which side* it is
missing from, because "missing implementation and/or test citation" alone does not
tell an operator which half to fix.

Three defects this gate now fails on instead of passing through:

**The wrong-corpus defect (R-GEA-1).** The config path and every glob used to
resolve against the *process* CWD, and ``make validate`` runs this gate from
``harness/node``. The globs therefore resolved under ``harness/node/``: the gate
read 6 requirement IDs while ``docs/specs/`` held 412 sharing not one member with
them, and printed ``traceability: passed (6 requirements)``. ``--workspace`` makes
the root explicit and every path resolves against it. It defaults to the current
working directory, so the per-stack shims that ``runpy`` this module during the
DEC-056 shim window behave exactly as before.

**The vacuity defect (R-GEA-4).** No emptiness guard can catch "found the wrong
two files": the ``no spec files matched`` and ``specs contain no requirement IDs``
raises both passed while the gate was pointed at the wrong tree. A config that
declares ``"scope": "repository"`` must therefore also clear
``traceability.min_discovered_requirement_ids``, so a repository-scoped run that
reads almost nothing fails instead of passing. A config with no ``scope`` key is a
legacy per-stack config and the floor does not apply to it, which is what keeps
this change backwards compatible.

**The cry-wolf defect (R-GEA-1b).** Re-scoping the globs alone produces a gate
that can never go green, because a program plan's requirement IDs name scheduled
work with nothing yet to cite. Each document therefore declares its class on a
line carrying ``traceability.spec_class_marker``. A document declaring nothing is
graded as ``traceability.default_spec_class`` — the strict branch — so the
permissive class is never the default, and a document declaring an *unrecognised*
class raises rather than falling into the permissive branch. What is left is a
ratchet, ``traceability.max_uncited_contract_requirement_ids``: it may be lowered
as citations land and never raised, so the backlog is visible and cannot grow.

Thresholds come from ``governance-policy.json`` and none is restated here. The
policy is read with ``json`` and resolved from *this file's* own location rather
than through ``policy_loader``: the per-stack shims run this module from arbitrary
working directories, so it imports nothing from the harness package beyond its
defensive logger, and a CWD-relative policy read would be the original defect
again in a second place.

Run with ``LOG_LEVEL=DEBUG`` to see the resolved workspace, the resolved config
path, the declared scope, which globs matched which files, and the per-class ID
counts. That is the fastest way to diagnose the common failure where a glob is
scoped to one stack and silently checks nothing outside it.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple

REQ = re.compile(r"\b([CR]-[A-Za-z0-9_-]+)\b")

TRACEABILITY_CONFIG = Path(".governance/traceability.json")

#: The ``scope`` value that opts a config into the floor and the ratchet. Legacy
#: per-stack configs declare no scope at all and keep their previous behaviour.
REPOSITORY_SCOPE = "repository"

#: The scaffold `make spec` copies. Excluded from the corpus for the reason given
#: at the call site; the name is the same literal `validate_specs.py` and
#: `validate_plan.py` skip, so all three gates read one corpus.
SPEC_TEMPLATE_NAME = "SPEC_TEMPLATE.md"

#: Resolved from this module rather than the CWD, for the reason in the docstring.
POLICY_PATH = Path(__file__).resolve().parents[1] / "governance-policy.json"


def _gate_logger() -> logging.Logger:
    """Return the shared gate logger, degrading to a bare one if unimportable.

    These scripts run as ``python ../shared/governance/check_traceability.py`` from
    a stack directory, where the repo root is not on ``sys.path``. Diagnostics are
    never allowed to fail the gate, so an import problem degrades to a no-op logger
    rather than raising.
    """
    try:
        root = Path(__file__).resolve().parents[3]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from harness.shared.json_logging import configure_gate_logging

        return configure_gate_logging(__name__)
    except Exception:  # noqa: BLE001 - logging setup must never break a gate
        return _fallback_logger()


def _fallback_logger() -> logging.Logger:
    """A stderr logger that does not propagate, for when the shared helper is absent.

    Propagating would hand diagnostics to the root logger, and `setup_json_logging`
    in this same package attaches a root handler on **stdout** — so the fallback
    could put diagnostics into the verdict channel the separation exists to protect.
    """
    logger = logging.getLogger(__name__)
    logger.propagate = False
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler(sys.stderr))
    return logger


logger = _gate_logger()


class TraceabilityResult(NamedTuple):
    """What one run measured, with no verdict attached.

    Separating measurement from verdict is what lets the floor, the ratchet and the
    legacy all-or-nothing rule be three readings of one traversal rather than three
    traversals — and lets a test assert *what was found* without reading an exit
    code. Every count the callers need is a ``len()`` over these fields: discovered
    IDs, per-class breakdown, and the gaps with the side each is absent from.

    A ``NamedTuple`` rather than a ``dataclass`` for a reason worth recording:
    ``test_gate_logging.py`` executes this module through ``exec_module`` *without*
    registering it in ``sys.modules``, to prove the fallback logger does not leak
    diagnostics into the verdict channel. ``@dataclass`` resolves each annotation
    through ``sys.modules[cls.__module__]`` and raises ``AttributeError`` under that
    loader; ``NamedTuple`` does not touch ``sys.modules``. The gate has to keep
    importing from anywhere, which is the same property ``--workspace`` exists for.
    """

    workspace: Path
    config_path: Path
    scope: str | None
    #: spec class -> the requirement IDs declared by documents of that class. An ID
    #: declared by both a contract spec and a program plan appears in both entries;
    #: the strict branch wins, because the contract spec is a promise about shipped
    #: behaviour whatever a roadmap also says about it.
    ids_by_class: dict[str, set[str]]
    #: contract-class ID -> the sides it is absent from. These fail the gate.
    gaps: dict[str, list[str]]
    #: IDs declared *only* by program plans and absent from a side. Reported so the
    #: backlog stays visible; not required to cite, because a roadmap item has
    #: nothing to cite until it is done.
    plan_only_gaps: dict[str, list[str]]

    @property
    def discovered(self) -> set[str]:
        """Every requirement ID the run read, across all classes."""
        found: set[str] = set()
        for members in self.ids_by_class.values():
            found |= members
        return found


def _traceability_policy() -> dict[str, Any]:
    """Read the ``traceability`` section of ``governance-policy.json``.

    Fails closed on a missing section: a gate that silently defaults its own
    thresholds is the DEC-024 shape, not a configured gate.
    """
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    section = policy.get("traceability")
    if not isinstance(section, dict):
        raise SystemExit(f"traceability: {POLICY_PATH} declares no `traceability` policy section")
    return section


def _policy_value(policy: dict[str, Any], key: str) -> Any:
    """Return one policy value, or fail closed naming the key that is missing."""
    if key not in policy:
        raise SystemExit(f"traceability: governance-policy.json -> traceability.{key} is not declared")
    return policy[key]


def _declared_class(text: str, marker: str) -> str | None:
    """Return the class a document declares, or ``None`` when it declares none.

    The declaration is a line *containing* the marker rather than a line equal to
    it, so a document can carry it inside its existing header blockquote and read
    naturally. Markdown emphasis and quoting around the value are stripped; an
    empty value is returned as ``""`` so the caller rejects it as unrecognised
    rather than reading a malformed declaration as "declared nothing".
    """
    for line in text.splitlines():
        position = line.find(marker)
        if position < 0:
            continue
        remainder = line[position + len(marker) :].strip(" \t*`_>")
        words = remainder.split()
        return words[0].strip("*`_.,;") if words else ""
    return None


def _spec_class(text: str, path: Path, policy: dict[str, Any]) -> str:
    """Grade one document, defaulting to the strict class and raising on nonsense.

    An unrecognised class must not fall through to the permissive branch: that is
    how a typo (``program_plan`` for ``program-plan``) would silently exempt a
    contract spec from citation, which is the failure this classification exists to
    prevent (AC-GEA-1c).
    """
    default_class = str(_policy_value(policy, "default_spec_class"))
    program_plan_class = str(_policy_value(policy, "program_plan_class"))
    marker = str(_policy_value(policy, "spec_class_marker"))
    declared = _declared_class(text, marker)
    if declared is None:
        return default_class
    if declared not in (default_class, program_plan_class):
        raise SystemExit(
            " ".join(
                [
                    f"traceability: {path} declares an unrecognised spec class {declared!r}.",
                    f"Declare {default_class!r} or {program_plan_class!r} after {marker!r},",
                    "or remove the line to be graded as the strict default. An unknown class",
                    "is never read as the permissive one.",
                ]
            )
        )
    return declared


def _absences(requirement_ids: list[str], impl_text: str, test_text: str) -> dict[str, list[str]]:
    """Map each uncited ID to the side(s) it is absent from.

    Tracked per side because an ID cited in code but not in a test is a very
    different fix from one cited nowhere, and a combined message hid that.
    """
    absences: dict[str, list[str]] = {}
    for req in requirement_ids:
        absent_from = []
        if req not in impl_text:
            absent_from.append("implementation")
        if req not in test_text:
            absent_from.append("tests")
        if absent_from:
            absences[req] = absent_from
    return absences


def analyse_traceability(workspace: Path, policy: dict[str, Any]) -> TraceabilityResult:
    """Measure one workspace and return the result, passing no judgement on it.

    Every path — the config and all three glob sets — resolves against
    ``workspace`` rather than the process CWD (R-GEA-1). An absolute glob in a
    config is left absolute, because ``Path.__truediv__`` yields the right operand
    when it is already anchored.

    The two emptiness raises are kept here rather than in the caller: an empty spec
    set or an empty ID set is a broken extractor, not a satisfied property, and it
    must fail wherever the traversal is used from (R-GEA-4).
    """
    workspace = Path(workspace).resolve()
    config_path = workspace / TRACEABILITY_CONFIG
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    scope = cfg.get("scope")
    logger.debug("workspace %s; config %s; scope %r", workspace, config_path, scope)

    def files(patterns: list[str], label: str) -> list[Path]:
        out: list[Path] = []
        for pattern in patterns:
            resolved = str(workspace / pattern)
            matched = [Path(x) for x in glob.glob(resolved, recursive=True) if Path(x).is_file()]
            logger.debug("%s glob %r resolved to %r matched %d file(s)", label, pattern, resolved, len(matched))
            out += matched
        logger.debug("%s: %d file(s) total: %s", label, len(out), [str(p) for p in out])
        return out

    # The scaffold is not a specification. `validate_specs.py:58` and
    # `validate_plan.py:45,101` both skip it by name, and counting its
    # `R-EXAMPLE-1` / `C-EXAMPLE-1` placeholders here would give this gate a
    # different corpus from its two siblings and inflate every number it
    # reports by two -- including the floor and ratchet the policy sets against
    # a corpus measured without it. A glob cannot express the exclusion, so it
    # lives here, matching how the siblings do it.
    specs = [path for path in files(cfg["spec_globs"], "spec_globs") if path.name != SPEC_TEMPLATE_NAME]
    impl = files(cfg["implementation_globs"], "implementation_globs")
    tests = files(cfg["test_globs"], "test_globs")
    if not specs:
        raise SystemExit("traceability: no spec files matched")

    ids_by_class: dict[str, set[str]] = {}
    for path in specs:
        text = path.read_text(errors="replace")
        ids_by_class.setdefault(_spec_class(text, path, policy), set()).update(REQ.findall(text))
    logger.debug("per-class ID counts: %s", {name: len(members) for name, members in sorted(ids_by_class.items())})

    contract_ids = ids_by_class.get(str(_policy_value(policy, "default_spec_class")), set())
    discovered: set[str] = set()
    for members in ids_by_class.values():
        discovered |= members
    if not discovered:
        raise SystemExit("traceability: specs contain no requirement IDs")
    logger.debug("discovered %d requirement ID(s): %s", len(discovered), sorted(discovered))

    impl_text = "\n".join(p.read_text(errors="replace") for p in impl)
    test_text = "\n".join(p.read_text(errors="replace") for p in tests)
    return TraceabilityResult(
        workspace=workspace,
        config_path=config_path,
        scope=scope,
        ids_by_class=ids_by_class,
        gaps=_absences(sorted(contract_ids), impl_text, test_text),
        plan_only_gaps=_absences(sorted(discovered - contract_ids), impl_text, test_text),
    )


def _gap_detail(gaps: dict[str, list[str]]) -> str:
    return "".join(f"\n  {req}: absent from {' and '.join(sides)}" for req, sides in gaps.items())


def _enforce_repository_scope(result: TraceabilityResult, policy: dict[str, Any]) -> None:
    """Apply the anti-vacuity floor and then the ratchet to a repository-scoped run.

    The ratchet is C-GEA-4's shape applied to a count rather than to a list: an
    allowance that may only be lowered cannot outlive the backlog it covers,
    because every citation that lands makes the recorded number wrong in the one
    direction the gate refuses to accept. A waiver that can only shrink is a
    waiver that has to be revisited.
    """
    floor = int(_policy_value(policy, "min_discovered_requirement_ids"))
    ratchet = int(_policy_value(policy, "max_uncited_contract_requirement_ids"))
    discovered = len(result.discovered)
    if discovered < floor:
        raise SystemExit(
            " ".join(
                [
                    f"traceability: repository-scoped run discovered {discovered} requirement ID(s),",
                    f"below the floor of {floor}",
                    "(governance-policy.json -> traceability.min_discovered_requirement_ids).",
                    "A repository-scoped gate that reads almost nothing is pointed at the wrong",
                    f"corpus, not a satisfied property: workspace {result.workspace},",
                    f"config {result.config_path}.",
                ]
            )
        )
    uncited = len(result.gaps)
    if uncited > ratchet:
        raise SystemExit(
            " ".join(
                [
                    f"traceability: {uncited} contract-spec requirement ID(s) missing an",
                    f"implementation and/or test citation, exceeding the ratchet of {ratchet}",
                    f"by {uncited - ratchet}",
                    "(governance-policy.json -> traceability.max_uncited_contract_requirement_ids).",
                    "The ratchet may only be lowered as citations land, never raised: cite the",
                    "IDs below or record an accepted exemption.",
                ]
            )
            + _gap_detail(result.gaps)
        )
    print(
        " ".join(
            [
                f"traceability: passed ({discovered} requirements;",
                f"{uncited} uncited contract ID(s) against a ratchet of {ratchet},",
                f"headroom {ratchet - uncited} — lower",
                f"traceability.max_uncited_contract_requirement_ids to {uncited};",
                f"{len(result.plan_only_gaps)} program-plan ID(s) reported, not required to cite)",
            ]
        )
    )


def check_traceability(workspace: Path | None = None) -> None:
    """Run the gate and exit non-zero on failure. ``workspace`` defaults to the CWD.

    A thin wrapper over :func:`analyse_traceability`, kept as the published entry
    point: the per-stack shims call it with no argument, and the leading sentence of
    its failure message is matched by CI logs and by ``test_validators.py``, so both
    are preserved verbatim.
    """
    policy = _traceability_policy()
    result = analyse_traceability(Path.cwd() if workspace is None else workspace, policy)
    if result.scope == REPOSITORY_SCOPE:
        _enforce_repository_scope(result, policy)
        return
    if result.gaps:
        # Leading sentence is unchanged: CI logs and the test suite match on it.
        raise SystemExit(
            "traceability: requirement IDs missing implementation and/or test citation: "
            + ", ".join(result.gaps)
            + _gap_detail(result.gaps)
        )
    print(f"traceability: passed ({len(result.discovered)} requirements)")


def main(argv: list[str] | None = None) -> None:
    """Parse ``--workspace`` and run the gate.

    Unknown arguments are ignored rather than rejected. This entry point had no
    argument parsing at all, and callers already pass flags it never read
    (``test_validators.py`` invokes it with ``--req-files``/``--src-dir``); turning
    those into a usage error would replace the gate's real verdict with an argparse
    one, which is a behaviour change dressed as a bug fix.
    """
    parser = argparse.ArgumentParser(description="Bidirectional requirement traceability gate.")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Root that the config path and every glob resolve against (default: the current directory).",
    )
    args, _unknown = parser.parse_known_args(argv)
    check_traceability(args.workspace)


if __name__ == "__main__":
    main()
