"""The pre-write prohibited-symbol check decides all three shapes, or raises.

Spec: ``docs/specs/graph-engineering-adoption.md`` (R-GEA-3, R-GEA-4, C-GEA-3;
AC-GEA-5). The failure these tests exist to catch is not "the checker missed a
case" but "the checker cannot fail": ``synthesis.prohibited_imports`` spans
importable modules, attribute targets reached through a bare ``import os``, and
a builtin no import statement names, so an ``ast.Import``-only reading decides
two of five entries and passes the rest in silence.

The same failure has two more spellings, each covered below. Every entry is
reachable through ``getattr`` -- a string is not an ``ast.Attribute``, so a
checker reading attribute chains alone decided none of the five that way. And
``synthesis.python_write_suffixes`` decides which writes are asked the question
at all, so a shape of *that* list which cannot be read leaves the whole check
undone for every target it failed to name.
"""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path

import pytest

from harness.shared import code_safety
from harness.shared.code_safety import (
    DEFAULT_PYTHON_WRITE_SUFFIXES,
    ProhibitedSymbol,
    ProhibitedSymbolPolicyError,
    load_prohibited_symbols,
    load_python_write_suffixes,
    prohibited_symbol_denial,
    prohibited_symbol_findings,
)
from harness.shared.policy_loader import PolicyError

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


class TestReflectionIsNotADetourEither:
    """The same entries, spelled as a string handed to ``getattr``.

    ``os.system(...)`` and ``getattr(os, "system")(...)`` reach the same
    attribute and only the first is an ``ast.Attribute``, so a checker reading
    attribute chains alone sees ``getattr`` and ``os`` -- neither prohibited --
    and writes the file. Every case below was admitted before the reflective
    resolution landed, and each is a two-line module.
    """

    def test_the_literal_key_resolves_to_the_attribute(self) -> None:
        findings = findings_for('import os\ngetattr(os, "system")("id")\n')
        assert [(f.policy_entry, f.reference, f.lineno) for f in findings] == [
            ("os.system", 'getattr(os, "system")', 2)
        ]

    def test_an_aliased_import_resolves_through_the_binding(self) -> None:
        """The rename machinery is shared, so `import os as o` costs the bypass nothing."""
        findings = findings_for('import os as o\ngetattr(o, "system")("id")\n')
        assert [(f.policy_entry, f.reference) for f in findings] == [("os.system", 'getattr(o, "system")')]

    def test_the_builtin_no_import_names_is_reached_through_its_namespace(self) -> None:
        findings = findings_for('import builtins\ngetattr(builtins, "__import__")("os")\n')
        assert [(f.policy_entry, f.reference, f.lineno) for f in findings] == [
            ("__import__", 'getattr(builtins, "__import__")', 2)
        ]

    def test_a_renamed_accessor_is_not_a_rename_around_the_check(self) -> None:
        """`from builtins import getattr as g` is the detour one level up."""
        findings = findings_for('from builtins import getattr as g\nimport os\ng(os, "system")("id")\n')
        assert [(f.policy_entry, f.reference, f.lineno) for f in findings] == [("os.system", 'g(os, "system")', 3)]

    def test_the_accessor_read_off_its_own_namespace(self) -> None:
        findings = findings_for('import builtins\nimport os\nbuiltins.getattr(os, "system")("id")\n')
        assert [(f.policy_entry, f.reference) for f in findings] == [("os.system", 'builtins.getattr(os, "system")')]

    def test_a_module_that_imports_its_own_getattr_is_still_judged(self) -> None:
        """The inverse direction, decided the way `_spellings` decides its own.

        A name bound to something else is not the builtin, so resolution alone
        would let this through. The written spelling counts as well, because a
        denial an author renames around costs a cycle and admitting the bypass
        costs the check.
        """
        assert entries_in('from vendor import getattr\nimport os\ngetattr(os, "system")("id")\n') == ["os.system"]

    def test_the_three_argument_form_reaches_the_same_attribute(self) -> None:
        assert entries_in('import os\ngetattr(os, "system", None)("id")\n') == ["os.system"]

    def test_nested_reads_resolve_through_the_whole_chain(self) -> None:
        """`getattr(getattr(a, "b"), "c")` is `a.b.c`, and is matched as `a.b.c`."""
        source = 'import os\ngetattr(getattr(os, "path"), "join")("a")\n'
        findings = findings_for(source, ("os.path.join",))
        assert [(f.policy_entry, f.reference) for f in findings] == [
            ("os.path.join", 'getattr(getattr(os, "path"), "join")')
        ]

    def test_an_attribute_read_off_the_result_keeps_resolving(self) -> None:
        """`getattr(os, "system").__call__("id")` calls the same object."""
        findings = findings_for('import os\ngetattr(os, "system").__call__("id")\n')
        assert [(f.policy_entry, f.reference) for f in findings] == [("os.system", 'getattr(os, "system").__call__')]

    def test_the_base_is_not_reported_a_second_time(self) -> None:
        """One line, one finding: the chain is reported, not the module inside it."""
        findings = findings_for('import subprocess\ngetattr(subprocess, "run")([])\n')
        assert [(f.reference, f.lineno) for f in findings] == [
            ("subprocess", 1),
            ('getattr(subprocess, "run")', 2),
        ]

    def test_an_attribute_the_policy_does_not_name_passes(self) -> None:
        assert findings_for('import os\nprint(getattr(os, "getenv")("HOME"))\n') == []

    def test_a_base_rooted_in_a_call_is_not_resolved(self) -> None:
        assert findings_for('import os\ndef f():\n    return os\ngetattr(f(), "system")("x")\n') == []

    def test_a_base_rooted_in_a_subscript_is_not_resolved(self) -> None:
        """A `Name`/`Attribute` chain is the whole of what this module can resolve."""
        assert findings_for('mods = {}\ngetattr(mods["os"], "system")("x")\n') == []

    def test_a_call_that_is_not_getattr_is_not_a_reflective_read(self) -> None:
        assert findings_for('import os\nprint(os, "system")\n') == []

    def test_a_callee_that_is_not_a_name_chain_is_not_a_reflective_read(self) -> None:
        assert findings_for('import os\nfuncs = []\nfuncs[0](os, "system")\n') == []

    def test_the_denial_names_the_entry_and_the_reflective_spelling(self, tmp_path: Path) -> None:
        policy = write_policy_file(tmp_path, {"prohibited_imports": list(ENTRIES)})
        reason = prohibited_symbol_denial(ast.parse('import os\ngetattr(os, "system")("id")\n'), policy)
        assert reason is not None
        assert 'os.system as getattr(os, "system") (line 2)' in reason


