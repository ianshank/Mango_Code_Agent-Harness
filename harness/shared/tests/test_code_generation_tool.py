"""Unit and integration tests for the dedicated code generation writing tool (generate_code).

Spec: docs/specs/code-generation-tool.md (AC-CGT-1..AC-CGT-7) and
docs/specs/graph-engineering-adoption.md (AC-GEA-4, R-GEA-3).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from harness.shared import mango_mas_orchestrator as orch_module
from harness.shared import tool_executors as te
from harness.shared.agent_authority import tools_for_role
from harness.shared.governance.broker import ExecutionBroker
from harness.shared.policy_loader import PolicyError
from harness.shared.tool_executors import (
    DEFAULT_PYTHON_WRITE_SUFFIXES,
    PYTHON_SUFFIX_KEY,
    authorize_write,
    execute_generate_code,
    load_python_write_suffixes,
)
from harness.shared.tool_result_format import DENIED_POLICY, tool_outcome
from harness.shared.tool_schemas import NEMOTRON_TOOLS

pytestmark = pytest.mark.governance

#: Distinguishes "the key is absent" from "the key is present and falsy".
_ABSENT = object()

#: One prohibited shape, shared by the two classes below so a fix that only
#: works for the payload one of them happens to use cannot look complete.
_PROHIBITED_PAYLOAD = "import os\n\n\nos.system('id')\n"


class TestCodeGenerationTool:
    """Test suite verifying AC-CGT-1 through AC-CGT-7."""

    def test_generate_code_writes_valid_python(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """AC-CGT-1: execute_generate_code writes valid Python code and logs context."""
        caplog.set_level(logging.INFO)
        valid_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        filepath = "src/math_ops.py"

        result = execute_generate_code(tmp_path, filepath, valid_code)

        assert "Success: Generated" in result
        target = tmp_path / filepath
        assert target.is_file()
        assert target.read_text(encoding="utf-8") == valid_code
        assert any("Successfully generated" in record.message for record in caplog.records)

    def test_generate_code_syntax_error_refuses_write(self, tmp_path: Path) -> None:
        """AC-CGT-2: Syntactically invalid Python is refused before touching disk."""
        invalid_code = "def broken(:\n    pass\n"
        filepath = "src/broken.py"
        target = tmp_path / filepath

        result = execute_generate_code(tmp_path, filepath, invalid_code)

        assert "SyntaxError" in result
        assert not target.exists()

    def test_generate_code_syntax_error_preserves_existing_file(self, tmp_path: Path) -> None:
        """AC-CGT-2: If a file already exists, a syntax error does not alter it."""
        filepath = "src/existing.py"
        original_code = "x = 1\n"
        target = tmp_path / filepath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(original_code, encoding="utf-8")

        broken_code = "def unclosed_paren(\n"
        result = execute_generate_code(tmp_path, filepath, broken_code)

        assert "SyntaxError" in result
        assert target.read_text(encoding="utf-8") == original_code

    def test_generate_code_denied_on_governed_paths(self, tmp_path: Path) -> None:
        """AC-CGT-3: Targeting .mango/memory or a protected path returns denial and writes 0 bytes."""
        memory_path = ".mango/memory/hypotheses.json"
        code = '[{"id": "forged"}]'

        result = execute_generate_code(tmp_path, memory_path, code)

        assert "Denied" in result or "Error generating code" in result
        assert "inside the agent memory directory" in result
        assert not (tmp_path / memory_path).exists()

        protected_path = "harness/shared/governance-policy.json"
        result_protected = execute_generate_code(tmp_path, protected_path, "{}")
        assert "matches a protected path" in result_protected

    def test_generate_code_refuses_overwrite_when_false(self, tmp_path: Path) -> None:
        """AC-CGT-4: Refuses to overwrite when overwrite=False and file exists."""
        filepath = "src/config.py"
        target = tmp_path / filepath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("API_VERSION = 1\n", encoding="utf-8")

        new_code = "API_VERSION = 2\n"
        result = execute_generate_code(tmp_path, filepath, new_code, overwrite=False)

        assert "File exists and overwrite is False" in result
        assert target.read_text(encoding="utf-8") == "API_VERSION = 1\n"

    def test_generate_code_confinement_denial(self, tmp_path: Path) -> None:
        """AC-CGT-5: Escaping workspace fails closed with confinement denial."""
        escape_path = "../../etc/shadow_clone.py"
        code = "secret = 'bad'\n"

        result = execute_generate_code(tmp_path, escape_path, code)

        assert "path escapes workspace" in result

    def test_generate_code_requires_write_authority(self) -> None:
        """AC-CGT-6: Lacking write authority refuses write for verifier and planner."""
        broker = ExecutionBroker()

        assert authorize_write(broker, "verifier", "test.py") is not None
        assert authorize_write(broker, "planner", "test.py") is not None
        assert authorize_write(broker, "nemotron-reasoner", "test.py") is None

    def test_generate_code_json_validation(self, tmp_path: Path) -> None:
        """Valid and invalid JSON handling."""
        valid_json = '{"valid": true, "count": 42}'
        result = execute_generate_code(tmp_path, "data.json", valid_json)
        assert "Success: Generated" in result

        invalid_json = '{"invalid": true, count: 42}'
        result_invalid = execute_generate_code(tmp_path, "bad_data.json", invalid_json)
        assert "JSONDecodeError" in result_invalid
        assert not (tmp_path / "bad_data.json").exists()

    def test_generate_code_schema_filtering(self) -> None:
        """Confirm generate_code is in NEMOTRON_TOOLS and filtered by role authority."""
        declared_names = {
            func.get("name")
            for t in NEMOTRON_TOOLS
            if isinstance(t, dict) and isinstance(func := t.get("function"), dict)
        }
        assert "generate_code" in declared_names

        reasoner_names = {t["function"]["name"] for t in tools_for_role("nemotron-reasoner", NEMOTRON_TOOLS)}
        assert "generate_code" in reasoner_names

        verifier_names = {t["function"]["name"] for t in tools_for_role("verifier", NEMOTRON_TOOLS)}
        assert "generate_code" not in verifier_names

        planner_names = {t["function"]["name"] for t in tools_for_role("planner", NEMOTRON_TOOLS)}
        assert "generate_code" not in planner_names

    def test_orchestrator_dispatch_generate_code(self, tmp_path: Path) -> None:
        """Integration test: ToolDispatcher correctly executes generate_code."""
        orch = orch_module.MangoMASOrchestrator(workspace_dir=tmp_path, active_role="nemotron-reasoner")
        dispatcher = orch.execution_loop.dispatcher

        res = dispatcher.tool_handlers["generate_code"](
            {
                "filepath": "generated_module.py",
                "code": "class Service:\n    pass\n",
            }
        )
        assert "Success: Generated" in res
        assert (tmp_path / "generated_module.py").is_file()


class TestProhibitedSymbolsNeverReachDisk:
    """AC-GEA-4: the write door refuses `synthesis.prohibited_imports` before writing.

    The escalation R-GEA-3 asks for: `execute_generate_code` already parsed the
    module to answer "does it compile", and the same tree answers "does it name
    something the policy prohibits". Post-hoc analysis would mean the defect is
    already on disk and a repair cycle is already owed.

    Each shape is checked against a *pre-existing* file, because "returns a
    denial" and "changed nothing" are two properties and only the second one is
    the reason the check runs before the write rather than after it.
    """

    #: The three shapes the policy key spans, and the symbol each denial must name.
    SHAPES = (
        ("import subprocess\nsubprocess.run(['ls'])\n", "subprocess"),
        ("import os\nos.system('rm -rf /')\n", "os.system"),
        ("mod = __import__('os')\n", "__import__"),
    )

    def test_generate_code_denies_prohibited_import(self, tmp_path: Path) -> None:
        """Zero bytes written, the existing file untouched, the symbol named."""
        sentinel = "ORIGINAL = 1\n"
        for index, (code, symbol) in enumerate(self.SHAPES):
            existing = tmp_path / f"existing_{index}.py"
            existing.write_text(sentinel, encoding="utf-8")
            fresh = f"fresh_{index}.py"

            over_existing = execute_generate_code(tmp_path, existing.name, code)
            over_nothing = execute_generate_code(tmp_path, fresh, code)

            for result in (over_existing, over_nothing):
                assert symbol in result, f"{symbol} is not named in: {result}"
                assert "prohibited" in result
                assert tool_outcome(result) == DENIED_POLICY
            assert existing.read_bytes() == sentinel.encode("utf-8")
            assert not (tmp_path / fresh).exists()

        # The other half of the criterion: ordinary code still writes, so the
        # denial is a narrowing rather than a closed door.
        allowed = "from pathlib import Path\n\n\ndef here() -> Path:\n    return Path('.')\n"
        assert "Success: Generated" in execute_generate_code(tmp_path, "ok.py", allowed)
        assert (tmp_path / "ok.py").read_text(encoding="utf-8") == allowed

    def test_aliased_and_dotted_forms_are_denied(self, tmp_path: Path) -> None:
        """A rename or a submodule must not be the way past the check."""
        aliased = execute_generate_code(tmp_path, "aliased.py", "import os as o\no.system('x')\n")
        assert "os.system as o.system" in aliased
        assert not (tmp_path / "aliased.py").exists()

        dotted = execute_generate_code(tmp_path, "dotted.py", "import importlib.util\n")
        assert "importlib" in dotted
        assert not (tmp_path / "dotted.py").exists()

    def test_non_python_content_is_unaffected(self, tmp_path: Path) -> None:
        """The check reads a Python parse tree; JSON and Markdown never produce one."""
        assert "Success: Generated" in execute_generate_code(tmp_path, "d.json", '{"cmd": "os.system"}')
        assert "Success: Generated" in execute_generate_code(tmp_path, "n.md", "Never call `subprocess.run`.\n")
        assert (tmp_path / "d.json").is_file()
        assert (tmp_path / "n.md").is_file()

    def test_a_prohibited_name_in_a_docstring_is_prose(self, tmp_path: Path) -> None:
        """Denying a string constant would deny this repository's own documentation."""
        code = '"""Never call os.system or import subprocess here."""\n\nVALUE = 1\n'
        assert "Success: Generated" in execute_generate_code(tmp_path, "doc.py", code)
        assert (tmp_path / "doc.py").read_text(encoding="utf-8") == code

    def test_the_builtins_detour_is_refused_at_the_write_door(self, tmp_path: Path) -> None:
        """`__import__` reached through the module that holds it, end to end.

        `builtins.__import__("os")` is the bare `__import__` entry under a name
        the policy string neither equals nor prefixes, so the write door
        admitted it until `code_safety` normalised the namespace. Asserted here
        as well as in `test_code_safety.py` because the property that matters is
        "zero bytes reached disk", which only this path can show.
        """
        code = "import builtins\n\n\nmod = builtins.__import__('os')\n"
        result = execute_generate_code(tmp_path, "detour.py", code)
        assert "__import__" in result
        assert tool_outcome(result) == DENIED_POLICY
        assert not (tmp_path / "detour.py").exists()


