"""Tests for ``authority_graph``: the two grant surfaces and the boundary.

Two properties, each written against a specific way the naive version of this
check passes for the wrong reason, plus the import boundary the whole graph
rests on:

* **The approval flag is unreachable from agent input** (AC-GEA-2, R-GEA-2).
  That half moved to ``test_authority_call_sites.py`` with the scan it tests,
  when ``authority_call_sites`` was split along the analysis/reporting seam;
  this module keeps the C-GEA-2 boundary over all three modules, because a
  governance module importing the *lower* half would breach it just as squarely.
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
written into ``tmp_path`` and read by the function that reads the real tree --
no test here edits a source file, and ``agent_authority.py`` is protected.

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
    EmptyDerivationError,
    Surface,
    UnnamedSurfaceError,
    build_authority_graph,
    paths_to,
    reachable_actions,
)
from harness.shared.tests._helpers import REPO, SHARED

pytestmark = pytest.mark.governance

#: The module names the governance layer must never import (C-GEA-2), and the
#: files that must never import them. The two call-site halves are listed too:
#: the split is an implementation detail of one deliverable, and a governance
#: module importing either would breach the boundary just as squarely. Adding
#: ``authority_call_analysis`` here is what keeps the boundary from being one
#: refactor behind the code -- the module that now holds the resolver is the one
#: a governance module would be tempted to reuse.
GRAPH_MODULES = ("authority_graph", "authority_call_sites", "authority_call_analysis")

#: The three ``high_risk_actions`` that no canonical role declares. They are
#: ``command_actions.classify`` *output* rather than grants, so ``decide``
#: denies them by absence -- a different mechanism from the approval gate, and
#: the reason an undifferentiated "no high-risk action is reachable" assertion
#: is vacuous for them (finding S-1, S-2).
DENIED_BY_ABSENCE = ("destructive", "permission_change", "secret_access")

#: The two ``high_risk_actions`` that ``release-auditor`` really declares and
#: gates on human approval. These are the ones the property is non-vacuous for.
GATED_BY_APPROVAL = ("external_write", "production_change")


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
