"""Shared building blocks for the harness test suites.

Three things were reimplemented across the suite and are centralised here:

* ``REPO`` -- ``Path(__file__).resolve().parents[3]`` appeared verbatim in ten
  modules. It encodes the test file's depth in the tree, so moving a test
  broke it silently: the wrong root still resolves to *a* directory, and the
  assertions that use it then check the wrong files.
* ``load_module_by_path`` -- ``harness/control-plane`` is not a legal package
  name, so its tools can only be loaded by path. Five modules had their own
  copy, three of which leaked an entry into ``sys.modules`` that outlived the
  test.
* OpenAI-shaped chat-completion builders -- the orchestrator suites each need
  to fabricate model responses and tool calls.

The name is underscore-prefixed so pytest does not collect it as a test
module while it still imports normally as ``harness.shared.tests._helpers``.
"""

from __future__ import annotations

import ast
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

# harness/shared/tests/_helpers.py -> harness/shared/tests -> harness/shared
# -> harness -> repo root.
REPO = Path(__file__).resolve().parents[3]
HARNESS = REPO / "harness"
SHARED = HARNESS / "shared"
CONTROL_PLANE = HARNESS / "control-plane"


def utc_today() -> dt.date:
    """Today's date in UTC.

    The validators under test anchor their own "today" to UTC so a waiver or a
    review date does not expire a day early or late depending on the CI
    runner's timezone. A test that built its fixture dates from
    ``dt.date.today()`` would disagree with them for the hours where the local
    date and the UTC date differ -- a genuine, timezone-dependent flake, not a
    lint preference. Tests use this so both sides share one clock.
    """
    return dt.datetime.now(dt.timezone.utc).date()


