"""Tests for ``authority_graph`` and its call-site half, ``authority_call_sites``.

Three properties, each written against a specific way the naive version of this
check passes for the wrong reason:

* **The approval flag is unreachable from agent input** (AC-GEA-2, R-GEA-2). The
  guarantee rests on one dict literal in ``execute_run_command``, read *at the
  call*: position- and parameter-blind, the scan called six of these sites clean.
* **High-risk reachability is asserted on the half where it is non-vacuous**
  (AC-GEA-2b, R-GEA-2b). Three of the five ``high_risk_actions`` are declared
  by no role at all, so asserting "no high-risk action is reachable" is 60%
  vacuous (finding S-1). The test states which two carry the property and
  asserts the other three are denied by absence, which is a different claim
  about a different mechanism.
* **A path answer names the surface it is about** (AC-GEA-3, R-GEA-2b).
  ``planner`` holds ``spec_write`` on tool exposure and lacks it as
  ``orchestrator``; that pair is the one a single-surface query answers wrongly
  (finding S-5).

Plus the boundary (AC-GEA-6) and every fail-closed raise (R-GEA-4). Fixtures are
written into ``tmp_path`` and analysed by the function that reads the real tree
-- no test here edits a source file, and ``agent_authority.py`` is protected.

Spec: ``docs/specs/graph-engineering-adoption.md``.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from harness.shared import agent_authority
from harness.shared.authority_graph import (
    APPROVAL_FLAG,
    EmptyDerivationError,
    Surface,
    UnnamedSurfaceError,
    approval_flag_reachability,
    build_authority_graph,
    paths_to,
    reachable_actions,
)
from harness.shared.tests._helpers import HARNESS, REPO, SHARED

pytestmark = pytest.mark.governance

#: The module name the governance layer must never import (C-GEA-2), and the
#: files that must never import it. ``authority_call_sites`` is listed too: the
#: split is an implementation detail of one deliverable, and a governance module
#: importing the lower half would breach the boundary just as squarely.
GRAPH_MODULES = ("authority_graph", "authority_call_sites")

#: The three ``high_risk_actions`` that no canonical role declares. They are
#: ``command_actions.classify`` *output* rather than grants, so ``decide``
#: denies them by absence -- a different mechanism from the approval gate, and
#: the reason an undifferentiated "no high-risk action is reachable" assertion
#: is vacuous for them (finding S-1, S-2).
DENIED_BY_ABSENCE = ("destructive", "permission_change", "secret_access")

#: The two ``high_risk_actions`` that ``release-auditor`` really declares and
#: gates on human approval. These are the ones the property is non-vacuous for.
GATED_BY_APPROVAL = ("external_write", "production_change")

#: The live call site the whole approval-flag property rests on.
LIVE_CALL_SITE = "execute_run_command"


def _first_party_sources() -> list[Path]:
    """Every non-test first-party module the agent path could run through.

    Tests are excluded deliberately: a test may hand the broker any context it
    likes, and that is not the agent path. Scanning the whole tree rather than a
    named list is the point -- a *new* call site is exactly the change this
    property must notice.
    """
    return [
        path
        for path in sorted(HARNESS.rglob("*.py"))
        if "tests" not in path.parts and "__pycache__" not in path.parts and not path.name.startswith("test_")
    ]


def _fixture(tmp_path: Path, name: str, source: str) -> Path:
    """Write a mutation fixture. Real sources are never edited by these tests."""
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    return path


def _policy(tmp_path: Path, agents: list[dict[str, Any]]) -> Path:
    """A mutated authority model on disk, passed as ``policy_path``."""
    path = tmp_path / "agent-policy.json"
    path.write_text(json.dumps({"default_deny": True, "agents": agents}), encoding="utf-8")
    return path


def _live_policy() -> dict[str, Any]:
    return agent_authority.load_agent_policy()


def _imports_the_graph(path: Path) -> list[str]:
    """The graph modules ``path`` imports, by ``ast`` rather than by grep.

    A text search would match a docstring that merely mentions the module, and
    a boundary test that fails on prose is a boundary test somebody deletes.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names if alias.name.split(".")[-1] in GRAPH_MODULES)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[-1] in GRAPH_MODULES:
                found.append(module)
            found.extend(f"{module}.{alias.name}" for alias in node.names if alias.name in GRAPH_MODULES)
    return found