class TestNeitherToolArgumentTurnsTheCheckOff:
    """R-GEA-3: `validate_syntax` and `language` are the model's, the check is not.

    Both are `generate_code` arguments the calling model fills in, so deriving
    "is this Python, and should the prohibited-symbol check run" from either let
    the agent whose output the check constrains switch it off in one field.
    DEC-065 recorded the `validate_syntax` half as an accepted residual; it is
    closed here by deciding Python from the resolved target suffix — the one
    fact about the write no argument can restate, because it is where the bytes
    land — and by running the check on every Python write regardless of the
    flag. `validate_syntax` keeps the meaning it always had, syntax *reporting*.

    Each case asserts the workspace is unchanged, not merely that the denial
    text is right: "returns a denial" and "wrote nothing" are two properties and
    the second is the one the pre-write ordering exists for.
    """

    #: One module per shape the policy key spans, so a bypass that only worked
    #: for one of them cannot hide behind the other two.
    PROHIBITED = (
        "import subprocess\n\n\nsubprocess.run(['ls'])\n",
        "import os\n\n\nos.system('rm -rf /')\n",
        "mod = __import__('os')\n",
    )

    #: Valid Python naming nothing prohibited: the control that keeps every
    #: assertion below a narrowing rather than a closed door.
    ALLOWED = "from pathlib import Path\n\n\ndef here() -> Path:\n    return Path('.')\n"

    def test_validate_syntax_false_still_refuses_prohibited_python(self, tmp_path: Path) -> None:
        """The bypass DEC-065 named: one `false` skipped the parse and the check with it."""
        for index, code in enumerate(self.PROHIBITED):
            target = f"unvalidated_{index}.py"
            result = execute_generate_code(tmp_path, target, code, validate_syntax=False)
            assert tool_outcome(result) == DENIED_POLICY, f"validate_syntax=False wrote {code!r}: {result}"
            assert "prohibited" in result
            assert not (tmp_path / target).exists()

    def test_a_python_target_declared_another_language_still_refuses(self, tmp_path: Path) -> None:
        """`language` is a claim about the content; the suffix is where it lands."""
        for index, code in enumerate(self.PROHIBITED):
            target = f"mislabelled_{index}.py"
            result = execute_generate_code(tmp_path, target, code, language="markdown")
            assert tool_outcome(result) == DENIED_POLICY, f"language='markdown' wrote {code!r}: {result}"
            assert not (tmp_path / target).exists()

    def test_both_arguments_together_still_refuse(self, tmp_path: Path) -> None:
        """Neither door is the other's fallback, so closing them singly proves little."""
        result = execute_generate_code(
            tmp_path, "both.py", self.PROHIBITED[0], language="markdown", validate_syntax=False
        )
        assert tool_outcome(result) == DENIED_POLICY
        assert not (tmp_path / "both.py").exists()

    def test_ordinary_python_still_writes_under_either_argument(self, tmp_path: Path) -> None:
        """The positive control: this is a narrowing of one input class, not a closed tool."""
        unvalidated = execute_generate_code(tmp_path, "fine_0.py", self.ALLOWED, validate_syntax=False)
        mislabelled = execute_generate_code(tmp_path, "fine_1.py", self.ALLOWED, language="markdown")
        for target, result in (("fine_0.py", unvalidated), ("fine_1.py", mislabelled)):
            assert "Success: Generated" in result, result
            assert (tmp_path / target).read_text(encoding="utf-8") == self.ALLOWED

    def test_unparseable_python_with_reporting_off_is_refused_for_want_of_a_judgement(self, tmp_path: Path) -> None:
        """A module that does not parse yields no tree, and no tree yields no findings.

        Writing it would be the vacuous pass R-GEA-4 forbids — the check would
        have reported nothing and been recorded as satisfied. The refusal names
        the policy address rather than the syntax error, because syntax
        reporting is exactly what the caller switched off.
        """
        result = execute_generate_code(tmp_path, "broken.py", "import subprocess\n(\n", validate_syntax=False)
        assert tool_outcome(result) == DENIED_POLICY
        assert "synthesis.prohibited_imports" in result
        assert "SyntaxError" not in result
        assert not (tmp_path / "broken.py").exists()

    def test_a_non_python_target_is_still_governed_by_the_flag(self, tmp_path: Path) -> None:
        """The flag keeps its meaning where the suffix does not make the file Python."""
        invalid_json = '{"invalid": true, count: 42}'
        assert "JSONDecodeError" in execute_generate_code(tmp_path, "bad.json", invalid_json)
        assert "Success: Generated" in execute_generate_code(tmp_path, "ok.json", invalid_json, validate_syntax=False)
        assert (tmp_path / "ok.json").read_text(encoding="utf-8") == invalid_json