def load_module_by_path(path: Path | str, name: str, register: bool = True) -> ModuleType:
    """Import a module from an explicit path.

    ``register`` puts the module in ``sys.modules`` (needed when the module
    pickles, uses ``dataclasses``, or imports itself). Prefer
    ``imported_module`` when the registration should not outlive the test.
    """
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def imported_module(path: Path | str, name: str) -> Iterator[ModuleType]:
    """Load a module by path and restore ``sys.modules`` afterwards.

    Collection-time registration of a bare name (``sys.modules["remotes"]``)
    is a live collision hazard: whichever suite pytest collects first wins,
    and the other silently tests the wrong object. This restores whatever was
    there before, including nothing.
    """
    sentinel = object()
    previous: Any = sys.modules.get(name, sentinel)
    try:
        yield load_module_by_path(path, name, register=True)
    finally:
        if previous is sentinel:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def chat_response(content: str | None = None, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """An OpenAI-style chat completion response for a mocked bridge."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def tool_call(
    name: str,
    arguments: dict[str, Any] | str | None = None,
    call_id: str = "call_1",
    omit_arguments: bool = False,
) -> dict[str, Any]:
    """A single ``tool_calls`` entry.

    ``arguments`` accepts a dict (JSON-encoded), a raw string (used verbatim,
    to exercise malformed payloads) or ``None`` (emitted as JSON ``null``,
    which is a shape real models produce for zero-argument tools).
    ``omit_arguments`` drops the key entirely.
    """
    function: dict[str, Any] = {"name": name}
    if not omit_arguments:
        if isinstance(arguments, str):
            function["arguments"] = arguments
        elif arguments is None:
            function["arguments"] = None
        else:
            function["arguments"] = json.dumps(arguments)
    return {"id": call_id, "function": function}


# --- ruff invocation -------------------------------------------------------
#
# Several meta-tests shell out to ruff and read its stdout. Ruff's exit codes
# are 0 (clean), 1 (violations found) and 2 (the run itself failed: bad rule
# code, unparseable config, missing binary). Only 2 is an error -- which is
# why a plain `returncode == 0` check would be wrong here, and why these
# helpers exist rather than each caller rolling its own.
#
# The failure mode this closes is quiet and actively misleading: on exit 2
# ruff writes the diagnostic to *stderr* and leaves stdout empty, so
# `json.loads(result.stdout or "[]")` yields an empty list. A broken
# invocation then reads as "this rule has zero findings" -- which, in the
# deferral register, renders as "the cost that justified deferring it is gone,
# enable it". A tool failure would have been reported as a policy conclusion.

RUFF_ERROR_EXIT = 2


def seed_minimal_decision_records(
    workspace: Path,
    *,
    dec_id: str = "DEC-001",
    date: str | None = None,
    title: str = "Example decision",
    skill_path: str = "agents/GOVERNANCE_SKILL.md",
    reviewed: str | None = None,
    since: str | None = None,
    write_skill: bool = True,
) -> Path:
    """Seed minimal ``docs/decisions/`` + generated indexes (+ optional skill pointer).

    Validators treat ``docs/decisions/`` as the decision SoT. Temp fixtures that
    only wrote a pipe ``decision-log.md`` fail closed after NS-34; call this
    helper so happy-path fixtures match the contract without duplicating
    frontmatter/index boilerplate in every suite.
    """
    from harness.shared import decision_records as dr

    if date is None:
        date = utc_today().isoformat()
    if reviewed is None:
        reviewed = utc_today().isoformat()
    if since is None:
        since = date

    decisions = workspace / "docs" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    record = (
        "---\n"
        f"id: {dec_id}\n"
        f'title: "{title}"\n'
        "status: accepted\n"
        f"date: {date}\n"
        "supersedes: []\n"
        "superseded_by: null\n"
        'owners: ["governance-maintainers"]\n'
        "---\n\n"
        f"# {dec_id}: {title}\n\n"
        "## Context\n\nWhy.\n\n"
        "## Decision\n\nWhat.\n\n"
        "## Consequences\n\nEffects.\n"
    )
    (decisions / f"{dec_id}.md").write_text(record, encoding="utf-8")
    payload = dr.index_payload(dr.load_all(decisions))
    (decisions / "index.json").write_text(dr.render_index_json(payload), encoding="utf-8")
    (decisions / "index.md").write_text(dr.render_index_md(payload), encoding="utf-8")

    if write_skill:
        skill = workspace / skill_path
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(
            f"# Governance Skill\nReviewed: {reviewed}\n\n"
            f"## Decisions since {since}\n\n"
            "Source of truth: docs/decisions/ (see index.md).\n",
            encoding="utf-8",
        )
    return decisions


def run_ruff(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    """Run ruff with ``args``, raising if the invocation itself failed.

    Violations (exit 1) are a normal result and are returned to the caller.
    """
    result = subprocess.run(
        [sys.executable, "-m", "ruff", *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode >= RUFF_ERROR_EXIT:
        raise AssertionError(
            f"ruff invocation failed (exit {result.returncode}): {' '.join(args)}\nstderr:\n{result.stderr.strip()}"
        )
    return result


def ruff_json(args: list[str], timeout: int = 300) -> list[dict]:
    """Run ruff with JSON output and parse it, reporting either failure clearly."""
    result = run_ruff([*args, "--output-format", "json"], timeout=timeout)
    try:
        parsed = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"ruff returned unparseable JSON for {' '.join(args)}: {exc}\nstdout begins: {result.stdout[:200]!r}"
        ) from exc
    if not isinstance(parsed, list):
        raise AssertionError(f"ruff JSON output was {type(parsed).__name__}, expected a list")
    return parsed


def agent_memory_policy(tmp_path: Path, **agent_memory_overrides) -> Path:
    """Copy the shipped governance policy, mutating only ``agent_memory`` keys.

    Shared because the gap suite and the hypothesis-revision suite both need it
    and were carrying byte-identical copies. `check_dedup.py` polices per-stack
    script shims, not intra-suite duplication, so this would have drifted
    silently -- the two copies already had to be edited together once.
    """
    shared_policy = REPO / "harness" / "shared" / "governance-policy.json"
    policy = json.loads(shared_policy.read_text(encoding="utf-8"))
    block = dict(policy.get("agent_memory") or {})
    block.update(agent_memory_overrides)
    policy["agent_memory"] = block
    path = tmp_path / "governance-policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    return path


#: The readers of the hypothesis store that carry no bound. A prompt-building
#: module may reach the store only through `format_hypotheses_for_reasoner`
#: (`docs/specs/hypothesis-surfacing.md`, C-HS-1, which narrowed the phase-1
#: `C-HR-2` from "no reader at all"). Shared so the pin and the test that proves
#: the pin is not vacuous grade the same set.
UNBOUNDED_HYPOTHESIS_READERS: frozenset[str] = frozenset(
    {"load_hypotheses", "format_hypotheses_for_review", "successors_of", "_hypotheses_path", "_read_json_safe"}
)
BOUNDED_HYPOTHESIS_FORMATTER = "format_hypotheses_for_reasoner"


_PROMPT_TEMPLATE_SUFFIX = "PROMPT_TEMPLATE"


def _names_a_prompt_template(path: Path) -> bool:
    """True when the module defines, imports or formats a ``*_PROMPT_TEMPLATE``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        name: str | None = None
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.alias):
            name = node.name
        if name is not None and name.endswith(_PROMPT_TEMPLATE_SUFFIX):
            return True
    return False


