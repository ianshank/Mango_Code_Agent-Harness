"""The approval flag is unreachable from agent input (AC-GEA-2, R-GEA-2, R-GEA-4).

``decide``'s ``human_approved`` is the one argument that turns a high-risk DENY
into an ALLOW, and the agent path reaches it only if some call site hands the
broker a mapping it did not build itself. Every test here is written against a
specific way a scan of that property passes for the wrong reason:

* **The resolver reads a name that is not the one at the call.** The guarantee
  rests on one dict literal in ``execute_run_command``, read *at the call*:
  position- and parameter-blind, the scan called six of these sites clean
  (DEC-065).
* **The enumeration misses the call entirely.** Matching only the final
  attribute name of a callee, ``invoke = broker.execute_command`` walked past
  the scan in one line while the non-empty-scan guard went on passing on the
  strength of the five direct sites -- a clean zero over a corpus that was never
  fully enumerated.
* **The scan reports on correct code and gets switched off.** Every rule here
  has a companion test pinning a shape that must stay clean, because a check
  nobody can leave on is a check nobody has.

This module tests ``authority_call_sites`` and the analysis half it rests on,
``authority_call_analysis``; ``test_authority_graph.py`` carries the surface,
high-risk and boundary halves of the same spec. Fixtures are written into
``tmp_path`` and analysed by the function that reads the real tree -- no test
here edits a source file.

Spec: ``docs/specs/graph-engineering-adoption.md``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from harness.shared.authority_graph import (
    APPROVAL_FLAG,
    EmptyDerivationError,
    approval_flag_reachability,
)
from harness.shared.tests._helpers import HARNESS, SHARED

pytestmark = pytest.mark.governance

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


class TestTheApprovalFlagIsUnreachable:
    """AC-GEA-2 / R-GEA-2. The clean result over the live tree, and every shape
    that must break it."""

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


class TestTheEnumerationCannotBeWalkedPast:
    """R-GEA-2. A call the scan does not *recognise* is not a clean call site,
    it is an absent one -- and absence reads exactly like safety. Matching only
    the final attribute name of a callee, the whole property was one line from
    being bypassed while its non-empty-scan guard stayed green on the five
    direct sites."""

    @pytest.mark.parametrize(
        "source",
        [
            pytest.param(
                """def run(broker, cmd, context):
    invoke = broker.execute_command
    return invoke(cmd, context)""",
                id="plain",
            ),
            pytest.param(
                """def run(broker, cmd, context):
    invoke: object = broker.execute_command
    return invoke(cmd, context)""",
                id="annotated",
            ),
            pytest.param(
                """def run(cmd, context):
    invoke = execute_command
    return invoke(cmd, context)""",
                id="bare_name",
            ),
            pytest.param(
                """def outer(broker):
    invoke = broker.execute_command
    def inner(cmd, context):
        return invoke(cmd, context)
    return inner""",
                id="closed_over",
            ),
        ],
    )
    def test_a_call_through_an_alias_is_a_call_site(self, tmp_path: Path, source: str) -> None:
        """Every binding shape that can leave a name holding the method: an
        assignment, an annotated assignment, the module-level function itself,
        and a closure -- the last because reading only the innermost scope would
        put the call back outside the enumeration, one ``def`` deeper."""
        (witness,) = approval_flag_reachability([_fixture(tmp_path, "alias", source)])
        assert witness.expression == "context", source
        assert "is a parameter of" in witness.reason

    @pytest.mark.parametrize(
        "source",
        [
            pytest.param("def run(broker, register):\n    register(broker.execute_command)", id="handed_on"),
            pytest.param("def run(broker):\n    return broker.execute_command", id="returned"),
            pytest.param("def run(broker):\n    return {'run': broker.execute_command}", id="in_a_container"),
            pytest.param("def run(self, broker):\n    self.invoke = broker.execute_command", id="on_an_object"),
            pytest.param(
                """def run(broker):
    first, second = broker.execute_command, None
    return first""",
                id="unpacked",
            ),
            pytest.param(
                """def run(broker, register):
    invoke = broker.execute_command
    register(invoke)""",
                id="alias_handed_on",
            ),
            pytest.param(
                """def run(broker, cmd, context):
    first = broker.execute_command
    second = first
    return second(cmd, context)""",
                id="alias_chain",
            ),
        ],
    )
    def test_a_reference_that_leaves_this_scan_is_reported(self, tmp_path: Path, source: str) -> None:
        """The other half of the enumeration. A method handed on as a value is
        called somewhere with arguments that are not in this function at all, so
        the mapping it receives is outside every rule this scan has. It is
        reported where it leaves, which is the last point the source names it.
        """
        found = approval_flag_reachability([_fixture(tmp_path, "escape", source)])
        assert found, source
        assert all("without being called" in w.reason for w in found), found
        assert all(APPROVAL_FLAG in w.reason for w in found), found

    def test_an_alias_carrying_a_literal_context_is_not_reported(self, tmp_path: Path) -> None:
        """The control that keeps the rule usable. Binding the method to a name
        is not itself the defect -- handing it a mapping the function did not
        build is -- so an alias called with a literal must stay clean, exactly
        as the same call spelled out would."""
        path = _fixture(
            tmp_path,
            "alias_literal",
            "def run(broker, cmd, role):\n"
            "    invoke = broker.execute_command\n"
            '    return invoke(cmd, {"agent_id": role})\n',
        )
        assert approval_flag_reachability([path]) == []

    def test_an_ordinary_local_alias_is_not_a_broker_call(self, tmp_path: Path) -> None:
        """Only a name bound to the *entry point* is followed. A rule that read
        every call through a local name as a broker call would report every call
        in the repository, and a check that fires on correct code gets switched
        off -- the same argument that keeps ``**kwargs`` resolved rather than
        flagged."""
        path = _fixture(
            tmp_path,
            "ordinary_alias",
            "def run(broker, cmd, context, role):\n"
            "    handler = other_module.run_something\n"
            "    handler(cmd, context)\n"
            '    return broker.execute_command(cmd, {"agent_id": role})\n',
        )
        assert approval_flag_reachability([path]) == []


class TestTheScanSplitRunsOneWay:
    """The analysis half may not import the reporting half.

    The split is what made room for the alias rule (NS-39 item 4), and it is
    only worth anything while the dependency runs one way: the refusal
    vocabulary is declared in the lower module so both halves and
    ``authority_graph`` import it downwards. A cycle here would mean the
    resolver could ask the reporter what a mapping means, which is the
    dependency this seam exists to forbid.
    """

    def test_the_analysis_half_imports_nothing_above_it(self) -> None:
        """By ``ast``: the analysis module's own docstring names the reporting
        one, so a text search would fail on prose rather than on an import."""
        tree = ast.parse((SHARED / "authority_call_analysis.py").read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert imported, "the analysis module imports nothing at all; the parse read the wrong file"
        assert not [name for name in imported if "authority" in name], (
            f"the analysis half imports {sorted(imported)}; the vocabulary it declares is the reason "
            "the dependency runs one way, and an upward edge would close the cycle"
        )

    def test_both_halves_share_one_refusal_vocabulary(self) -> None:
        """One class object, not two with the same name: a caller that catches
        ``AuthorityGraphError`` from ``authority_graph`` must catch what the
        scan raises."""
        from harness.shared import authority_call_analysis, authority_call_sites, authority_graph

        assert authority_call_sites.EmptyDerivationError is authority_call_analysis.EmptyDerivationError
        assert authority_graph.EmptyDerivationError is authority_call_analysis.EmptyDerivationError
        assert issubclass(authority_call_analysis.EmptyDerivationError, authority_graph.AuthorityGraphError)

    def test_the_public_surface_survived_the_split(self) -> None:
        """``authority_graph`` re-exports the scan so R-GEA-2's named module
        carries the API, and the split must not move a name out from under a
        caller. Checked against ``__all__`` rather than an import list, because
        the promise is what the module says it exports."""
        from harness.shared import authority_call_sites, authority_graph

        assert set(authority_call_sites.__all__) == {
            "APPROVAL_FLAG",
            "BROKER_ENTRY_POINTS",
            "CONTEXT_PARAMETER",
            "ApprovalWitness",
            "AuthorityGraphError",
            "EmptyDerivationError",
            "approval_flag_reachability",
        }
        assert authority_graph.approval_flag_reachability is authority_call_sites.approval_flag_reachability