class TestTheFilenameAxisOfTheSameBypass:
    """R-GEA-3: the suffix decides, and *which* suffixes decide is policy.

    `TestNeitherToolArgumentTurnsTheCheckOff` closed the argument axis by
    deriving Python-ness from the resolved suffix instead of from `language` or
    `validate_syntax`. It left the filename axis open, because the suffix it
    compared against was the literal `".py"`: `.pyw` is executable Python, so a
    `.pyw` target declaring `language="markdown"` wrote `os.system` to disk with
    every check nominally in place. Reported by a review bot on PR #120 and
    reproduced before it was believed.

    The fix is not "add `.pyw`". It is that the set is `synthesis.
    python_write_suffixes` in policy, because it decides whether a write is
    checked at all — and `test_the_suffix_set_is_policy_not_a_relocated_literal`
    is what keeps that a fact rather than a claim.
    """

    PROHIBITED = _PROHIBITED_PAYLOAD
    ALLOWED = "from pathlib import Path\n\n\ndef here() -> Path:\n    return Path('.')\n"

    @pytest.mark.parametrize("kwargs", [{"language": "markdown"}, {"validate_syntax": False}, {}])
    def test_a_pyw_target_is_python_whatever_the_arguments_say(self, tmp_path: Path, kwargs: dict) -> None:
        """Each argument shape that skipped the check for `.pyw` before the fix."""
        result = execute_generate_code(tmp_path, "payload.pyw", self.PROHIBITED, **kwargs)
        assert tool_outcome(result) == DENIED_POLICY, f"{kwargs} wrote a prohibited .pyw: {result}"
        assert "synthesis.prohibited_imports" in result
        assert not (tmp_path / "payload.pyw").exists(), "the denial must land before the bytes do"

    def test_the_comparison_is_case_insensitive(self, tmp_path: Path) -> None:
        """`Path.suffix` preserves case; a case-sensitive compare is the same hole."""
        result = execute_generate_code(tmp_path, "PAYLOAD.PYW", self.PROHIBITED, language="markdown")
        assert tool_outcome(result) == DENIED_POLICY
        assert not (tmp_path / "PAYLOAD.PYW").exists()

    def test_a_clean_pyw_still_writes(self, tmp_path: Path) -> None:
        """The control. Without it the assertions above pass on a closed door."""
        assert "Success: Generated" in execute_generate_code(tmp_path, "ok.pyw", self.ALLOWED)
        assert (tmp_path / "ok.pyw").read_text(encoding="utf-8") == self.ALLOWED

    def test_a_non_python_suffix_is_not_swept_in(self, tmp_path: Path) -> None:
        """Widening the set must not turn every write into a Python write."""
        assert "Success: Generated" in execute_generate_code(tmp_path, "notes.md", self.PROHIBITED)
        assert (tmp_path / "notes.md").read_text(encoding="utf-8") == self.PROHIBITED