def prompt_building_modules() -> list[Path]:
    """Every source module under ``harness/shared`` that builds a prompt.

    Discovered by *content*, not by filename: any non-test module that names a
    ``*_PROMPT_TEMPLATE`` (defines one, imports one, or formats one), plus the
    orchestrator loop. The first version matched ``"prompt" in path.name``,
    which found ``agent_prompts.py`` and ``loop.py`` and missed
    ``langgraph/nodes.py`` -- a module that formats all three templates and
    is a prompt builder by the spec's own definition (adversarial review of
    DEC-058, finding M1). A third builder added later is graded without anyone
    extending a list. Tests are excluded: ``test_agent_prompts.py`` names the
    templates and is not a builder.
    """
    return sorted(
        path
        for path in SHARED.rglob("*.py")
        if "tests" not in path.parts and (path.name == "loop.py" or _names_a_prompt_template(path))
    )


def hypothesis_reader_violations(path: Path) -> list[str]:
    """Ways ``path`` reaches the hypothesis store other than through the bounded formatter.

    A call-graph check over the module's AST, not a substring scan: it looks for
    an import of, a call to, a bare reference to, or a string naming any name in
    `UNBOUNDED_HYPOTHESIS_READERS`, and accepts `BOUNDED_HYPOTHESIS_FORMATTER`.
    A comment that mentions the readers passes. A call through a module alias
    (``memory_view.load_hypotheses()``), an aliased reference
    (``r = memory_view.load_hypotheses; r()``) and a ``getattr(mv,
    "load_hypotheses")`` lookup do not -- the last two were bypasses the first
    version missed (adversarial review of DEC-058, finding L3). This is a drift
    pin over the repository's own modules, not a sandbox: a module determined to
    read the file by path can still do so, and the tree-diff and prompt tests
    are what catch the effect. Returns the violations so the caller can assert
    on the empty list and the negative test can assert on a non-empty one.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    call_targets = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in UNBOUNDED_HYPOTHESIS_READERS:
                    violations.append(f"{path.name} imports {alias.name}")
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in UNBOUNDED_HYPOTHESIS_READERS:
                violations.append(f"{path.name} calls {name}()")
        elif isinstance(node, (ast.Name, ast.Attribute)) and id(node) not in call_targets:
            referenced = node.id if isinstance(node, ast.Name) else node.attr
            if referenced in UNBOUNDED_HYPOTHESIS_READERS:
                violations.append(f"{path.name} references {referenced}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in UNBOUNDED_HYPOTHESIS_READERS:
                violations.append(f"{path.name} names {node.value} in a string")
    return violations


def snapshot_tree(root: Path, *, exclude: tuple[str, ...] = ()) -> dict[str, str]:
    """Relative POSIX path -> sha256 for every file under ``root``.

    The shape a "nothing else changed" assertion needs: two snapshots compared
    with ``==`` name exactly which files appeared, vanished or changed. Paths
    whose relative form starts with an entry of ``exclude`` are left out, for
    the case where one directory is *expected* to change.
    """
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(rel == prefix or rel.startswith(prefix.rstrip("/") + "/") for prefix in exclude):
            continue
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out