def _imported_roots(path: Path) -> set[str]:
    """The top-level packages ``path`` imports, by ``ast``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
    return roots


class TestTheApprovalFlagIsUnreachable:
    """AC-GEA-2 / R-GEA-2. ``decide``'s ``human_approved`` is the one argument
    that turns a high-risk DENY into an ALLOW, and the agent path reaches it only
    if some call site hands the broker a mapping it did not build itself."""

    def test_no_agent_input_reaches_the_approval_flag(self, tmp_path: Path) -> None:
        """Zero witnesses over the live tree -- and a mutated ``execute_run_command``
        that forwards a caller-supplied context produces one, naming that site.

        Both halves are in one test because either alone is worthless: the clean
        result is only evidence if the scan can fail, and the mutation is only
        evidence if the real tree is clean.
        """
        witnesses = approval_flag_reachability(_first_party_sources())
        assert witnesses == [], "agent-controlled input can reach the approval flag: " + "; ".join(
            f"{w.path}:{w.line} in {w.function}: `{w.expression}` -- {w.reason}" for w in witnesses
        )

        mutated = _fixture(
            tmp_path,
            "tool_executors_mutated",
            "def execute_run_command(broker, active_role, workspace_dir, command, timeout=None, context=None):\n"
            '    kwargs = {"context": context, "cwd": workspace_dir}\n'
            "    if timeout is not None:\n"
            '        kwargs["timeout"] = timeout\n'
            "    return broker.execute_command(command, **kwargs)\n",
        )
        found = approval_flag_reachability([mutated])
        assert len(found) == 1, f"the forwarded context was not reported: {found}"
        assert found[0].function == LIVE_CALL_SITE
        assert found[0].path == str(mutated)
        assert APPROVAL_FLAG in found[0].reason

    def test_the_live_call_site_is_actually_inspected(self) -> None:
        """The clean result above must come from reading the real function, not
        from a path glob that quietly matched nothing."""
        executors = SHARED / "tool_executors.py"
        assert executors in _first_party_sources()
        source = executors.read_text(encoding="utf-8")
        assert f"def {LIVE_CALL_SITE}(" in source
        assert "broker.execute_command(command, **kwargs)" in source

    def test_a_forwarded_kwargs_bag_is_reported(self, tmp_path: Path) -> None:
        """The shape ``broker.execute_command(command, **kwargs)`` makes easy:
        a wrapper that never builds the mapping it forwards."""
        path = _fixture(
            tmp_path,
            "kwargs_bag",
            "def run(broker, command, **extra):\n    return broker.execute_command(command, **extra)\n",
        )
        (witness,) = approval_flag_reachability([path])
        assert "**extra" in witness.reason

    def test_a_forwarded_literal_naming_the_flag_is_reported(self, tmp_path: Path) -> None:
        """``**{"human_approved": True}`` never reaches ``context``, but a scan
        that ignored it would be reporting on argument shape rather than on the
        flag."""
        path = _fixture(
            tmp_path,
            "spread_literal",
            "def run(broker, command):\n"
            '    return broker.execute_command(command, **{"human_approved": True, "cwd": "."})\n',
        )
        (witness,) = approval_flag_reachability([path])
        assert "forwarded arguments" in witness.reason

    def test_a_context_built_by_a_helper_is_reported(self, tmp_path: Path) -> None:
        """A name bound to a call is not a mapping this analysis can read: the
        helper is free to return anything, including the flag."""
        path = _fixture(
            tmp_path,
            "built_context",
            "def run(broker, command, role):\n"
            "    context = build_context(role)\n"
            "    return broker.execute_command(command, context)\n",
        )
        (witness,) = approval_flag_reachability([path])
        assert "not a dict literal" in witness.reason

    def test_a_caller_supplied_context_keyword_is_reported(self, tmp_path: Path) -> None:
        path = _fixture(
            tmp_path,
            "context_keyword",
            "async def run(broker, command, context):\n"
            "    return await broker.execute_command(command, context=context)\n",
        )
        (witness,) = approval_flag_reachability([path])
        assert witness.function == "run"
        assert witness.expression == "context"

    def test_a_positional_context_is_reported(self, tmp_path: Path) -> None:
        """``execute_command``'s second positional slot is the context, and
        ``verification.py`` uses exactly that form."""
        path = _fixture(
            tmp_path,
            "positional",
            "def run(broker, command, context):\n    return broker.execute_command(command, context)\n",
        )
        (witness,) = approval_flag_reachability([path])
        assert witness.expression == "context"

    def test_an_alias_of_the_broker_entry_point_is_reported(self, tmp_path: Path) -> None:
        path = _fixture(
            tmp_path,
            "broker_alias",
            "def run(broker, command, context):\n"
            "    invoke = broker.execute_command\n"
            "    return invoke(command, context)\n",
        )
        (witness,) = approval_flag_reachability([path])
        assert witness.expression == "context"

    def test_a_literal_approval_key_is_reported(self, tmp_path: Path) -> None:
        """A hard-coded ``human_approved`` is literal in the constructing
        function and still a standing approval on the agent path."""
        path = _fixture(
            tmp_path,
            "literal_flag",
            "def run(broker, command, role):\n"
            '    return broker.execute_command(command, {"agent_id": role, "human_approved": True})\n',
        )
        (witness,) = approval_flag_reachability([path])
        assert "directly" in witness.reason

    def test_a_flag_added_by_subscript_is_reported(self, tmp_path: Path) -> None:
        """The dict literal is clean; the line after it is not."""
        path = _fixture(
            tmp_path,
            "subscript",
            "def run(broker, command, role):\n"
            '    context = {"agent_id": role}\n'
            '    context["human_approved"] = True\n'
            "    return broker.execute_command(command, context)\n",
        )
        (witness,) = approval_flag_reachability([path])
        assert APPROVAL_FLAG in witness.reason

    def test_a_computed_key_is_reported(self, tmp_path: Path) -> None:
        """A key the analysis cannot read could be the flag."""
        path = _fixture(
            tmp_path,
            "computed_key",
            "def run(broker, command, role, key):\n"
            '    context = {"agent_id": role}\n'
            "    context[key] = True\n"
            "    return broker.execute_command(command, context)\n",
        )
        assert approval_flag_reachability([path])

    def test_a_merged_mapping_is_reported(self, tmp_path: Path) -> None:
        """``update`` and ``|=`` both add keys the literal does not show."""
        merged = _fixture(
            tmp_path,
            "merged",
            "def run(broker, command, role, overrides):\n"
            '    context = {"agent_id": role}\n'
            "    context.update(overrides)\n"
            "    return broker.execute_command(command, context=context)\n",
        )
        augmented = _fixture(
            tmp_path,
            "augmented",
            "def run(broker, command, role, overrides):\n"
            '    context = {"agent_id": role}\n'
            "    context |= overrides\n"
            "    return broker.execute_command(command, context=context)\n",
        )
        assert approval_flag_reachability([merged])
        assert approval_flag_reachability([augmented])

    def test_a_spread_inside_the_context_is_reported(self, tmp_path: Path) -> None:
        path = _fixture(
            tmp_path,
            "spread",
            "def run(broker, command, role, extra):\n"
            '    return broker.execute_command(command, {"agent_id": role, **extra})\n',
        )
        assert approval_flag_reachability([path])

    def test_a_rebound_name_is_reported(self, tmp_path: Path) -> None:
        """Which of two assignments reaches the call is a flow question this
        analysis does not answer, so it reports rather than guesses."""
        path = _fixture(
            tmp_path,
            "rebound",
            "def run(broker, command, role, approved):\n"
            '    context = {"agent_id": role}\n'
            '    context = {"agent_id": role, "human_approved": approved}\n'
            "    return broker.execute_command(command, context)\n",
        )
        assert approval_flag_reachability([path])

    @pytest.mark.parametrize(
        "source",
        [
            """def run(broker, cmd, context):
    broker.execute_command(cmd, context)
    context = {"agent_id": "x"}""",
            """def run(broker, cmd, context):
    context = {"agent_id": "x"}
    broker.execute_command(cmd, context)""",
            """def run(broker, cmd, role):
    if role:
        context = {"agent_id": role}
    broker.execute_command(cmd, context)""",
            """def run(broker, cmd, roles):
    for role in roles:
        context = {"agent_id": role}
    broker.execute_command(cmd, context)""",
            """def run(broker, cmd, role):
    try:
        context = {"agent_id": role}
    finally:
        broker.execute_command(cmd, context)""",
            """def run(broker, cmd, contexts):
    for context in contexts:
        broker.execute_command(cmd, context)
        context = {"agent_id": "late"}
    stored = broker.execute_command(cmd, stored)
    broker.execute_command(cmd, MODULE_CONTEXT)""",
        ],
    )
    def test_a_laundered_binding_is_reported(self, tmp_path: Path, source: str) -> None:
        """Shapes that read *clean* while one scope was built from every
        assignment in a body: a literal written after the call, an iteration late,
        over a parameter, or under an ``if``/``for``/``try`` that may not have run
        stood in for the mapping the broker was actually handed."""
        found = approval_flag_reachability([_fixture(tmp_path, "laundered", source)])
        assert found and all(APPROVAL_FLAG in w.reason for w in found), source

    def test_a_parameter_reads_as_the_caller_s_value(self, tmp_path: Path) -> None:
        """Reporting a parameter as "not bound to a dict literal" reads as a
        shape this analysis gave up on. It is the hole itself -- the caller chose
        that mapping, by name or as the whole ``**`` bag -- and it must say so."""
        source = "def run(broker, cmd, context):\n    broker.execute_command(cmd, context)\n"
        source += "def bag(broker, cmd, **kw):\n    broker.execute_command(cmd, **kw)\n"
        found = approval_flag_reachability([_fixture(tmp_path, "parameters", source)])
        assert [(w.function, "is a parameter of" in w.reason) for w in found] == [("run", True), ("bag", True)]

    def test_a_binding_that_dominates_its_call_is_not_reported(self, tmp_path: Path) -> None:
        """Dominance, not nesting: a rule tainting every binding under an ``if``
        would fire on ``kwargs["timeout"] = timeout``, which is correct code."""
        guarded = "def run(broker, cmd, role):\n    if role:\n        context = {'agent_id': role}\n"
        guarded += "        return broker.execute_command(cmd, context)\n    return None\n"
        assert approval_flag_reachability([_fixture(tmp_path, "dominating", guarded)]) == []

    def test_the_real_forwarding_shape_is_not_reported(self, tmp_path: Path) -> None:
        """The one shape that must stay clean. A scan that flagged every ``**``
        would fail on ``execute_run_command`` as written and be switched off."""
        path = _fixture(
            tmp_path,
            "clean_forward",
            "def execute_run_command(broker, active_role, workspace_dir, command, timeout=None):\n"
            '    kwargs = {"context": {"agent_id": execution_identity(active_role)}, "cwd": workspace_dir}\n'
            "    if timeout is not None:\n"
            '        kwargs["timeout"] = timeout\n'
            "    return broker.execute_command(command, **kwargs)\n",
        )
        assert approval_flag_reachability([path]) == []

    def test_a_context_free_call_is_not_reported(self, tmp_path: Path) -> None:
        """No context at all cannot carry the flag; ``execute_command`` defaults
        it to an empty mapping."""
        path = _fixture(
            tmp_path,
            "no_context",
            "def probe(broker, command, cwd):\n"
            "    return execute_command(command, cwd=cwd)\n"
            "\n"
            "def other(broker, command):\n"
            '    return broker.run_other(command, {"human_approved": True})\n',
        )
        assert approval_flag_reachability([path]) == []

    def test_a_forwarded_bag_without_a_context_key_is_not_reported(self, tmp_path: Path) -> None:
        path = _fixture(
            tmp_path,
            "bag_without_context",
            "def run(broker, command, cwd):\n"
            '    kwargs = {"cwd": cwd}\n'
            "    return broker.execute_command(command, **kwargs)\n",
        )
        assert approval_flag_reachability([path]) == []

    def test_an_empty_file_list_raises(self) -> None:
        """R-GEA-4: a scan of nothing returns no witnesses for a reason that has
        nothing to do with the property."""
        with pytest.raises(EmptyDerivationError, match="nothing to prove"):
            approval_flag_reachability([])

    def test_a_corpus_with_no_broker_call_raises(self, tmp_path: Path) -> None:
        """R-GEA-4 again, one level subtler: the files exist, and none of them
        is on the path being checked. This is the shape that let a traceability
        gate print ``passed (6 requirements)`` over a corpus of 412."""
        path = _fixture(tmp_path, "unrelated", "def helper(value):\n    return value\n")
        with pytest.raises(EmptyDerivationError, match="inspected nothing"):
            approval_flag_reachability([path])


class TestHighRiskReachability:
    """AC-GEA-2b / R-GEA-2b. Two of the five ``high_risk_actions`` carry this
    property; the other three are denied by a different mechanism and must be
    asserted as such rather than counted as passes."""

    def test_high_risk_reachability_names_its_live_half(self) -> None:
        """Only ``external_write`` and ``production_change`` make this test
        non-vacuous.

        ``destructive``, ``permission_change`` and ``secret_access`` are
        ``command_actions.classify`` output, not grants: no canonical role
        declares them, so there is no edge to traverse and ``decide`` denies
        them by absence (``default_deny``). Asserting they are "not reachable"
        would pass for a reason unrelated to reachability -- finding S-1's 60%
        vacuity. Both claims are made here, separately, and each says which
        mechanism it is about.
        """
        policy = _live_policy()
        declared = {role["id"]: set(role.get("allowed_actions", [])) for role in policy["agents"]}
        high_risk = set(policy["high_risk_actions"])
        assert set(DENIED_BY_ABSENCE) | set(GATED_BY_APPROVAL) == high_risk, (
            "the high-risk vocabulary moved; re-triage which half this test is non-vacuous for "
            "before editing the constants"
        )

        for action in DENIED_BY_ABSENCE:
            holders = sorted(role_id for role_id, actions in declared.items() if action in actions)
            assert holders == [], (
                f"{action!r} is now declared by {holders}; it was previously denied by absence, so the "
                "reachability assertion below has become the only thing standing between the verifier "
                "and it -- and it was never designed to carry that weight for this action"
            )

        assert set(GATED_BY_APPROVAL) <= declared["release-auditor"], (
            "release-auditor no longer declares the two high-risk actions this test is non-vacuous for; "
            "the assertions below would now pass by absence like the other three"
        )

        for surface in Surface:
            graph = build_authority_graph(surface)
            assert set(GATED_BY_APPROVAL) <= graph.actions, (
                "the two live high-risk actions are not even nodes on this graph, so 'the verifier "
                "cannot reach them' would hold with no edge to traverse -- the vacuity of S-1"
            )
            assert not (set(DENIED_BY_ABSENCE) & graph.actions), (
                "a classification-vocabulary action became a declared grant; it is now reachable in "
                "principle and needs the approval gate the other two have"
            )

            actions = reachable_actions("verifier", surface)
            assert actions, f"the verifier reaches nothing on {surface.value}; the derivation is broken"
            for action in GATED_BY_APPROVAL:
                assert action not in actions, (
                    f"the verifier reaches {action!r} on the {surface.value} surface. This is the live half "
                    "of the high-risk property: release-auditor declares it and gates it on human approval, "
                    "and `allowed_actions` subtracts `human_approval_required_for` for exactly this reason"
                )

    def test_reverting_the_approval_subtraction_turns_the_live_half_red(self, tmp_path: Path) -> None:
        """The mutation proof, run through the real code path.

        The subtraction lives in ``agent_authority.allowed_actions``, a
        protected path, so the mutation is applied to its *input*: an authority
        model identical to the live one except that ``release-auditor`` gates
        nothing. If the assertion above were vacuous, this would still be
        empty.
        """
        agents = []
        for role in _live_policy()["agents"]:
            mutated = dict(role)
            if mutated["id"] == "release-auditor":
                mutated["human_approval_required_for"] = []
            agents.append(mutated)
        ungated = _policy(tmp_path, agents)

        actions = reachable_actions("verifier", Surface.TOOL_EXPOSURE, ungated)
        assert set(GATED_BY_APPROVAL) <= actions, (
            "removing `human_approval_required_for` did not widen the verifier's reach, so the "
            "assertion in the previous test proves nothing about the subtraction"
        )

    def test_a_naive_union_reimplementation_turns_the_live_half_red(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The graph must read the live grant function, not a copy of it.

        ``allowed_actions`` is replaced with the plain union it would be without
        the subtraction -- the exact code mutation AC-GEA-2b names. A graph that
        re-derived the tool-exposure surface itself would sail through this.
        """

        def naive_union(active_role: str, policy_path: Path | None = None) -> frozenset[str]:
            policy = agent_authority.load_agent_policy(policy_path)
            by_id = {role["id"]: role for role in policy["agents"]}
            granted: set[str] = set()
            for role_id in agent_authority.ACTIVE_TO_CANONICAL.get(active_role, ()):
                granted |= set(by_id[role_id].get("allowed_actions", []))
            return frozenset(granted)

        monkeypatch.setattr(agent_authority, "allowed_actions", naive_union)
        actions = reachable_actions("verifier", Surface.TOOL_EXPOSURE)
        assert set(GATED_BY_APPROVAL) <= actions, (
            "the graph did not follow `agent_authority.allowed_actions`, so it is a second "
            "implementation of the grant surface and will drift from the enforced one"
        )


