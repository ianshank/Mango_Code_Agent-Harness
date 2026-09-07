"""Regression: generated code naming a prohibited symbol was written to disk.

Spec: docs/specs/graph-engineering-adoption.md (R-GEA-3, C-GEA-3, AC-GEA-4).
Decision: docs/decisions/DEC-065.md.

`execute_generate_code` parsed every generated Python module with `ast.parse` to
answer "does it compile", discarded the tree, and wrote. `governance-policy.json`
had been declaring `synthesis.prohibited_imports` the whole time, and the same
tree could decide it before a byte reached disk.

Two things had to be wrong at once for this to ship, and this file reproduces
both:

* **The analysis was thrown away.** The defect is not "the check was wrong", it
  is "there was no check at the write door at all" -- so the reproduction is
  end-to-end through `execute_generate_code`, and asserts that *nothing at all*
  appeared under the workspace, not merely that the named target is absent.
* **The obvious checker would have decided two of five.** The policy key is
  called `prohibited_imports`, and its entries span three shapes: importable
  modules (`subprocess`, `importlib`), attribute targets reachable through a
  bare `import os` (`os.system`, `shutil.rmtree`), and a builtin no import
  statement ever names (`__import__`). A walk over `ast.Import` / `ast.ImportFrom`
  -- the reading the key's own name invites -- passes the last three in silence.
  So the shapes here are *derived from the policy list*, and the run fails
  closed if that list stops spanning them.

A third thing was wrong, found later and reproduced here beside the first two:

* **The checker read attribute chains, and `getattr` is not one.**
  `os.system(...)` and `getattr(os, "system")(...)` reach the same attribute;
  only the first is an `ast.Attribute`. The check saw `getattr` and `os`,
  neither of which the policy names, and wrote the file. `import os` is not
  prohibited and neither is `import builtins`, so for every entry that is an
  attribute target or the unnamed builtin, the reflective line below is the
  *only* reason the write is refused -- which is what makes these end-to-end
  cases a reproduction rather than a restatement.

What would regress: reverting the write-door wiring in `tool_executors.py`, or
narrowing `code_safety.py`/`code_symbols.py` to import statements or to
attribute chains. All three were run as mutations against this file before it
landed; each turns a `test_no_byte_lands_*` case red and leaves the rest of the
suite green, which is the whole reason the reproduction is here rather than
folded into the unit tier.

The last class is the pre-fix behaviour, still live and by decision: `write_file`
and `apply_patch` reach the same paths and still accept what this door refuses,
because DEC-065 and the spec both scope the change to one door under C-CGT-2.
Reading them is how this stays a reproduction of a defect rather than a
restatement of the current code.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from harness.shared.code_safety import load_prohibited_symbols
from harness.shared.tests._helpers import REPO, snapshot_tree
from harness.shared.tool_executors import execute_apply_patch, execute_generate_code, execute_write_file
from harness.shared.tool_result_format import DENIED_POLICY, tool_outcome

pytestmark = pytest.mark.governance

logger = logging.getLogger(__name__)

DEC_065 = REPO / "docs" / "decisions" / "DEC-065.md"
GRAPH_SPEC = REPO / "docs" / "specs" / "graph-engineering-adoption.md"

#: The three shapes `synthesis.prohibited_imports` spans, named so a failure
#: says which one stopped being represented rather than only that a count moved.
IMPORTABLE_MODULE = "an importable module"
ATTRIBUTE_TARGET = "an attribute reached through a bare import"
UNNAMED_BUILTIN = "a builtin no import statement names"


def _shape_of(entry: str) -> str:
    """Which of the three shapes a policy entry is, from the entry alone."""
    if "." in entry:
        return ATTRIBUTE_TARGET
    if entry.startswith("__") and entry.endswith("__"):
        return UNNAMED_BUILTIN
    return IMPORTABLE_MODULE


def _module_reaching(entry: str) -> str:
    """A minimal, syntactically valid module that reaches ``entry``.

    Built per shape rather than per name, so a sixth policy entry is exercised
    the day it is declared instead of the day someone remembers to add a case.
    Syntactic validity matters: a module that fails to parse would be refused by
    the syntax check that shipped years earlier, and would prove nothing about
    the check under test.
    """
    shape = _shape_of(entry)
    if shape == ATTRIBUTE_TARGET:
        head, _, attribute = entry.partition(".")
        return f"import {head}\n\n\n{head}.{attribute}()\n"
    if shape == UNNAMED_BUILTIN:
        return f'{entry}("os")\n'
    return f"import {entry}\n"


def _reflective_module_reaching(entry: str) -> str:
    """A module that reaches ``entry`` by handing its name to ``getattr`` as a string.

    Built per shape from the entry, like ``_module_reaching``, so the reflective
    spelling of a sixth entry is exercised the day it is declared. For every
    shape but the importable module, nothing on the import line is prohibited --
    ``os`` and ``builtins`` are ordinary imports -- so the last line is the whole
    of the reason the write is refused.
    """
    shape = _shape_of(entry)
    if shape == ATTRIBUTE_TARGET:
        head, _, attribute = entry.partition(".")
        return f'import {head}\n\n\ngetattr({head}, "{attribute}")()\n'
    if shape == UNNAMED_BUILTIN:
        return f'import builtins\n\n\ngetattr(builtins, "{entry}")("os")\n'
    return f'import {entry}\n\n\ngetattr({entry}, "run")\n'


def _computed_module_reaching(entry: str) -> str:
    """The same read with a key the module computes rather than writes down.

    The base is what is judged here, not the key: the policy forbids something
    under ``os`` and under ``builtins``, so a computed attribute of either could
    name it. ``chosen`` is never defined, which the write door does not care
    about -- it judges what the file contains, and this file parses.
    """
    base = "builtins" if _shape_of(entry) == UNNAMED_BUILTIN else entry.partition(".")[0]
    return f"import {base}\n\n\ngetattr({base}, chosen)\n"


@pytest.fixture(scope="module")
def prohibited() -> tuple[str, ...]:
    """`synthesis.prohibited_imports`, read through the accessor that fails closed."""
    entries = load_prohibited_symbols()
    assert entries, "the policy declares no prohibited symbols; every assertion here would be vacuous"
    return entries


class TestProhibitedCodeReachedDisk:
    """Every policy entry, end to end, with the whole workspace as the witness."""

    def test_no_byte_lands_for_any_prohibited_entry(self, tmp_path: Path, prohibited: tuple[str, ...]) -> None:
        """AC-GEA-4: zero bytes written, a pre-existing file byte-for-byte unchanged.

        The assertion is a hash of every file under the workspace before and
        after, not `not target.exists()`: the defect was "the write happened",
        and a check that only looks where the write was aimed cannot see a
        partial write, a temporary file, or a directory created on the way.
        """
        sentinel = b"ORIGINAL = 1\n"
        for index, entry in enumerate(prohibited):
            existing = tmp_path / f"existing_{index}.py"
            existing.write_bytes(sentinel)
            before = snapshot_tree(tmp_path)

            over_existing = execute_generate_code(tmp_path, existing.name, _module_reaching(entry))
            over_nothing = execute_generate_code(tmp_path, f"generated/fresh_{index}.py", _module_reaching(entry))

            for result in (over_existing, over_nothing):
                assert tool_outcome(result) == DENIED_POLICY, f"{entry} ({_shape_of(entry)}) was not denied: {result}"
                assert entry in result, f"the denial does not name {entry!r}, so an author cannot act on it: {result}"
            assert snapshot_tree(tmp_path) == before, f"writing {entry} changed the workspace"
            assert not (tmp_path / "generated").exists(), (
                f"the denied write for {entry} still created its parent directory; the refusal has to happen "
                "before any filesystem effect, not only before the file"
            )
            logger.debug("entry %r (%s) denied with the workspace unchanged", entry, _shape_of(entry))

    def test_ordinary_code_still_writes(self, tmp_path: Path) -> None:
        """The positive control the criterion names.

        A write door that refused everything would satisfy the test above while
        breaking the tool, and the whole point of R-GEA-3 is that this is a
        narrowing of one input class rather than a closed door.
        """
        allowed = "from pathlib import Path\n\n\ndef here() -> Path:\n    return Path('.')\n"
        before = snapshot_tree(tmp_path)
        result = execute_generate_code(tmp_path, "ok.py", allowed)
        assert "Success: Generated" in result, result
        assert (tmp_path / "ok.py").read_text(encoding="utf-8") == allowed
        assert snapshot_tree(tmp_path) != before, "the control wrote nothing, so the comparison above proves nothing"

    def test_the_policy_list_still_spans_the_three_shapes(self, prohibited: tuple[str, ...]) -> None:
        """The anti-vacuity guard, and the reason this defect class existed.

        A checker built on `ast.Import` / `ast.ImportFrom` decides only the
        importable shape. If the policy list narrowed to that shape, this file
        would keep passing while proving nothing about the other two -- so the
        list losing a shape is a failure here rather than a silent reduction in
        what the reproduction covers.
        """
        found = {_shape_of(entry) for entry in prohibited}
        missing = sorted({IMPORTABLE_MODULE, ATTRIBUTE_TARGET, UNNAMED_BUILTIN} - found)
        assert not missing, (
            f"synthesis.prohibited_imports no longer spans {missing}; the entries are {list(prohibited)}. "
            "An import-only checker decides the importable shape alone, so a list that stops spanning the "
            "three no longer exercises the defect this reproduction exists for."
        )


class TestReflectiveCodeReachedDiskToo:
    """The same entries, spelled as a string, through the same door.

    Kept separate from the class above because the defect is separate: that one
    is "the analysis was thrown away", this one is "the analysis read attribute
    chains and a string is not one". Each was a live bypass of a check the other
    passed.
    """

    def test_no_byte_lands_for_a_reflective_spelling_of_any_entry(
        self, tmp_path: Path, prohibited: tuple[str, ...]
    ) -> None:
        """AC-GEA-4 again, for the reflective spelling: zero bytes, nothing created.

        The whole workspace is the witness, for the reason the direct case gives:
        a check that only looks where the write was aimed cannot see a partial
        write, a temporary file, or a directory created on the way.
        """
        for index, entry in enumerate(prohibited):
            source = _reflective_module_reaching(entry)
            existing = tmp_path / f"reflective_{index}.py"
            existing.write_bytes(b"ORIGINAL = 1\n")
            before = snapshot_tree(tmp_path)

            over_existing = execute_generate_code(tmp_path, existing.name, source)
            over_nothing = execute_generate_code(tmp_path, f"reflected/fresh_{index}.py", source)

            for result in (over_existing, over_nothing):
                assert tool_outcome(result) == DENIED_POLICY, f"{entry} via getattr was not denied: {result}"
                assert entry in result, f"the denial does not name {entry!r}: {result}"
                assert f"(line {len(source.splitlines())})" in result, (
                    f"the denial for {entry!r} does not cite the reflective line, so it was refused for "
                    f"something else on the way: {result}"
                )
            assert snapshot_tree(tmp_path) == before, f"writing {entry} through getattr changed the workspace"
            assert not (tmp_path / "reflected").exists()
            logger.debug("entry %r denied through a literal getattr key with the workspace unchanged", entry)

    def test_no_byte_lands_for_a_computed_key_on_a_forbidden_base(
        self, tmp_path: Path, prohibited: tuple[str, ...]
    ) -> None:
        """The key the module never writes down, judged by the base it is read from."""
        for index, entry in enumerate(prohibited):
            source = _computed_module_reaching(entry)
            before = snapshot_tree(tmp_path)
            result = execute_generate_code(tmp_path, f"computed_{index}.py", source)
            assert tool_outcome(result) == DENIED_POLICY, f"{entry} via a computed key was not denied: {result}"
            assert entry in result, f"the denial does not name {entry!r}: {result}"
            assert snapshot_tree(tmp_path) == before, f"the denied write for {entry} changed the workspace"

    def test_ordinary_reflection_still_writes(self, tmp_path: Path) -> None:
        """The positive control, and the reason the computed-key rule is narrow.

        `getattr(self, name)` is how ordinary Python reaches a field chosen at
        runtime. A rule that denied it would deny correct code at the write door,
        and a check that denies correct code is switched off rather than
        satisfied -- taking the four cases above with it.
        """
        allowed = "class C:\n    def get(self, name):\n        return getattr(self, name, None)\n"
        result = execute_generate_code(tmp_path, "reflective_ok.py", allowed)
        assert "Success: Generated" in result, result
        assert (tmp_path / "reflective_ok.py").read_text(encoding="utf-8") == allowed


class TestTheCheckIsScopedToTheOneDoorTheRecordNames:
    """The pre-fix behaviour is still live at the sibling doors, by decision.

    `write_file` and `apply_patch` reach the same paths and write the same
    bytes, and both still accept a module naming a prohibited symbol. That is
    not an oversight: DEC-065 states that they are "unchanged, preserving
    C-CGT-2", and `docs/specs/code-generation-tool.md`'s C-CGT-2 is what says
    only the code-generation door changes.

    Exercising them is what makes this file a reproduction rather than an
    assertion that the current code does what it does -- the shipped behaviour
    is one call away, in the same module, with no source mutation and no
    dependence on a flag. It also states the scope of the fix precisely, which
    is the half a reader is most likely to over-trust: R-GEA-3 raises the floor
    at one door and is not a containment boundary. The pairing with the record
    is the enforcement, following `test_graph_topology_parked.py`: widening the
    check to the sibling doors is a real improvement, and it has to amend the
    two documents that currently say it did not happen.
    """

    @pytest.mark.parametrize("door", ["write_file", "apply_patch"])
    def test_the_sibling_doors_still_accept_what_this_one_refuses(
        self, tmp_path: Path, prohibited: tuple[str, ...], door: str
    ) -> None:
        # An importable entry, so the patch arm can turn a permitted module into
        # a prohibited one by substituting the module name and nothing else.
        entry = next(item for item in prohibited if _shape_of(item) == IMPORTABLE_MODULE)
        source = _module_reaching(entry)
        refused = execute_generate_code(tmp_path, "refused.py", source)
        assert tool_outcome(refused) == DENIED_POLICY, f"the door under test stopped refusing {entry}: {refused}"

        target = tmp_path / "sibling.py"
        if door == "write_file":
            result = execute_write_file(tmp_path, target.name, source)
        else:
            target.write_text("import json\n", encoding="utf-8")
            result = execute_apply_patch(tmp_path, target.name, "json", entry)
        assert "Success" in result, (
            f"execute_{door} now refuses a module naming {entry}. That widens R-GEA-3 beyond the door "
            "docs/decisions/DEC-065.md and docs/specs/graph-engineering-adoption.md both record as the only "
            "one that changed -- a real improvement, but both records must be amended in the same change, "
            "and this reproduction must then move its pre-fix witness to a source mutation."
        )
        assert entry in target.read_text(encoding="utf-8"), (
            f"execute_{door} reported success without leaving {entry} on disk. The witness for the pre-fix "
            "behaviour is the file's contents, not the result string."
        )

    def test_the_records_still_scope_the_change_to_one_door(self) -> None:
        """A scope claim that lives only in code is one a later reader over-trusts."""
        for record in (DEC_065, GRAPH_SPEC):
            text = record.read_text(encoding="utf-8")
            assert "C-CGT-2" in text, (
                f"{record.relative_to(REPO)} no longer cites C-CGT-2. The sibling write doors still accept "
                "modules this one refuses, so dropping the record leaves that scope undocumented."
            )
