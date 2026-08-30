"""Deterministic coverage map: is every `ci_required_targets` gate actually run?

`governance-policy.json` declares `ci_required_targets` in the **per-stack**
Makefile vocabulary (`cov`, `types`, `secrets`, `audit`, `remotes`, ...), which
`harness/node/Makefile` and `harness/jvm/Makefile` implement under exactly those
names. The **root** Makefile deliberately uses a different vocabulary (`coverage`,
`lint`, `validate`, ...) because it gates a multi-stack repository rather than one
stack.

Those two vocabularies drifting apart is not hypothetical. `specs` sat in
`ci_required_targets` with no root stage at all, and the two existing meta-tests
that assert "CI invokes every required target" both read the *per-stack* `ci.yml`
and so could never have caught it.

This module closes that hole by requiring an explicit mapping: every required
gate names the root mechanism that satisfies it, and that mechanism must be
reachable from `make ci` by actual prerequisite resolution. A gate that nothing
covers must be declared in `KNOWN_GAPS` with a reason -- silence is not an option
in either direction.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
POLICY = REPO / "harness" / "shared" / "governance-policy.json"
ROOT_MAKEFILE = REPO / "Makefile"
# GitHub only executes workflows in the repository-root `.github/workflows/`.
# harness/{node,jvm}/.github/workflows/ci.yml are adopter templates that never run,
# so they must never be read as evidence that a gate is enforced here.
ROOT_WORKFLOW_DIR = REPO / ".github" / "workflows"
NEXT_STEPS = REPO / "NEXT_STEPS.md"

pytestmark = pytest.mark.governance

# Maps each per-stack gate name to the root `make` target that satisfies it.
# The value must be a real root target reachable from `ci`; the test resolves
# prerequisites rather than trusting this table.
GATE_TO_ROOT_TARGET = {
    "cov": "coverage",
    "lint": "lint",
    "types": "lint",  # lint -> lint-python, which runs mypy
    "specs": "specs",
    "remotes": "remotes",
    "projections": "validate",  # validate runs check_projections.py
    "traceability": "validate",  # validate runs governance/check_traceability.py
    "governance": "validate",  # validate runs the governance validator set
    "secrets": "secrets",  # dedicated workflow job; see INV-1 note above
    "audit": "audit",  # dedicated workflow job; see the `audit` job in python-package.yml
}

# What each gate's recipe must still *do*. Reachability only proves the target
# name is wired into `ci`; without this, emptying `validate` (which would delete
# the only invocation of the protected-path gate) leaves every test green.
GATE_TO_EVIDENCE = {
    "cov": r"coverage_gate\.py",
    "lint": r"\$\(RUFF\)|ruff",
    "types": r"\$\(MYPY\)|mypy",
    "specs": r"validate_specs\.sh",
    "remotes": r"remotes\.py",
    "projections": r"check_projections",
    "traceability": r"check_traceability",
    "governance": r"validate_invariants\.py",
    "secrets": r"\$\(GITLEAKS\)|gitleaks",
    "audit": r"pip-audit",
}

# Stages that must remain direct prerequisites of `ci`. Checked against `ci`'s own
# prerequisite list rather than transitive reachability, which a stray token could
# otherwise pollute.
REQUIRED_CI_STAGES = {
    "test-node": "the Node suite; without it the TypeScript stack is ungated",
    "verify-zero-skips": "INV-2 (no unapproved skips)",
    "check-dedup": "named non-negotiable in CLAUDE.md; detects copied governance scripts",
    "digest-regen": "the control-plane drift baseline `git diff --exit-code` compares against",
    "specs": "the spec structural, plan-defect, and strict tiers",
    "remotes": "INV-3 (push destination allowlist)",
    "validate": "the governance validator set, including the protected-path gate",
}

# Gates with no root equivalent. Each needs a reason; adding an entry here is a
# deliberate, reviewable statement that the root pipeline does not run this gate.
KNOWN_GAPS: dict[str, str] = {}

# Root mechanisms that satisfy a gate only partially. Documented rather than
# asserted away, so the weaker coverage stays visible to a reviewer.
PARTIAL_COVERAGE: dict[str, str] = {
    "specs": (
        "`make specs` runs validate_specs.sh, which is three-tier. The *structural* "
        "tier always runs and does real work (required sections, a requirement ID "
        "on every normative MUST, no unfalsifiable acceptance language, no unfilled "
        "template scaffold). The *plan* tier always runs too (validate_plan.py: "
        "unfalsifiable acceptance, stage reachability, missing failure path, orphan "
        "requirement) but is scoped to plans git reports as modified, so a run that "
        "touches no spec examines nothing -- it says so on stdout rather than "
        "reporting a silent pass. The "
        "*strict* tier (`openspec validate`) does not: `openspec` is pinned "
        "nowhere, and REQUIRE_STRICT_SPEC_VALIDATOR=1 is set only in "
        "harness/{node,jvm}/.github/workflows/ci.yml -- adopter templates GitHub "
        "never executes -- so root CI silently takes the WARNING branch on every "
        "run. Installing an unpinned, unverified validator as a hard CI dependency "
        "is a product decision, not a gate fix, so the strict tier is declared "
        "absent here rather than advertised as enforced."
    ),
}


def _expand_make_vars(makefile_text: str, line: str) -> str:
    """Substitute simple `NAME := value` / `NAME ?= value` definitions into `line`.

    Recipes reference paths through variables (`--cov=$(SHARED_SRC)`), so a literal
    string match would report a false gap. Only simple assignments are resolved,
    which is all this Makefile uses for the paths under test.
    """
    definitions = dict(
        re.findall(r"^([A-Z_][A-Z0-9_]*)\s*[:?]?=\s*(.+?)\s*$", makefile_text, re.M)
    )
    for _ in range(5):  # bounded: variables may reference other variables
        expanded = re.sub(
            r"\$\(([A-Z_][A-Z0-9_]*)\)", lambda m: definitions.get(m.group(1), m.group(0)), line
        )
        if expanded == line:
            break
        line = expanded
    return line


def _workflow_run_commands(workflow_text: str) -> str:
    """Concatenate the shell of every `run:` step, ignoring names and comments.

    Step names routinely quote the command they wrap ("Run secret scan gate
    (make secrets)"), so searching raw workflow text for an invocation gives false
    positives: the prose would keep satisfying an assertion after the step itself
    was deleted. Only executed shell counts as enforcement.

    Deliberately regex-based rather than YAML-parsed: PyYAML is not a declared
    dependency of this repo, and a governance gate must not rest on a transitive one.
    """
    commands: list[str] = []
    lines = workflow_text.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        match = re.match(r"^(\s*)(?:-\s+)?run:\s*([|>][-+]?)?\s*(.*)$", raw)
        if not match:
            index += 1
            continue
        # A `run:` nested under `with:`/`env:` is an action input or a variable
        # value, not executed shell. Find the nearest shallower mapping key.
        run_col = raw.index("run:")
        parent = ""
        for prior in reversed(lines[:index]):
            if not prior.strip():
                continue
            prior_indent = len(prior) - len(prior.lstrip())
            if prior_indent < run_col:
                parent = prior.strip().rstrip(":").lstrip("- ")
                break
        index += 1
        if parent in {"with", "env"}:
            continue
        block_scalar, inline = match.group(2), match.group(3)
        if not block_scalar:
            commands.append(inline)
            continue
        # Base is the column of the `run` key itself, never the leading dash: for
        # `- run: |`, sibling keys of the step sit deeper than the dash and would
        # otherwise be swallowed into "executed shell" — re-arming the very
        # step-name false positive this function exists to prevent.
        while index < len(lines):
            line = lines[index]
            if line.strip() and (len(line) - len(line.lstrip())) <= run_col:
                break
            commands.append(line)
            index += 1
    return "\n".join(commands)


def _root_workflow_texts() -> list[str]:
    """Root workflows that actually fire on a pull request or push.

    A `workflow_dispatch`-only helper never runs on a PR, so counting it as
    enforcement would be the same mistake as trusting the per-stack templates that
    GitHub does not execute at all.
    """
    files = sorted(ROOT_WORKFLOW_DIR.glob("*.yml")) + sorted(ROOT_WORKFLOW_DIR.glob("*.yaml"))
    texts = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        trigger = re.search(r"^on:\s*$(.*?)^\S", text, re.M | re.S) or re.search(
            r"^on:.*$", text, re.M
        )
        block = trigger.group(0) if trigger else ""
        if re.search(r"^\s*(pull_request|push):", block, re.M):
            texts.append(text)
    return texts


def _workflow_jobs(workflow_text: str) -> dict[str, str]:
    """Split a workflow into job blocks keyed by job id.

    Scoping matters: a global substring search for `fetch-depth: 0` is satisfied by
    *another* job's checkout, so the secret-scan job could silently go shallow — and
    a shallow clone makes its history scan vacuous — with the assertion still green.
    """
    lines = workflow_text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if re.match(r"^jobs:\s*$", line))
    except StopIteration:
        return {}
    jobs: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    for line in lines[start + 1 :]:
        header = re.match(r"^(\s{2})([A-Za-z0-9_-]+):\s*$", line)
        if header:
            if current:
                jobs[current] = "\n".join(body)
            current, body = header.group(2), []
            continue
        if re.match(r"^\S", line):  # back to a top-level key; jobs block is over
            break
        body.append(line)
    if current:
        jobs[current] = "\n".join(body)
    return jobs


def _unquote(value: str) -> str:
    """Strip one matching layer of YAML quoting, if present.

    YAML quoting is syntax, not content: `name: "x"` and `name: x` both parse
    to the string `x`, and GitHub reports the same check name either way. An
    unstripped quote would read as drift the moment a job's `name:` or a
    matrix entry picked up quotes for reasons unrelated to any real change.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


_QUOTED = r'"[^"]*"|\'[^\']*\''


def _matrix_python_versions(pre_steps: str) -> list[str] | None:
    """The job's `strategy.matrix.python-version` values, or None if it has none.

    GitHub Actions accepts this matrix axis in two equally valid YAML forms --
    an inline flow list (`python-version: ["3.9", "3.10"]`) or a block list
    (`python-version:` followed by indented `- "3.9"` lines) -- and treats
    them identically. Recognizing only one would read a purely stylistic
    reformat as the matrix disappearing, which fails the drift test loudly
    but for a reason that isn't real drift.

    Scoped to `pre_steps`, not the full job body, for the same reason the
    `name:` search below is: a step's `with:` input is a different context,
    and matching it there would be inspecting the wrong thing entirely, not
    just a false drift signal.
    """
    inline = re.search(r"python-version:\s*\[(.*?)\]", pre_steps)
    if inline:
        return [_unquote(v) for v in re.findall(_QUOTED, inline.group(1))]
    block = re.search(
        rf"python-version:[ \t]*\n((?:[ \t]*-[ \t]*(?:{_QUOTED})[ \t]*\n)+)", pre_steps
    )
    if block:
        return [_unquote(v) for v in re.findall(_QUOTED, block.group(1))]
    return None


def _job_check_names(job_id: str, body: str) -> list[str]:
    """The GitHub-reported check name(s) for one job, matrix legs included.

    A job-level `name:` (e.g. `secret-scan`) is distinct from step-level
    `- name:` entries under `steps:`, so the search is scoped to the slice
    before `steps:` -- an unscoped regex would occasionally match a step.
    """
    pre_steps = re.split(r"^\s*steps:\s*$", body, maxsplit=1, flags=re.M)[0]
    declared = re.search(r"^\s*name:\s*(.+?)\s*$", pre_steps, re.M)
    base = _unquote(declared.group(1).strip()) if declared else job_id

    # A bare numeric entry (`[3.9, 3.10]` or a block list of bare `3.10`) is
    # deliberately not supported: unquoted, `3.10` is the YAML float 3.1 --
    # the exact footgun this workflow's own quoting exists to avoid -- so
    # this file should never contain one, and treating it as absent fails
    # the drift test loudly rather than guessing at what GitHub would
    # actually resolve it to.
    values = _matrix_python_versions(pre_steps)
    if values is None:
        return [base]
    placeholder = "${{ matrix.python-version }}"
    if placeholder in base:
        return [base.replace(placeholder, v) for v in values]
    # No placeholder in the job's own name: GitHub appends "(value)" itself,
    # exactly as it does for `build`, which declares no `name:` at all.
    return [f"{base} ({v})" for v in values]


def _reported_check_names(workflow_text: str) -> set[str]:
    """Every check name a PR against this workflow will actually show."""
    names: set[str] = set()
    for job_id, body in _workflow_jobs(workflow_text).items():
        names.update(_job_check_names(job_id, body))
    return names


def _splice_continuations(makefile_text: str) -> str:
    """Join Make backslash continuations so a wrapped rule parses as one line."""
    return re.sub(r"\\\n\s*", " ", makefile_text)


# A Make target name; excludes `|` (order-only separator) and `#` so neither can
# be mistaken for a prerequisite.
_TARGET_TOKEN = re.compile(r"[A-Za-z0-9_.\-/]+")


def _make_prerequisites(makefile_text: str, target: str) -> list[str]:
    """Prerequisites of `target`, with Make's comment and continuation rules applied."""
    spliced = _splice_continuations(makefile_text)
    match = re.search(rf"^{re.escape(target)}\s*::?(?!=)([^\n]*)$", spliced, re.M)
    if not match:
        return []
    # Make treats an unescaped `#` as a comment to end of line -- not only `##`.
    # Splitting on `##` alone let a commented-out stage list read as prerequisites.
    prereqs = re.split(r"(?<!\\)#", match.group(1))[0]
    return [t for t in prereqs.split() if _TARGET_TOKEN.fullmatch(t)]


def _make_targets(makefile_text: str) -> set[str]:
    """Every name defined as a rule, so a fabricated prerequisite is detectable."""
    spliced = _splice_continuations(makefile_text)
    return set(re.findall(r"^([A-Za-z0-9_.\-/]+)\s*::?(?!=)", spliced, re.M))


def _recipe_body(makefile_text: str, target: str) -> str:
    """The executed recipe lines of `target`, with Make comment lines removed.

    Comment stripping is load-bearing: a commented-out command still appears in a
    raw recipe capture, so a substring check would accept a gate whose real work
    had been disabled.
    """
    spliced = _splice_continuations(makefile_text)
    match = re.search(
        rf"^{re.escape(target)}\s*::?(?!=)[^\n]*\n((?:\t[^\n]*\n)*)", spliced, re.M
    )
    if not match:
        return ""
    return "\n".join(
        line for line in match.group(1).splitlines() if not re.match(r"^\t\s*[@-]*\s*#", line)
    )


def _reachable_from(makefile_text: str, root: str) -> set[str]:
    """Transitively resolve `make` prerequisites, so nesting is followed, not assumed."""
    seen: set[str] = set()
    stack = [root]
    while stack:
        target = stack.pop()
        if target in seen:
            continue
        seen.add(target)
        stack.extend(_make_prerequisites(makefile_text, target))
    return seen


def _evidence_text(makefile_text: str, target: str) -> str:
    """Union of the recipe bodies of `target` and everything it depends on.

    Reachability proves a gate's *name* is wired in; this is what proves the gate
    still *does* something. Without it, emptying a recipe leaves the suite green.
    """
    return "\n".join(_recipe_body(makefile_text, t) for t in _reachable_from(makefile_text, target))


@pytest.fixture(scope="module")
def makefile() -> str:
    return ROOT_MAKEFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def required_gates() -> list[str]:
    gates = list(json.loads(POLICY.read_text(encoding="utf-8"))["ci_required_targets"])
    assert gates, "policy declares no ci_required_targets; this suite would be vacuous"
    return gates


@pytest.fixture(scope="module")
def root_workflows() -> str:
    """Concatenated root workflows — the only ones GitHub actually executes."""
    texts = _root_workflow_texts()
    assert texts, "no PR/push-triggered workflows in the repository-root .github/workflows/"
    return "\n".join(texts)


@pytest.fixture(scope="module")
def ci_reachable(makefile: str, root_workflows: str) -> set[str]:
    """Targets CI actually invokes: reachable from `make ci`, or run by a root job.

    INV-5 says "CI invokes every policy-required gate by Make target" — not that
    `make ci` must reach it. A gate deliberately kept out of the matrix (the
    interpreter-independent secret scan) is still enforced when a root job runs it.
    """
    reachable = _reachable_from(makefile, "ci")
    assert "ci" in reachable, "root Makefile has no `ci` target"
    for target in re.findall(
        r"\bmake\s+([a-zA-Z0-9_.-]+)", _workflow_run_commands(root_workflows)
    ):
        reachable |= _reachable_from(makefile, target)
    return reachable


class TestEveryRequiredGateIsAccountedFor:
    def test_every_required_gate_is_mapped_or_declared_a_gap(self, required_gates):
        """No gate may be silently unaccounted for — the failure mode `specs` hit."""
        unaccounted = sorted(
            g for g in required_gates if g not in GATE_TO_ROOT_TARGET and g not in KNOWN_GAPS
        )
        assert not unaccounted, (
            f"ci_required_targets entries with no root mapping and no declared gap: "
            f"{unaccounted}. Add a root target and map it in GATE_TO_ROOT_TARGET, or "
            "declare it in KNOWN_GAPS with a reason."
        )

    def test_mapped_gates_resolve_to_targets_reachable_from_ci(
        self, required_gates, ci_reachable, makefile
    ):
        """A mapping that points at a target `make ci` never reaches is not coverage."""
        broken = {}
        for gate in required_gates:
            target = GATE_TO_ROOT_TARGET.get(gate)
            if target is None:
                continue
            if not _make_prerequisites(makefile, target) and not re.search(
                rf"^{re.escape(target)}:", makefile, re.M
            ):
                broken[gate] = f"root target '{target}' does not exist"
            elif target not in ci_reachable:
                broken[gate] = f"root target '{target}' is not reachable from `make ci`"
        assert not broken, f"required gates mapped to unreachable root targets: {broken}"

    @pytest.mark.parametrize("gate", sorted(GATE_TO_EVIDENCE))
    def test_mapped_gate_recipe_still_does_its_work(self, gate, makefile, required_gates):
        """Reachability is not enforcement: prove the recipe still runs something.

        Emptying `validate` deletes the only invocation of the protected-path gate
        while leaving its name wired into `ci` — reachability alone stays green.
        """
        assert gate in required_gates, f"GATE_TO_EVIDENCE covers a gate the policy dropped: {gate}"
        target = GATE_TO_ROOT_TARGET[gate]
        evidence = _evidence_text(makefile, target)
        assert re.search(GATE_TO_EVIDENCE[gate], evidence), (
            f"gate '{gate}' maps to target '{target}', but nothing in that target's "
            f"recipe (or its prerequisites') matches {GATE_TO_EVIDENCE[gate]!r}. The "
            "target name is wired in but the work is gone."
        )

    def test_evidence_map_covers_every_mapped_gate(self):
        """A mapped gate with no evidence rule is unverified substance."""
        unverified = sorted(set(GATE_TO_ROOT_TARGET) - set(GATE_TO_EVIDENCE))
        assert not unverified, f"mapped gates with no evidence assertion: {unverified}"

    def test_no_stale_mappings(self, required_gates):
        """A mapping for a gate the policy no longer requires is dead weight."""
        stale = sorted(set(GATE_TO_ROOT_TARGET) - set(required_gates))
        assert not stale, f"GATE_TO_ROOT_TARGET maps gates the policy does not require: {stale}"

    def test_no_stale_gap_declarations(self, required_gates):
        """A gap waiver must not outlive the requirement it excuses."""
        stale = sorted(set(KNOWN_GAPS) - set(required_gates))
        assert not stale, f"KNOWN_GAPS declares gates the policy does not require: {stale}"

    def test_gaps_are_not_also_mapped(self):
        """A gate is either covered or a declared gap, never recorded as both."""
        both = sorted(set(KNOWN_GAPS) & set(GATE_TO_ROOT_TARGET))
        assert not both, f"gates declared as gaps but also mapped as covered: {both}"

    @pytest.mark.parametrize("gate", sorted(KNOWN_GAPS))
    def test_every_declared_gap_has_a_substantive_reason(self, gate):
        reason = KNOWN_GAPS[gate].strip()
        assert len(reason) > 40, f"KNOWN_GAPS['{gate}'] needs a real reason, not a placeholder"

    def test_partial_coverage_notes_describe_mapped_gates(self, required_gates):
        """Loops rather than parametrizes: an empty dict must not become a skipped test."""
        for gate in sorted(PARTIAL_COVERAGE):
            assert gate in GATE_TO_ROOT_TARGET, (
                f"PARTIAL_COVERAGE['{gate}'] describes a gate that is not mapped as covered"
            )
            assert gate in required_gates, (
                f"PARTIAL_COVERAGE['{gate}'] describes a gate the policy no longer requires"
            )
            assert len(PARTIAL_COVERAGE[gate].strip()) > 40, (
                f"PARTIAL_COVERAGE['{gate}'] needs a real reason, not a placeholder"
            )

    def test_specs_strict_tier_waiver_is_removed_once_the_root_pipeline_enforces_it(self):
        """Falsifiable in the direction that matters: the waiver must not outlive the gap.

        A stale "we don't enforce this" note is worse than none -- it tells a
        reviewer to stop looking. Once anything in the root pipeline sets
        REQUIRE_STRICT_SPEC_VALIDATOR=1, the strict tier *is* enforced and this
        entry has to go, so the assertion is written to fail at that moment.
        """
        enforced_at_root = any(
            "REQUIRE_STRICT_SPEC_VALIDATOR=1" in text
            for text in [*_root_workflow_texts(), ROOT_MAKEFILE.read_text(encoding="utf-8")]
        )
        assert enforced_at_root == ("specs" not in PARTIAL_COVERAGE), (
            "the root pipeline now sets REQUIRE_STRICT_SPEC_VALIDATOR=1; drop the "
            "PARTIAL_COVERAGE['specs'] waiver"
            if enforced_at_root
            else "the strict spec tier is unenforced at root but no longer declared in "
            "PARTIAL_COVERAGE['specs']"
        )


class TestRootPipelineShape:
    """Guards the structural invariants other tooling and docs depend on."""

    def test_ci_runs_the_specs_stage(self, ci_reachable):
        assert "specs" in ci_reachable, "`make ci` no longer runs the specs gate"

    def test_ci_runs_the_remotes_stage(self, ci_reachable):
        assert "remotes" in ci_reachable, "`make ci` no longer runs the remote allowlist gate"

    def test_specs_target_invokes_the_validator_through_bash(self, makefile):
        """validate_specs.sh is mode 644: a bare ./ invocation is a guaranteed red CI."""
        # _recipe_body (not a hand-rolled regex here) strips comment lines and
        # accepts both `:` and `::` rule syntax, exactly like every other
        # target-body test in this file -- a bespoke regex would silently pass
        # a commented-out invocation as if it were live.
        body = _recipe_body(makefile, "specs")
        assert body, "root Makefile has no specs recipe"
        assert "validate_specs.sh" in body, "specs target does not invoke validate_specs.sh"
        assert re.search(r"\bbash\b\s+\S*validate_specs\.sh", body), (
            "validate_specs.sh must be invoked via `bash`; it is not executable, so a "
            "bare ./ invocation fails with 'Permission denied'"
        )

    def test_secret_scan_gate_fails_closed_and_scans_history(self, makefile, root_workflows):
        """INV-1: a missing tool must fail, and the history scan must not be vacuous."""
        # _recipe_body strips Make comment lines: a commented-out scan still appears
        # in a raw capture, so a substring check would accept a disabled gate.
        body = _recipe_body(makefile, "secrets")
        assert body, "root Makefile has no secrets recipe"
        assert "command -v" in body and "exit 1" in body, (
            "the secrets gate must fail closed when gitleaks is absent, never skip"
        )
        for mode, what in (("dir", "the working tree"), ("git", "git history")):
            assert re.search(rf"(?:\$\(GITLEAKS\)|gitleaks\S*)\s+{mode}\b", body), (
                f"secrets gate does not scan {what}"
            )
        # Scoped per job: a global search for `fetch-depth: 0` is satisfied by the
        # build job's checkout, so the scanning job could go shallow undetected.
        scanning = [
            (job, block)
            for text in _root_workflow_texts()
            for job, block in _workflow_jobs(text).items()
            if re.search(r"\bmake\s+secrets\b(?!-)", _workflow_run_commands(block))
        ]
        assert scanning, (
            "no root workflow job invokes `make secrets`; INV-1 would have no live "
            "enforcement, since GitHub never runs harness/*/.github/workflows/"
        )
        for job, block in scanning:
            assert "fetch-depth: 0" in block, (
                f"job '{job}' runs the secret scan without a full clone; the default "
                "shallow checkout makes the history half of INV-1 vacuous"
            )
            # A conditional can disable the gate while the invocation remains:
            # `if: github.event_name == 'push'` would exempt every pull request.
            guards = re.findall(r"^\s*(?:-\s+)?if:\s*(.+)$", block, re.M)
            assert not guards, (
                f"job '{job}' gates the secret scan behind conditional(s) {guards}; "
                "INV-1 must run unconditionally on every triggering event"
            )

    def test_audit_gate_is_invoked_unconditionally(self) -> None:
        """Mirrors the secret-scan check above: GATE_TO_ROOT_TARGET only proves some
        workflow contains a `make audit` command, not that it always runs. A job- or
        step-level `if:` guard (e.g. `if: github.event_name == 'push'`) would leave
        this gate green while skipping every pull request's dependency audit."""
        auditing = [
            (job, block)
            for text in _root_workflow_texts()
            for job, block in _workflow_jobs(text).items()
            if re.search(r"\bmake\s+audit\b(?!-)", _workflow_run_commands(block))
        ]
        assert auditing, (
            "no root workflow job invokes `make audit`; the dependency-audit gate "
            "would have no live enforcement"
        )
        for job, block in auditing:
            # Same conditional-guard check as the secret scan: the invocation
            # remaining in the file proves nothing if a guard can skip the job.
            guards = re.findall(r"^\s*(?:-\s+)?if:\s*(.+)$", block, re.M)
            assert not guards, (
                f"job '{job}' gates the dependency audit behind conditional(s) "
                f"{guards}; it must run unconditionally on every triggering event"
            )

    @pytest.mark.parametrize("stage", sorted(REQUIRED_CI_STAGES))
    def test_required_stage_is_a_direct_prerequisite_of_ci(self, stage, makefile):
        """Checked against `ci`'s own prerequisites, not transitive reachability,
        which a stray token in a comment could otherwise satisfy."""
        prereqs = _make_prerequisites(makefile, "ci")
        assert stage in prereqs, (
            f"`make ci` no longer runs '{stage}' — {REQUIRED_CI_STAGES[stage]}. "
            f"Current prerequisites: {prereqs}"
        )

    def test_every_ci_prerequisite_is_a_real_target(self, makefile):
        """A fabricated name must never satisfy a reachability assertion."""
        defined = _make_targets(makefile)
        phantom = sorted(t for t in _reachable_from(makefile, "ci") if t not in defined)
        assert not phantom, (
            f"`make ci` depends on names with no rule in the Makefile: {phantom}. "
            "Either they are typos, or the parser accepted comment text as targets."
        )

    def test_coverage_thresholds_are_enforced_by_the_gate_script(self, makefile):
        """The recipe must produce the machine-readable report AND run the gate.

        coverage_gate.py applies coverage.lines and coverage.branches as two
        separate numbers. Its thresholds come from governance-policy.json with no
        numeric default anywhere, so "not hardcoded" is a property of the script;
        what the Makefile must guarantee is that the script actually runs against
        a report produced by this same pytest invocation.
        """
        body = _recipe_body(makefile, "coverage-python")
        assert body, "root Makefile has no coverage-python recipe"
        assert "--cov-report=json" in body, (
            "coverage-python must emit coverage.json; without it the gate script "
            "fails closed on every run instead of measuring anything"
        )
        assert re.search(r"coverage_gate\.py", body), (
            "coverage-python no longer runs coverage_gate.py; the pytest run "
            "would measure coverage without enforcing any threshold"
        )

    def test_digest_regen_regenerates_both_digest_layers(self, makefile):
        """The bundle has two layers: profiles[*].protected_files (refreshed by
        regenerate_bundle_digests.py) and the top-level governance/agent policy
        digests (refreshed ONLY by build_policy_bundle.py). Dropping either tool
        from the recipe silently un-gates its layer, so both invocations -- and
        the `git diff --exit-code` that turns drift red -- are pinned here."""
        body = _recipe_body(makefile, "digest-regen")
        assert body, "root Makefile has no digest-regen recipe"
        for required in (
            "regenerate_bundle_digests.py",
            "build_policy_bundle.py",
            "git diff --exit-code",
        ):
            assert required in body, f"digest-regen recipe no longer runs {required}"

    def test_coverage_gate_script_has_no_numeric_fallback(self):
        """The gate script must carry no default threshold a broken policy could
        silently fall back to -- the COV_MIN=80 inversion, one layer down
        (CHANGELOG: "COV_MIN fell back to the literal 80 whenever the policy
        was unreadable or its coverage block absent").

        Forbidden values come from governance-policy.json's own current
        thresholds, not a hardcoded (80, 90) pair: a policy change that moved
        a floor to some other number would otherwise leave this checking for
        a value that no longer means anything, while missing a fallback at
        the new one. Patterns are scoped to fallback-shaped syntax (argparse/
        kwarg `default=`, a `dict.get` fallback, the `or` idiom, or a
        threshold-named constant) rather than any bare `= N`, so an unrelated
        literal that happens to equal a threshold -- a line length, a byte
        cap -- does not fail this test with no real defect present.
        """
        source = (REPO / "harness" / "shared" / "coverage_gate.py").read_text(encoding="utf-8")
        assert "governance-policy.json" in source
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        thresholds = sorted(
            {
                str(v)
                for v in policy.get("coverage", {}).values()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
        )
        assert thresholds, "governance-policy.json declares no numeric coverage thresholds to guard"
        for value in thresholds:
            v = re.escape(value)
            shapes = (
                rf"default\s*=\s*{v}\b",  # argparse / keyword-arg default
                rf"\.get\([^)]*,\s*{v}\s*\)",  # dict.get(..., <threshold>) fallback
                rf"\bor\s+{v}\b",  # `resolved_value or <threshold>` idiom
                rf"\b\w*(?:COV|COVERAGE|THRESHOLD|MIN|FLOOR)\w*\s*=\s*{v}\b",  # named constant
            )
            for shape in shapes:
                assert not re.search(shape, source), (
                    f"coverage_gate.py has a fallback shape defaulting to {value!r}; "
                    "thresholds have exactly one source, governance-policy.json"
                )

    def test_coverage_run_does_not_exclude_tests(self, makefile):
        """Deselecting governance tests would silently drop these very gates."""
        body = _recipe_body(makefile, "coverage-python")
        for flag in ("--ignore", "--deselect"):
            assert flag not in body, f"coverage-python excludes tests via {flag}"
        markers = re.findall(r'-m\s+"([^"]+)"', body)
        for expression in markers:
            assert "not governance" not in expression, (
                f"coverage-python deselects governance tests via -m {expression!r}"
            )

    def test_coverage_measures_every_declared_source_root(self, makefile):
        """A source root in pyproject's coverage config that the gate never measures
        is configured-but-unmeasured — the state harness/control-plane was in."""
        pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        # Scoped to the [tool.coverage.run] table: an unscoped search takes the
        # first `source = [` anywhere in the file, which any other [tool.*] table
        # could silently become.
        table = re.search(r"^\[tool\.coverage\.run\]\s*$(.*?)(?=^\[)", pyproject, re.M | re.S)
        assert table, "pyproject declares no [tool.coverage.run] table"
        source_block = re.search(r"^source\s*=\s*\[(.*?)\]", table.group(1), re.M | re.S)
        assert source_block, "pyproject declares no [tool.coverage.run] source"
        declared = re.findall(r'"([^"]+)"', source_block.group(1))
        assert declared, "coverage source list is empty"
        body = _expand_make_vars(makefile, _recipe_body(makefile, "coverage-python"))
        assert body, "root Makefile has no coverage-python recipe"
        # Exact token comparison: `"--cov=harness" in body` is satisfied by
        # `--cov=harness/shared`, so broadening the declared source to ["harness"]
        # would read as measured while most of the tree stayed unmeasured.
        measured = set(re.findall(r"--cov=(\S+)", body))
        unmeasured = sorted(s for s in declared if s not in measured)
        assert not unmeasured, (
            f"coverage source root(s) declared in pyproject but never measured by the "
            f"gate: {unmeasured}. The Makefile's explicit --cov flags take precedence "
            "over the static config, so these read as covered while being ignored."
        )


class TestRequiredStatusChecksListIsAccurate:
    """`NEXT_STEPS.md` hands a human the literal check names for the branch
    ruleset GitHub has no API this repo's CI can configure on its own behalf --
    someone pastes this list into Settings -> Rules by hand, once. A list that
    silently drifts from what CI actually reports is exactly how the ruleset
    would end up requiring a `build (3.11)` that never runs, or omitting a real
    gate like `dependency-audit`: the ruleset would enforce a check GitHub
    never sends, or leave a check GitHub does send permanently unrequired,
    with nothing here to say so.
    """

    @pytest.fixture()
    def workflow_text(self) -> str:
        path = ROOT_WORKFLOW_DIR / "python-package.yml"
        assert path.is_file(), f"{path} does not exist"
        return path.read_text(encoding="utf-8")

    @pytest.fixture()
    def next_steps_text(self) -> str:
        assert NEXT_STEPS.is_file(), f"{NEXT_STEPS} does not exist"
        return NEXT_STEPS.read_text(encoding="utf-8")

    @staticmethod
    def _documented_required_checks(next_steps_text: str) -> set[str]:
        # Scoped to the sentence between "Required status checks" and its
        # terminating period: the paragraph after it repeats one of these
        # names in different prose, which would corrupt an unscoped search.
        sentence = re.search(
            r"Required status checks[^:]*:\s*(.+?)\.\s*\n", next_steps_text, re.S
        )
        assert sentence, "NEXT_STEPS.md has no 'Required status checks' sentence to parse"
        return set(re.findall(r"`([^`]+)`", sentence.group(1)))

    def test_documented_checks_match_what_ci_reports(
        self, workflow_text: str, next_steps_text: str
    ) -> None:
        reported = _reported_check_names(workflow_text)
        documented = self._documented_required_checks(next_steps_text)
        missing = sorted(reported - documented)
        extra = sorted(documented - reported)
        assert not missing and not extra, (
            "NEXT_STEPS.md's required-status-check list has drifted from what "
            f"python-package.yml reports. CI reports but the doc omits: {missing}. "
            f"The doc lists but CI no longer reports: {extra}. A branch ruleset "
            "built from the doc as it stands would misconfigure at least one check."
        )

    def test_every_job_contributes_at_least_one_check_name(self, workflow_text: str) -> None:
        """A job that silently derives zero names would make the comparison
        above vacuously agree with an incomplete `reported` set -- this pins
        that every job in the workflow contributes something to compare."""
        jobs = _workflow_jobs(workflow_text)
        assert jobs, "no jobs found in python-package.yml; the parser or the file is broken"
        for job_id, body in jobs.items():
            assert _job_check_names(job_id, body), f"job '{job_id}' derived no check name"

    def test_quoted_name_and_matrix_values_parse_the_same_as_unquoted(self) -> None:
        """YAML quoting is syntax, not content -- this repo's workflow never
        quotes a job `name:`, but a future edit that adds quotes for style
        reasons alone must not read as a check-name change. Covers exactly
        the two cases a Copilot review of this file flagged as unverified."""
        unquoted = '  audit:\n    name: dependency-audit\n    steps:\n'
        double_quoted = '  audit:\n    name: "dependency-audit"\n    steps:\n'
        single_quoted = "  audit:\n    name: 'dependency-audit'\n    steps:\n"
        for body in (unquoted, double_quoted, single_quoted):
            assert _job_check_names("audit", body) == ["dependency-audit"]

        double_quoted_matrix = (
            '  build:\n    strategy:\n      matrix:\n'
            '        python-version: ["3.9", "3.10"]\n    steps:\n'
        )
        single_quoted_matrix = (
            "  build:\n    strategy:\n      matrix:\n"
            "        python-version: ['3.9', '3.10']\n    steps:\n"
        )
        for body in (double_quoted_matrix, single_quoted_matrix):
            assert _job_check_names("build", body) == ["build (3.9)", "build (3.10)"]

    def test_block_list_matrix_syntax_parses_the_same_as_inline(self) -> None:
        """GitHub Actions treats an inline flow list and a block list as the
        identical matrix axis; a Copilot review of this file correctly
        flagged that only the inline form was recognized, which would have
        read a purely stylistic reformat as the matrix disappearing."""
        inline = (
            '  build:\n    strategy:\n      matrix:\n'
            '        python-version: ["3.9", "3.10"]\n    steps:\n'
        )
        block = (
            "  build:\n    strategy:\n      matrix:\n"
            "        python-version:\n"
            '          - "3.9"\n'
            '          - "3.10"\n'
            "    steps:\n"
        )
        block_single_quoted = (
            "  build:\n    strategy:\n      matrix:\n"
            "        python-version:\n"
            "          - '3.9'\n"
            "          - '3.10'\n"
            "    steps:\n"
        )
        for body in (inline, block, block_single_quoted):
            assert _job_check_names("build", body) == ["build (3.9)", "build (3.10)"]

    def test_matrix_search_is_scoped_to_pre_steps(self) -> None:
        """A step's `with:` input is a different context than the job's own
        `strategy.matrix`; matching a bracket-list-shaped step input there
        would be inspecting the wrong thing, not just a false drift signal."""
        body = (
            "  build:\n    runs-on: ubuntu-latest\n    steps:\n"
            '      - name: Some future step\n'
            '        with:\n'
            '          python-version: ["3.9", "3.10"]\n'
        )
        assert _job_check_names("build", body) == ["build"]