class TestSurfacesAreNamed:
    """AC-GEA-3 / R-GEA-2b. The two grant surfaces disagree, so an unnamed one
    raises rather than picking the surface the caller did not ask about."""

    def test_write_paths_name_their_surface(self) -> None:
        """A witness names every intermediate; the planner has none; an unnamed
        surface raises; and ``planner``/``spec_write`` differs between the two,
        which is the pair a single-surface query answers wrongly (S-5)."""
        for surface in Surface:
            assert paths_to("nemotron-reasoner", "write_file", surface) == [
                ["nemotron-reasoner", "implementer", "write", "write_file"]
            ], f"the reasoner's write path changed shape on {surface.value}"
            assert paths_to("planner", "write_file", surface) == [], (
                f"the planner reaches write_file on {surface.value}; it holds no `write` action"
            )

        with pytest.raises(UnnamedSurfaceError, match="must name a surface"):
            paths_to("nemotron-reasoner", "write_file")
        with pytest.raises(UnnamedSurfaceError, match="must name a surface"):
            reachable_actions("planner")
        with pytest.raises(UnnamedSurfaceError):
            build_authority_graph("tool_exposure")  # type: ignore[arg-type]

        exposed = reachable_actions("planner", Surface.TOOL_EXPOSURE)
        executed = reachable_actions("planner", Surface.EXECUTION_IDENTITY)
        assert "spec_write" in exposed, "the planner's tool exposure lost `spec_write` (spec-analyst)"
        assert "spec_write" not in executed, (
            "the planner executes as `orchestrator`, which declares no `spec_write`; a query that "
            "conflated the surfaces would report this grant as enforceable"
        )
        assert {"review_write", "security_scan"} <= reachable_actions("verifier", Surface.TOOL_EXPOSURE)
        assert not ({"review_write", "security_scan"} & reachable_actions("verifier", Surface.EXECUTION_IDENTITY))

    def test_a_witness_names_every_canonical_intermediate(self) -> None:
        """Tool exposure unions four canonical roles for the verifier, and the
        witness list names which one carries each path -- ``read`` reaches
        ``read_file`` four ways on one surface and one way on the other."""
        exposed = paths_to("verifier", "read_file", Surface.TOOL_EXPOSURE)
        assert [path[1] for path in exposed] == [
            "peer-reviewer",
            "release-auditor",
            "security-reviewer",
            "test-eval",
        ]
        assert all(path[0] == "verifier" and path[2] == "read" for path in exposed)
        assert paths_to("verifier", "read_file", Surface.EXECUTION_IDENTITY) == [
            ["verifier", "test-eval", "read", "read_file"]
        ]

    def test_the_verifier_cannot_reach_the_write_tools(self) -> None:
        """R-AC-8 restated as a path property: the role that judges the work
        cannot reach a tool that edits it, on either surface."""
        for tool in ("write_file", "apply_patch", "generate_code"):
            for surface in Surface:
                assert paths_to("verifier", tool, surface) == [], f"the verifier reaches {tool} on {surface.value}"

    def test_the_graph_reports_its_own_size(self) -> None:
        """Node and edge counts back the debug line an operator reads when a
        derivation looks wrong; a graph that counted nothing would log a
        plausible zero."""
        graph = build_authority_graph(Surface.TOOL_EXPOSURE)
        assert graph.node_count > len(graph.role_edges)
        assert graph.edge_count >= graph.node_count - len(graph.role_edges)
        assert graph.surface is Surface.TOOL_EXPOSURE
        narrower = build_authority_graph(Surface.EXECUTION_IDENTITY)
        assert narrower.edge_count < graph.edge_count, (
            "the execution-identity surface must traverse fewer role edges than tool exposure; "
            "the verifier maps to four canonical roles and executes as one"
        )