class TestAComputedKeyIsJudgedByWhatItsBaseCouldReach:
    """`getattr(os, name)`: the key is a string the module never writes down.

    The fail-closed reading is "report every one of them", and it is the wrong
    one -- `getattr(self, name)` is how ordinary Python reaches a field chosen
    at runtime, and a check that denies correct code is switched off rather than
    satisfied. So the rule is narrower: report only where the policy forbids
    something under the base the key is read from.
    """

    def test_a_computed_key_on_a_forbidden_base_is_reported(self) -> None:
        findings = findings_for("import os\ngetattr(os, name)('id')\n")
        assert [(f.policy_entry, f.reference, f.lineno) for f in findings] == [
            ("os.system", "getattr(os, <computed>)", 2)
        ]

    def test_a_key_bound_earlier_in_the_module_is_still_computed(self) -> None:
        """The reproduction: the name is a literal one line up, and is not folded.

        Constant folding would decide this one module and not the next, so the
        base rule decides both: `os` is a base the policy forbids something
        under, whatever the key turns out to be.
        """
        assert entries_in('import os\nname = "system"\ngetattr(os, name)("id")\n') == ["os.system"]

    def test_reflection_on_an_object_the_policy_does_not_name_passes(self) -> None:
        """The reason the rule is not "report every computed key"."""
        source = (
            "class C:\n"
            "    def get(self, name, obj, attr):\n"
            "        return getattr(self, name), getattr(obj, attr), getattr(C, name, None)\n"
        )
        assert findings_for(source) == []

    def test_the_builtins_namespace_is_reachable_by_a_computed_key(self) -> None:
        """Every single-segment entry sits under `builtins`; that is what it is."""
        assert set(entries_in("import builtins\ngetattr(builtins, name)('os')\n")) == {
            "__import__",
            "importlib",
            "subprocess",
        }

    def test_a_key_that_is_not_a_string_is_a_key_this_module_cannot_read(self) -> None:
        assert entries_in("import os\ngetattr(os, 1)\n") == ["os.system"]

    def test_a_base_that_does_not_resolve_is_not_judged(self) -> None:
        """Stated rather than hidden: the same residual as `f().system`."""
        assert findings_for("def load():\n    return None\ngetattr(load(), name)\n") == []

    def test_the_base_is_not_reported_twice_when_it_is_itself_prohibited(self) -> None:
        """`subprocess` is already a finding on that line; the rule adds nothing."""
        findings = findings_for("import subprocess\ngetattr(subprocess, name)\n")
        assert [(f.policy_entry, f.reference, f.lineno) for f in findings] == [
            ("subprocess", "subprocess", 1),
            ("subprocess", "subprocess", 2),
        ]

    def test_the_denial_says_the_key_was_not_written_down(self, tmp_path: Path) -> None:
        policy = write_policy_file(tmp_path, {"prohibited_imports": list(ENTRIES)})
        reason = prohibited_symbol_denial(ast.parse("import os\ngetattr(os, name)\n"), policy)
        assert reason is not None
        assert "os.system as getattr(os, <computed>) (line 2)" in reason


