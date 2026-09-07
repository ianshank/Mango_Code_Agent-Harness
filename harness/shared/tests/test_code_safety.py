"""The pre-write prohibited-symbol check decides all three shapes, or raises.

Spec: ``docs/specs/graph-engineering-adoption.md`` (R-GEA-3, R-GEA-4, C-GEA-3;
AC-GEA-5). The failure these tests exist to catch is not "the checker missed a
case" but "the checker cannot fail": ``synthesis.prohibited_imports`` spans
importable modules, attribute targets reached through a bare ``import os``, and
a builtin no import statement names, so an ``ast.Import``-only reading decides
two of five entries and passes the rest in silence.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from harness.shared.code_safety import (
    ProhibitedSymbol,
    ProhibitedSymbolPolicyError,
    load_prohibited_symbols,
    prohibited_symbol_denial,
    prohibited_symbol_findings,
)

pytestmark = pytest.mark.governance

#: The live policy's five entries, restated so these tests state the corpus they
#: judge rather than inheriting whatever the policy happens to say today. The
#: agreement between the two is asserted separately, in
#: ``TestTheLivePolicyIsTheCorpusUnderTest``.
ENTRIES = ("os.system", "subprocess", "shutil.rmtree", "importlib", "__import__")


def findings_for(source: str, prohibited: tuple[str, ...] = ENTRIES) -> list[ProhibitedSymbol]:
    """Parse ``source`` the way the write door does, then judge the tree."""
    return prohibited_symbol_findings(ast.parse(source), prohibited)


def entries_in(source: str, prohibited: tuple[str, ...] = ENTRIES) -> list[str]:
    return [finding.policy_entry for finding in findings_for(source, prohibited)]


def write_policy_file(tmp_path: Path, synthesis: object) -> Path:
    """A temporary governance policy carrying exactly the ``synthesis`` block given."""
    path = tmp_path / "governance-policy.json"
    path.write_text(json.dumps({"synthesis": synthesis}), encoding="utf-8")
    return path


class TestImportableModules:
    """`subprocess` and `importlib`: the two entries an import-only checker gets right."""

    def test_plain_import(self) -> None:
        assert entries_in("import subprocess\n") == ["subprocess"]

    def test_aliased_import(self) -> None:
        findings = findings_for("import subprocess as sp\nsp.run(['ls'])\n")
        assert [f.policy_entry for f in findings] == ["subprocess", "subprocess"]
        assert findings[1].reference == "sp.run"
        assert findings[1].lineno == 2

    def test_from_import_reports_the_entry_once_per_line(self) -> None:
        """`from subprocess import run` matches through both the module and the alias."""
        findings = findings_for("from subprocess import run\n")
        assert [f.policy_entry for f in findings] == ["subprocess"]
        assert findings[0].lineno == 1

    def test_dotted_submodule_matches_the_package_entry(self) -> None:
        """Prohibiting `importlib` while admitting `importlib.util` decides nothing."""
        assert entries_in("import importlib.util\n") == ["importlib"]

    def test_dotted_from_import_matches_the_package_entry(self) -> None:
        assert entries_in("from importlib.util import spec_from_file_location\n") == ["importlib"]

    def test_aliased_submodule_use_resolves(self) -> None:
        findings = findings_for("import importlib.util as iu\niu.spec_from_file_location('m', 'p')\n")
        assert [f.reference for f in findings] == ["importlib.util", "iu.spec_from_file_location"]

    def test_a_relative_import_is_not_the_distribution(self) -> None:
        """`from . import subprocess` names a sibling module, not the stdlib one."""
        assert findings_for("from . import subprocess\n") == []


class TestAttributeTargets:
    """`os.system` and `shutil.rmtree`: reachable through a bare `import os`."""

    def test_attribute_call_through_a_plain_import(self) -> None:
        findings = findings_for("import os\nos.system('rm -rf /')\n")
        assert [f.policy_entry for f in findings] == ["os.system"]
        assert findings[0].reference == "os.system"
        assert findings[0].lineno == 2

    def test_attribute_call_through_an_aliased_import(self) -> None:
        findings = findings_for("import os as o\no.system('rm -rf /')\n")
        assert [(f.policy_entry, f.reference) for f in findings] == [("os.system", "o.system")]

    def test_direct_binding_from_an_import_from(self) -> None:
        findings = findings_for("from os import system\nsystem('rm -rf /')\n")
        assert [f.policy_entry for f in findings] == ["os.system", "os.system"]
        assert [f.lineno for f in findings] == [1, 2]

    def test_renamed_direct_binding(self) -> None:
        findings = findings_for("from os import system as sh\nsh('rm -rf /')\n")
        assert [(f.policy_entry, f.reference) for f in findings] == [("os.system", "os.system"), ("os.system", "sh")]

    def test_star_import_binds_the_prohibited_attribute(self) -> None:
        """`from os import *` then `system(...)` would otherwise be the one-line bypass."""
        assert entries_in("from os import *\nsystem('rm -rf /')\n") == ["os.system"]

    def test_second_attribute_entry(self) -> None:
        assert entries_in("import shutil\nshutil.rmtree('/')\n") == ["shutil.rmtree"]

    def test_importing_the_module_alone_is_allowed(self) -> None:
        """`import os` is not prohibited; only the named attribute is."""
        assert findings_for("import os\nprint(os.getenv('HOME'), os)\n") == []

    def test_a_reference_rooted_in_a_call_is_not_resolved(self) -> None:
        """Resolving `f().system` needs values a single-module check does not have."""
        assert findings_for("import os\ndef f():\n    return os\nf().system('x')\n") == []

    def test_an_unrelated_attribute_of_the_same_name_is_not_flagged(self) -> None:
        assert findings_for("class Shell:\n    system = 1\nShell().system\n") == []

    def test_literal_getattr_attribute_is_resolved(self) -> None:
        findings = findings_for("import os\ngetattr(os, 'system')('x')\n")
        assert [(f.policy_entry, f.lineno) for f in findings] == [("os.system", 2)]


class TestTheBuiltinNoImportNames:
    """`__import__`: the third shape, invisible to an `ast.Import` walk."""

    def test_bare_builtin_call(self) -> None:
        findings = findings_for("__import__('os').system('x')\n")
        assert [f.policy_entry for f in findings] == ["__import__"]
        assert findings[0].lineno == 1

    def test_builtin_passed_as_a_value(self) -> None:
        assert entries_in("loader = __import__\n") == ["__import__"]


class TestTheBuiltinsNamespaceIsNotADetour:
    """The same builtin, spelled through the module that holds it.

    Every entry of the policy that names a builtin has a second spelling --
    ``builtins.<name>`` -- which a prefix-only comparison neither equals nor is
    prefixed by. Both forms below are two lines long and were admitted, so the
    one entry the policy declares *because* no import statement names it was the
    one entry two import statements could reach.
    """

    def test_the_attribute_form_resolves_to_the_bare_entry(self) -> None:
        """``import builtins`` then ``builtins.__import__('os')``."""
        findings = findings_for("import builtins\nbuiltins.__import__('os')\n")
        assert [(f.policy_entry, f.reference, f.lineno) for f in findings] == [("__import__", "builtins.__import__", 2)]

    def test_the_renamed_from_import_form_resolves_to_the_bare_entry(self) -> None:
        """``from builtins import __import__ as load`` then ``load('os')``."""
        findings = findings_for("from builtins import __import__ as load\nload('os')\n")
        assert [(f.policy_entry, f.reference, f.lineno) for f in findings] == [
            ("__import__", "builtins.__import__", 1),
            ("__import__", "load", 2),
        ]

    def test_the_namespace_itself_is_not_prohibited(self) -> None:
        """A check that denied ``import builtins`` would deny ordinary modules.

        The normalisation strips the namespace before matching; it does not add
        ``builtins`` to the prohibited list.
        """
        assert findings_for("import builtins\nprint(builtins.len([1]))\n") == []

    def test_literal_getattr_builtin_is_resolved(self) -> None:
        findings = findings_for("import builtins\ngetattr(builtins, '__import__')('os')\n")
        assert [(f.policy_entry, f.lineno) for f in findings] == [("__import__", 2)]

    def test_the_denial_names_the_entry_and_the_spelling(self, tmp_path: Path) -> None:
        """The author has to see both: the rule, and the name their file contains."""
        policy = write_policy_file(tmp_path, {"prohibited_imports": list(ENTRIES)})
        reason = prohibited_symbol_denial(ast.parse("import builtins\nbuiltins.__import__('os')\n"), policy)
        assert reason is not None
        assert "__import__ as builtins.__import__ (line 2)" in reason


class TestBenignCodePasses:
    """A check that denied everything would be as useless as one that denied nothing."""

    def test_ordinary_stdlib_use(self) -> None:
        source = (
            "from pathlib import Path\nimport json\n\n\n"
            "def read(p: str) -> dict:\n    return json.loads(Path(p).read_text())\n"
        )
        assert findings_for(source) == []

    def test_an_empty_module(self) -> None:
        assert findings_for("") == []

    def test_prohibited_names_inside_string_content_are_not_code(self) -> None:
        """Non-Python content reaches the tree only as a constant, never as a reference."""
        source = '"""import subprocess and call os.system(...) — prose, not code."""\nDOC = "__import__"\n'
        assert findings_for(source) == []

    def test_a_local_binding_of_a_prohibited_name_is_not_a_read(self) -> None:
        assert findings_for("subprocess = 1\nimportlib = 2\n") == []


class TestSpecificityAndOrdering:
    def test_the_most_specific_entry_is_reported(self) -> None:
        """With both `os` and `os.system` prohibited, the call reports `os.system`."""
        findings = findings_for("import os\nos.system('x')\n", ("os", "os.system"))
        assert [f.policy_entry for f in findings] == ["os", "os.system"]

    def test_findings_are_ordered_by_line(self) -> None:
        source = "import shutil\nimport os\nos.system('x')\nshutil.rmtree('/')\n"
        assert [f.lineno for f in findings_for(source)] == [3, 4]


class TestFailClosed:
    """AC-GEA-5: every shape of an unusable list raises instead of passing."""

    def test_empty_list_passed_directly(self) -> None:
        with pytest.raises(ProhibitedSymbolPolicyError, match="empty"):
            prohibited_symbol_findings(ast.parse("import subprocess\n"), [])

    def test_a_bare_string_passed_directly(self) -> None:
        """A `str` satisfies `Sequence[str]`, so this call typechecks and the guard
        is the only thing that catches it -- which is exactly why the guard exists.
        No `type: ignore` here: mypy raises no error to silence, and an inert
        directive would be flagged by both `--warn-unused-ignores` and RUF100."""
        with pytest.raises(ProhibitedSymbolPolicyError, match="must be a list of strings"):
            prohibited_symbol_findings(ast.parse(""), "subprocess")

    def test_a_non_string_member_passed_directly(self) -> None:
        with pytest.raises(ProhibitedSymbolPolicyError, match="non-empty strings"):
            prohibited_symbol_findings(ast.parse(""), ["subprocess", 7])  # type: ignore[list-item]

    def test_a_blank_member_passed_directly(self) -> None:
        with pytest.raises(ProhibitedSymbolPolicyError, match="non-empty strings"):
            prohibited_symbol_findings(ast.parse(""), ["subprocess", "   "])

    def test_missing_key_in_a_present_policy(self, tmp_path: Path) -> None:
        policy = write_policy_file(tmp_path, {"max_repair_cycles": 3})
        with pytest.raises(ProhibitedSymbolPolicyError, match="is missing"):
            load_prohibited_symbols(policy)

    def test_missing_section_in_a_present_policy(self, tmp_path: Path) -> None:
        path = tmp_path / "governance-policy.json"
        path.write_text(json.dumps({"coverage": {"lines": 90}}), encoding="utf-8")
        with pytest.raises(ProhibitedSymbolPolicyError, match="is missing"):
            load_prohibited_symbols(path)

    def test_a_section_that_is_not_an_object(self, tmp_path: Path) -> None:
        with pytest.raises(ProhibitedSymbolPolicyError, match="is missing"):
            load_prohibited_symbols(write_policy_file(tmp_path, "prohibited"))

    def test_an_absent_policy_file(self, tmp_path: Path) -> None:
        """No policy means no list, and no list means no judgement to make."""
        with pytest.raises(ProhibitedSymbolPolicyError, match="is missing"):
            load_prohibited_symbols(tmp_path / "nothing-here.json")

    def test_empty_list_in_a_present_policy(self, tmp_path: Path) -> None:
        policy = write_policy_file(tmp_path, {"prohibited_imports": []})
        with pytest.raises(ProhibitedSymbolPolicyError, match="empty"):
            load_prohibited_symbols(policy)

    def test_wrong_type_in_a_present_policy(self, tmp_path: Path) -> None:
        policy = write_policy_file(tmp_path, {"prohibited_imports": "subprocess"})
        with pytest.raises(ProhibitedSymbolPolicyError, match="must be a list of strings"):
            load_prohibited_symbols(policy)

    def test_non_string_member_in_a_present_policy(self, tmp_path: Path) -> None:
        policy = write_policy_file(tmp_path, {"prohibited_imports": ["subprocess", 3]})
        with pytest.raises(ProhibitedSymbolPolicyError, match="non-empty strings"):
            load_prohibited_symbols(policy)

    def test_the_denial_helper_propagates_the_refusal(self, tmp_path: Path) -> None:
        """The raise must reach the write door rather than being swallowed into `None`."""
        policy = write_policy_file(tmp_path, {"prohibited_imports": []})
        with pytest.raises(ProhibitedSymbolPolicyError):
            prohibited_symbol_denial(ast.parse("import pathlib\n"), policy_path=policy)


class TestTheDenialText:
    def test_benign_code_yields_no_denial(self, tmp_path: Path) -> None:
        policy = write_policy_file(tmp_path, {"prohibited_imports": list(ENTRIES)})
        assert prohibited_symbol_denial(ast.parse("import pathlib\n"), policy_path=policy) is None

    def test_the_denial_names_the_policy_entry_and_the_line(self, tmp_path: Path) -> None:
        policy = write_policy_file(tmp_path, {"prohibited_imports": list(ENTRIES)})
        reason = prohibited_symbol_denial(ast.parse("import os\nos.system('x')\n"), policy_path=policy)
        assert reason is not None
        assert "synthesis.prohibited_imports" in reason
        assert "symbol: os.system (line 2)" in reason

    def test_a_rename_is_reported_alongside_the_entry(self, tmp_path: Path) -> None:
        policy = write_policy_file(tmp_path, {"prohibited_imports": list(ENTRIES)})
        reason = prohibited_symbol_denial(ast.parse("import os as o\no.system('x')\n"), policy_path=policy)
        assert reason is not None
        assert "os.system as o.system (line 2)" in reason

    def test_several_findings_are_all_named(self, tmp_path: Path) -> None:
        policy = write_policy_file(tmp_path, {"prohibited_imports": list(ENTRIES)})
        reason = prohibited_symbol_denial(ast.parse("import subprocess\nimport importlib\n"), policy_path=policy)
        assert reason is not None
        assert "symbols:" in reason
        assert "subprocess (line 1)" in reason
        assert "importlib (line 2)" in reason


class TestTheLivePolicyIsTheCorpusUnderTest:
    """The entries above are a restatement; this is what pins them to the policy."""

    def test_the_default_policy_declares_the_five_entries(self) -> None:
        assert set(load_prohibited_symbols()) == set(ENTRIES)

    def test_every_live_entry_is_decided_by_the_checker(self) -> None:
        """The vacuity guard: each entry must be reachable by some module the checker denies."""
        witnesses = {
            "subprocess": "import subprocess\n",
            "importlib": "import importlib.util\n",
            "os.system": "import os\nos.system('x')\n",
            "shutil.rmtree": "import shutil as sh\nsh.rmtree('/')\n",
            "__import__": "__import__('os')\n",
        }
        live = load_prohibited_symbols()
        assert set(witnesses) == set(live), "a policy entry gained or lost a witness; add one before shipping it"
        for entry, source in witnesses.items():
            assert entry in entries_in(source, live), f"{entry} is declared but nothing the checker sees reaches it"