class TestFailsClosedOnEmptyInput:
    """R-GEA-4. Every empty derived set raises; none returns a clean result."""

    def test_an_unknown_active_role_raises(self) -> None:
        with pytest.raises(EmptyDerivationError, match="not an active role"):
            reachable_actions("nemotron-reasner", Surface.TOOL_EXPOSURE)

    def test_an_unknown_tool_raises(self) -> None:
        """An unmapped tool is withheld by ``tool_is_permitted``; an empty path
        list for a misspelled name would read as 'safely unreachable'."""
        with pytest.raises(EmptyDerivationError, match="declares no required action"):
            paths_to("nemotron-reasoner", "write_fil", Surface.TOOL_EXPOSURE)

    def test_no_active_role_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(agent_authority, "ACTIVE_TO_CANONICAL", {})
        with pytest.raises(EmptyDerivationError, match="active-role mapping is empty"):
            build_authority_graph(Surface.TOOL_EXPOSURE)

    def test_no_declared_tool_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(agent_authority, "TOOL_REQUIRED_ACTION", {})
        with pytest.raises(EmptyDerivationError, match="no tool declares a required action"):
            build_authority_graph(Surface.EXECUTION_IDENTITY)

    def test_a_policy_with_no_roles_raises(self, tmp_path: Path) -> None:
        with pytest.raises(EmptyDerivationError, match="no canonical role"):
            build_authority_graph(Surface.TOOL_EXPOSURE, _policy(tmp_path, []))

    def test_a_policy_whose_agents_are_not_a_list_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "agent-policy.json"
        path.write_text(json.dumps({"agents": {"orchestrator": {}}}), encoding="utf-8")
        with pytest.raises(EmptyDerivationError, match="no canonical role"):
            build_authority_graph(Surface.TOOL_EXPOSURE, path)

    def test_a_policy_declaring_no_action_raises(self, tmp_path: Path) -> None:
        agents = [{"id": "orchestrator", "allowed_actions": []}]
        with pytest.raises(EmptyDerivationError, match="declares no action"):
            build_authority_graph(Surface.TOOL_EXPOSURE, _policy(tmp_path, agents))

    def test_a_policy_gating_every_action_raises(self, tmp_path: Path) -> None:
        """Roles and actions exist, and no role can act without a human. That is
        a broken model rather than a maximally safe one, and a graph with no
        grant edge satisfies every reachability assertion trivially."""
        agents = [
            {
                "id": "release-auditor",
                "allowed_actions": ["external_write"],
                "human_approval_required_for": ["external_write"],
            }
        ]
        with pytest.raises(EmptyDerivationError, match="no canonical role is granted any action"):
            build_authority_graph(Surface.EXECUTION_IDENTITY, _policy(tmp_path, agents))