class TestEveryLiveEntryIsReachedReflectively:
    """The anti-vacuity guard for the reflective spelling, per policy entry.

    `os.system` is the entry the bypass was reported against; a fix tested only
    against it would leave the other four decided by the direct spelling alone.
    Witnesses are built per shape from the live policy, so a sixth entry is
    exercised the day it is declared.
    """

    @staticmethod
    def _literal_witness(entry: str) -> str:
        head, _, attribute = entry.partition(".")
        if attribute:
            return f'import {head}\ngetattr({head}, "{attribute}")()\n'
        if entry.startswith("__") and entry.endswith("__"):
            return f'import builtins\ngetattr(builtins, "{entry}")("os")\n'
        return f'import {entry}\ngetattr({entry}, "__name__")\n'

    @staticmethod
    def _computed_witness(entry: str) -> str:
        head, _, attribute = entry.partition(".")
        if attribute:
            return f"import {head}\ngetattr({head}, name)\n"
        if entry.startswith("__") and entry.endswith("__"):
            return "import builtins\ngetattr(builtins, name)\n"
        return f"import {entry}\ngetattr({entry}, name)\n"

    @pytest.mark.parametrize("entry", load_prohibited_symbols())
    def test_a_literal_key_reaches_the_entry_at_the_reflective_line(self, entry: str) -> None:
        live = load_prohibited_symbols()
        findings = findings_for(self._literal_witness(entry), live)
        reached = [f for f in findings if f.policy_entry == entry and f.lineno == 2]
        assert reached, f"{entry} is not reachable through a literal getattr: {findings}"

    @pytest.mark.parametrize("entry", load_prohibited_symbols())
    def test_a_computed_key_reaches_the_entry_at_the_reflective_line(self, entry: str) -> None:
        live = load_prohibited_symbols()
        findings = findings_for(self._computed_witness(entry), live)
        reached = [f for f in findings if f.policy_entry == entry and f.lineno == 2]
        assert reached, f"{entry} is not reachable through a computed getattr: {findings}"