class TestPythonWriteSuffixPolicy:
    """The accessor fails closed on every policy shape that cannot arm the check."""

    PROHIBITED = _PROHIBITED_PAYLOAD

    def _policy(self, tmp_path: Path, value: object) -> Path:
        # The section is `dict[str, object]` rather than inferred, because the
        # cases below deliberately write shapes the key forbids -- a string, an
        # int, a list with a non-string in it. Letting mypy infer
        # `dict[str, list[str]]` from the first entry makes writing those a type
        # error, and silencing that with an ignore hides the one thing this
        # helper exists to do.
        section: dict[str, object] = {"prohibited_imports": ["os.system"]}
        if value is not _ABSENT:
            section[PYTHON_SUFFIX_KEY] = value
        path = tmp_path / "governance-policy.json"
        path.write_text(json.dumps({"synthesis": section}), encoding="utf-8")
        return path

    @pytest.mark.parametrize(
        "value",
        [_ABSENT, "not-a-list", [], [".py", 7], [".py", "py"], [".py", " .pyw"]],
        ids=["missing", "not-a-list", "empty", "non-string", "undotted", "whitespace"],
    )
    def test_a_policy_that_cannot_arm_the_check_raises(self, tmp_path: Path, value: object) -> None:
        """Substituting a default here would silently narrow a security check."""
        with pytest.raises(PolicyError, match="python_write_suffixes"):
            load_python_write_suffixes(self._policy(tmp_path, value))

    def test_entries_are_case_normalised(self, tmp_path: Path) -> None:
        assert load_python_write_suffixes(self._policy(tmp_path, [".PY", ".Pyw"])) == {".py", ".pyw"}

    def test_an_absent_policy_file_falls_back_rather_than_raising(self, tmp_path: Path) -> None:
        """The adopter case `policy_file_is_absent` exists to keep working."""
        assert load_python_write_suffixes(tmp_path / "nothing-here.json") == DEFAULT_PYTHON_WRITE_SUFFIXES

    def test_the_shipped_policy_names_both_executable_suffixes(self) -> None:
        """`.pyi` is excluded on purpose: a stub is never executed."""
        shipped = load_python_write_suffixes()
        assert {".py", ".pyw"} <= shipped
        assert ".pyi" not in shipped

    def test_the_accessor_reads_a_suffix_the_module_never_mentions(self, tmp_path: Path) -> None:
        """One half of "policy, not a relocated literal": the key drives the set.

        `.pyx` appears nowhere in `tool_executors`, so a set containing it and
        nothing else can only have come from the file. Moving `".py"` into JSON
        and reading it straight back would look identical to leaving it in the
        module; a suffix the module never names cannot.
        """
        assert load_python_write_suffixes(self._policy(tmp_path, [".pyx"])) == {".pyx"}

    def test_the_write_door_decides_python_ness_by_asking_the_accessor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other half: `execute_generate_code` consults it, not a literal.

        The accessor is patched rather than the policy path, because pointing
        `active_policy_path` at a temporary file makes the *write* policy
        distrust it — an unpinned supplied policy is denied before the
        prohibited-symbol check ever runs. The first draft of this test did
        exactly that and passed on a denial it had not caused, which is the
        vacuous green this repository keeps finding in itself. So each assertion
        below names the denial *reason*, not merely that a denial happened.
        """
        monkeypatch.setattr(te, "load_python_write_suffixes", lambda *_: frozenset({".pyx"}))

        refused = execute_generate_code(tmp_path, "payload.pyx", self.PROHIBITED)
        assert tool_outcome(refused) == DENIED_POLICY
        assert "synthesis.prohibited_imports" in refused, f"denied for the wrong reason: {refused}"
        assert not (tmp_path / "payload.pyx").exists()

        # The converse, which is what makes the first half evidence rather than
        # a coincidence. It needs `validate_syntax=False` because there are two
        # ways into the parse: the accessor (which always parses, and is what
        # this test is about) and `ext_to_lang`, a separate suffix map that
        # parses when the flag is on. With the flag on, `.py` is still caught
        # through the second path even when the accessor excludes it — which is
        # a defence in depth worth knowing about, but it would hide the
        # dependency being asserted here.
        written = execute_generate_code(tmp_path, "payload.py", self.PROHIBITED, validate_syntax=False)
        assert "Success: Generated" in written, written
        assert (tmp_path / "payload.py").read_text(encoding="utf-8") == self.PROHIBITED