class TestTheGovernanceLayerDoesNotDependOnTheGraph:
    """AC-GEA-6 / C-GEA-2. The graph reads the governance layer. The reverse edge
    would put a derived view underneath the thing it derives from, and a stale
    view of governance state is a security bug rather than a performance one."""

    def test_governance_layer_does_not_import_the_graph(self) -> None:
        scanned: list[Path] = sorted((SHARED / "governance").rglob("*.py"))
        scanned += [SHARED / "write_policy.py", SHARED / "read_policy.py", SHARED / "agent_authority.py"]
        assert len(scanned) > len(GRAPH_MODULES), "the governance scan found almost nothing; the paths moved"

        offenders = {str(path.relative_to(REPO)): found for path in scanned if (found := _imports_the_graph(path))}
        assert offenders == {}, (
            f"the governance layer imports the authority graph: {offenders}. C-GEA-2 forbids it; the "
            "graph must recompute from the governance layer, never be consulted by it"
        )

    def test_the_import_scan_detects_an_introduced_import(self, tmp_path: Path) -> None:
        """The negative control. Without it the assertion above passes whenever
        the scanner is broken, which is the failure mode it exists to avoid."""
        plain = _fixture(tmp_path, "plain", "from harness.shared.agent_authority import allowed_actions\n")
        dotted = _fixture(tmp_path, "dotted", "import harness.shared.authority_graph\n")
        from_module = _fixture(tmp_path, "from_module", "from harness.shared.authority_graph import paths_to\n")
        submodule = _fixture(tmp_path, "submodule", "from harness.shared import authority_call_sites\n")

        assert _imports_the_graph(plain) == []
        assert _imports_the_graph(dotted)
        assert _imports_the_graph(from_module)
        assert _imports_the_graph(submodule)

    def test_the_graph_imports_the_governance_layer(self) -> None:
        """The edge that must exist, in the direction it must run: the surfaces
        are derived by calling ``allowed_actions`` and ``decide`` rather than by
        restating either."""
        source = (SHARED / "authority_graph.py").read_text(encoding="utf-8")
        assert "from harness.shared import agent_authority" in source
        assert "from harness.shared.governance.policy_decision import decide" in source

    def test_neither_module_adds_a_dependency(self) -> None:
        """C-GEA-1: standard library and first-party only, asserted from the
        import statements rather than from a prose claim -- ``make lock-check``
        can only prove the lock file did not move, not why."""
        for name in GRAPH_MODULES:
            roots = _imported_roots(SHARED / f"{name}.py")
            assert roots, f"{name} imports nothing; the parse read the wrong file"
            outside = sorted(root for root in roots if root != "harness" and root not in sys.stdlib_module_names)
            assert outside == [], f"{name} imports {outside}, which C-GEA-1 forbids (no networkx, no new lock entry)"