class TestThePythonWriteSuffixList:
    """`synthesis.python_write_suffixes`: which writes are asked the question at all.

    A target the list fails to name is never judged against
    `synthesis.prohibited_imports`, so every shape that cannot be read raises
    for the same reason the prohibited list does -- with one exception, the
    adopter who has no policy file, which is a supported path rather than a
    policy that lost a key.
    """

    @staticmethod
    def _policy(tmp_path: Path, value: object) -> Path:
        return write_policy_file(tmp_path, {"python_write_suffixes": value})

    def test_the_live_policy_names_both_executable_suffixes(self) -> None:
        assert {".py", ".pyw"} <= load_python_write_suffixes()

    def test_an_absent_policy_file_uses_the_built_in_default(self, tmp_path: Path) -> None:
        assert load_python_write_suffixes(tmp_path / "nothing-here.json") == DEFAULT_PYTHON_WRITE_SUFFIXES

    def test_case_is_folded_because_the_filesystem_does_not_fold_it(self, tmp_path: Path) -> None:
        assert load_python_write_suffixes(self._policy(tmp_path, [".PY", ".Pyw"])) == {".py", ".pyw"}

    def test_the_list_is_the_policy_rather_than_a_literal(self, tmp_path: Path) -> None:
        """A suffix no module names arms the check, so the key really is the source."""
        assert ".pyx" in load_python_write_suffixes(self._policy(tmp_path, [".pyx"]))

    def test_a_supplied_policy_cannot_narrow_the_harness_floor(self, tmp_path: Path) -> None:
        """R-PPP-1, one key over: supplying a policy adds, it never takes away.

        As first written this substituted, so a digest-pinned policy naming only
        `.pyx` made `.py` not-Python and switched the prohibited-symbol check off
        for Python output -- the check reading its arming list from a document
        the adopter controls. `write_policy` had already decided this for
        protected paths; this key had simply not applied it. A review bot found
        it. The removal is reported rather than obeyed, matching how
        `write_policy` treats the keys through which a supplied policy could take
        a harness denial away.
        """
        assert DEFAULT_PYTHON_WRITE_SUFFIXES <= load_python_write_suffixes(self._policy(tmp_path, [".pyx"]))

    def test_a_supplied_policy_missing_the_key_gets_the_floor(self, tmp_path: Path) -> None:
        """Omission is the quietest removal. A policy silent on the key does not
        narrow it either -- it simply has nothing to add."""
        policy = write_policy_file(tmp_path, {"prohibited_imports": ["subprocess"]})
        assert load_python_write_suffixes(policy) == DEFAULT_PYTHON_WRITE_SUFFIXES

    def test_a_supplied_policy_missing_the_section_gets_the_floor(self, tmp_path: Path) -> None:
        path = tmp_path / "governance-policy.json"
        path.write_text(json.dumps({"coverage": {"lines": 90}}), encoding="utf-8")
        assert load_python_write_suffixes(path) == DEFAULT_PYTHON_WRITE_SUFFIXES

    def test_the_reported_removal_names_what_it_kept(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """A removal the union defeats is still an attempt, and a silent
        no-op teaches the adopter nothing about why their policy did not apply."""
        with caplog.at_level(logging.WARNING):
            load_python_write_suffixes(self._policy(tmp_path, [".pyx"]))
        assert any("omits" in record.message and "union keeps them" in record.message for record in caplog.records)

    @pytest.mark.parametrize("value", [[], "py", {}, None])
    def test_a_list_that_cannot_name_a_suffix_raises(self, tmp_path: Path, value: object) -> None:
        with pytest.raises(ProhibitedSymbolPolicyError, match="non-empty list"):
            load_python_write_suffixes(self._policy(tmp_path, value))

    @pytest.mark.parametrize("entry", ["py", " .py", ".py ", 3, ""])
    def test_an_entry_that_is_not_a_dotted_suffix_raises(self, tmp_path: Path, entry: object) -> None:
        """`Path.suffix` yields `.py`; a bare `py` would match nothing while looking sound."""
        with pytest.raises(ProhibitedSymbolPolicyError, match="dotted suffixes"):
            load_python_write_suffixes(self._policy(tmp_path, [".py", entry]))

    def test_the_refusal_is_catchable_as_a_policy_error(self, tmp_path: Path) -> None:
        """One name for "the policy cannot arm this check", whichever key lost it."""
        with pytest.raises(PolicyError):
            load_python_write_suffixes(self._policy(tmp_path, []))


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


class TestTheHarnessFloorIsTheFloor:
    """The union's own edges: where the floor comes from, and when there is none.

    `load_prohibited_symbols` and `load_python_write_suffixes` both read the
    harness policy for a floor and union a supplied policy onto it (R-PPP-1).
    These are the three branches of that lookup — the adopter with no harness
    policy at all, the broken install whose harness policy lost the key, and the
    supplied policy that drops an entry and is reported rather than obeyed.
    """

    def test_a_supplied_policy_cannot_drop_a_prohibited_symbol(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The sibling of the suffix narrowing, and the more direct one.

        A digest-pinned policy naming only `shutil.rmtree` used to *be* the
        list, so `os.system` — which the harness policy forbids — became
        writable. Pinning establishes provenance, not benignity.
        """
        narrowed = write_policy_file(tmp_path, {"prohibited_imports": ["shutil.rmtree"]})
        with caplog.at_level(logging.WARNING):
            symbols = load_prohibited_symbols(narrowed)
        assert "os.system" in symbols, "a supplied policy must not be able to drop a harness prohibition"
        assert "shutil.rmtree" in symbols, "and must still be able to add one"
        assert any("omits" in record.message for record in caplog.records)

    def test_no_harness_policy_at_all_falls_back_rather_than_raising(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The adopter path `policy_file_is_absent` exists to keep working."""
        monkeypatch.setattr(code_safety, "POLICY_PATH", tmp_path / "no-such-policy.json")
        assert load_python_write_suffixes(tmp_path / "also-absent.json") == DEFAULT_PYTHON_WRITE_SUFFIXES

    def test_a_harness_policy_that_lost_the_key_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A broken install, not an adopter choice: there is no floor to enforce.

        Distinguished from a *supplied* policy missing the key, which is silence
        rather than removal and gets the floor. Substituting a built-in default
        here would let a truncated harness policy narrow the check to whatever
        this module happens to say — the failure `policy_loader._Section._value`
        was written to refuse.
        """
        broken = write_policy_file(tmp_path, {"prohibited_imports": ["os.system"]})
        monkeypatch.setattr(code_safety, "POLICY_PATH", broken)
        with pytest.raises(ProhibitedSymbolPolicyError, match="no floor to enforce"):
            load_python_write_suffixes(tmp_path / "supplied.json")
