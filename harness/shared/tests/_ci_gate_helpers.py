"""Shared parser for the CI gate tests (`test_ci_gate_*.py`).

Make prerequisite resolution, recipe extraction, root-workflow discovery, job and
check-name derivation, and the module-scoped fixtures the three gate modules
share. Split out of the 923-line `test_ci_gate_coverage.py` by concern
(tech-debt-hardening-plan R-TDH-22); the leading underscore keeps pytest from
collecting it, and the `harness/shared/tests/*ci_gate*.py` protected-path glob
keeps it under the same review as the gates that depend on it.

Deliberately regex-based rather than YAML-parsed: PyYAML is not a declared
dependency of this repo, and a governance gate must not rest on a transitive one.
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


def _strip_yaml_comment(value: str) -> str:
    """Drop a trailing ` # comment` from a name-style scalar value.

    A `#` starts a YAML comment only when preceded by whitespace; a quoted
    scalar's closing quote ends it outright, so anything after that point
    -- comment or otherwise -- is not content either way.
    """
    if value[:1] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        return value if end == -1 else value[: end + 1]
    return re.split(r"\s+#", value, maxsplit=1)[0].rstrip()


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
    # YAML allows a trailing comment on the `steps:` line itself; matching
    # only the bare key would leave the split silently not happening, and
    # the search below would then be free to match a step's own `name:`
    # instead of falling back to the job id.
    pre_steps = re.split(r"^\s*steps:\s*(?:#.*)?$", body, maxsplit=1, flags=re.M)[0]
    declared = re.search(r"^\s*name:\s*(.+?)\s*$", pre_steps, re.M)
    base = _unquote(_strip_yaml_comment(declared.group(1).strip())) if declared else job_id

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


def _numeric_fallback_shape(source: str) -> re.Match[str] | None:
    """The first fallback-shaped numeric literal found in `source`, if any.

    Matches ANY numeric default in these shapes (argparse/kwarg `default=`,
    a `dict.get` fallback, the `or` idiom, or a threshold-named constant) --
    not only values equal to some particular policy's current thresholds, so
    a fallback to an arbitrary unrelated number is caught exactly like one
    that happens to collide with today's real threshold. Scoped to these
    shapes rather than any bare `= N` so an unrelated literal that isn't
    actually being used as a fallback -- a line length, a byte cap -- does
    not read as one.
    """
    number = r"\d+(?:\.\d+)?"
    shapes = (
        rf"default\s*=\s*{number}\b",
        rf"\.get\([^)]*,\s*{number}\s*\)",
        rf"\bor\s+{number}\b",
        rf"\b\w*(?:COV|COVERAGE|THRESHOLD|MIN|FLOOR)\w*\s*=\s*{number}\b",
    )
    for shape in shapes:
        match = re.search(shape, source)
        if match:
            return match
    return None


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
