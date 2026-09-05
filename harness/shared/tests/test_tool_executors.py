"""Tests for harness/shared/tool_executors.py -- the direct read and patch tools.

Spec: ``docs/specs/agent-read-patch-tools.md`` (R-RPT-1, R-RPT-4, R-RPT-5, R-RPT-7).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.shared.governance.process_backend import DEFAULT_MAX_OUTPUT_BYTES
from harness.shared.tests.conftest import POSIX_ONLY
from harness.shared.tool_executors import (
    execute_apply_patch,
    execute_read_file,
    execute_write_file,
)


class TestReadFile:
    def test_reads_the_whole_file_verbatim(self, mock_workspace: Path) -> None:
        """No header on a full read: the result has to be pasteable into
        apply_patch's old_text without editing (R-RPT-1)."""
        (mock_workspace / "sample.py").write_bytes(b"alpha\nbeta\n")
        assert execute_read_file(mock_workspace, "sample.py") == "alpha\nbeta\n"

    def test_reads_a_line_range(self, mock_workspace: Path) -> None:
        (mock_workspace / "sample.py").write_bytes(b"a\nb\nc\nd\n")
        result = execute_read_file(mock_workspace, "sample.py", 2, 3)
        assert result.splitlines()[0] == "# sample.py lines 2-3 of 4"
        assert result.endswith("b\nc\n")

    def test_an_open_ended_range_runs_to_the_end(self, mock_workspace: Path) -> None:
        (mock_workspace / "sample.py").write_bytes(b"a\nb\nc\n")
        assert execute_read_file(mock_workspace, "sample.py", 2).endswith("b\nc\n")

    def test_a_sliced_read_keeps_crlf(self, mock_workspace: Path) -> None:
        (mock_workspace / "crlf.txt").write_bytes(b"a\r\nb\r\nc\r\n")
        assert "b\r\n" in execute_read_file(mock_workspace, "crlf.txt", 2, 2)

    def test_a_range_past_eof_reports_the_line_actually_returned(self, mock_workspace: Path) -> None:
        """Flagged in review: the slice already clamps `end_line` to the file's
        length, but the header used to echo the raw, un-clamped request --
        `# f lines 100-200 of 3` for a 3-line file, describing a range that was
        never returned. The header must report what the slice actually did."""
        (mock_workspace / "small.txt").write_bytes(b"a\nb\nc\n")
        result = execute_read_file(mock_workspace, "small.txt", 100, 200)
        assert result.splitlines()[0] == "# small.txt lines 100-3 of 3"

    def test_a_ranged_read_that_overflows_the_cap_is_still_bounded(self, mock_workspace: Path) -> None:
        """Flagged in review: the cap applied to `content` alone, then prepended
        the header, so `header + capped_content` could exceed
        DEFAULT_MAX_OUTPUT_BYTES by the header's own length. The header must be
        inside the capped budget, not added on top of it."""
        big_line = "y" * (DEFAULT_MAX_OUTPUT_BYTES + 100)
        (mock_workspace / "ranged.txt").write_bytes(f"{big_line}\nz\n".encode())
        result = execute_read_file(mock_workspace, "ranged.txt", 1, 2)
        # `_cap` itself appends a `[truncated at N bytes]` marker on top of the
        # limit -- the same accepted overhead `run_command` output already
        # carries everywhere else in this codebase -- so the bound is that
        # overhead, not a hard zero-overhead ceiling.
        marker_overhead = len(f"\n[truncated at {DEFAULT_MAX_OUTPUT_BYTES} bytes]".encode())
        assert len(result.encode("utf-8")) <= DEFAULT_MAX_OUTPUT_BYTES + marker_overhead
        assert result.startswith("# ranged.txt lines 1-2 of 2")

    @pytest.mark.parametrize(
        ("start", "end", "expected"),
        [
            (0, None, "start_line must be 1 or greater"),
            (-3, None, "start_line must be 1 or greater"),
            (None, 0, "end_line must be 1 or greater"),
            ("2", None, "start_line must be an integer"),
            (5, 2, "end_line (2) is before start_line (5)"),
        ],
    )
    def test_bad_bounds_are_refused(self, mock_workspace: Path, start: object, end: object, expected: str) -> None:
        """A negative index would silently return a different slice than asked
        for, with no error for the model to react to."""
        (mock_workspace / "sample.py").write_text("a\nb\n", encoding="utf-8")
        assert expected in execute_read_file(mock_workspace, "sample.py", start, end)  # type: ignore[arg-type]

    def test_a_bool_is_not_an_integer(self, mock_workspace: Path) -> None:
        """`isinstance(True, int)` is True, so bools need naming explicitly."""
        (mock_workspace / "sample.py").write_text("a\n", encoding="utf-8")
        assert "must be an integer" in execute_read_file(mock_workspace, "sample.py", True)  # type: ignore[arg-type]

    def test_output_is_capped_and_marked(self, mock_workspace: Path) -> None:
        (mock_workspace / "big.txt").write_text("x" * (DEFAULT_MAX_OUTPUT_BYTES + 5000), encoding="utf-8")
        result = execute_read_file(mock_workspace, "big.txt")
        assert f"[truncated at {DEFAULT_MAX_OUTPUT_BYTES} bytes]" in result
        assert result.startswith("# big.txt truncated\n")

    def test_path_escaping_the_workspace_is_refused(self, mock_workspace: Path) -> None:
        assert "path escapes workspace" in execute_read_file(mock_workspace, "../../etc/passwd")

    def test_a_credential_file_is_refused(self, mock_workspace: Path) -> None:
        """The regression this whole change exists to prevent: `run_command`
        denies `cat .env`, so the direct door must deny it too."""
        (mock_workspace / ".env").write_text("NVIDIA_API_KEY=sk-secret\n", encoding="utf-8")
        result = execute_read_file(mock_workspace, ".env")
        assert "credential-bearing" in result
        assert "sk-secret" not in result

    def test_a_git_internal_is_refused(self, mock_workspace: Path) -> None:
        assert ".git directory" in execute_read_file(mock_workspace, ".git/config")

    def test_a_missing_file_reports_the_error(self, mock_workspace: Path) -> None:
        assert execute_read_file(mock_workspace, "nope.txt").startswith("Error reading file")

    def test_a_directory_reports_the_error(self, mock_workspace: Path) -> None:
        (mock_workspace / "adir").mkdir()
        assert execute_read_file(mock_workspace, "adir").startswith("Error reading file")

    @POSIX_ONLY
    def test_a_symlink_pointing_outside_the_workspace_is_refused(self, mock_workspace: Path) -> None:
        """`.resolve()` follows the link before the containment check, so the
        escape is caught by its destination rather than its (innocent-looking)
        name inside the workspace."""
        outside = mock_workspace.parent / "outside_secret.txt"
        outside.write_text("NVIDIA_API_KEY=nvapi-outside\n", encoding="utf-8")
        (mock_workspace / "innocent.txt").symlink_to(outside)
        result = execute_read_file(mock_workspace, "innocent.txt")
        assert "path escapes workspace" in result
        assert "nvapi-outside" not in result

    def test_a_non_utf8_file_reports_the_error_without_crashing(self, mock_workspace: Path) -> None:
        (mock_workspace / "bin.dat").write_bytes(bytes([0xFF, 0xFE, 0x00, 0x01]))
        result = execute_read_file(mock_workspace, "bin.dat")
        assert result.startswith("Error reading file")


class TestApplyPatch:
    def test_replaces_a_unique_substring(self, mock_workspace: Path) -> None:
        target = mock_workspace / "sample.py"
        target.write_text("def alpha():\n    return 1\n", encoding="utf-8")
        assert execute_apply_patch(mock_workspace, "sample.py", "return 1", "return 2").startswith("Success")
        assert target.read_text(encoding="utf-8") == "def alpha():\n    return 2\n"

    def test_crlf_line_endings_survive_a_patch(self, mock_workspace: Path) -> None:
        """`Path.read_text`/`write_text` would rewrite every line ending in the
        file, turning a one-word edit into a whole-file diff (R-RPT-7)."""
        target = mock_workspace / "crlf.txt"
        target.write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")
        assert execute_apply_patch(mock_workspace, "crlf.txt", "beta", "BETA").startswith("Success")
        assert target.read_bytes() == b"alpha\r\nBETA\r\ngamma\r\n"

    def test_a_missing_trailing_newline_is_not_added(self, mock_workspace: Path) -> None:
        target = mock_workspace / "nonl.txt"
        target.write_bytes(b"alpha\nbeta")
        execute_apply_patch(mock_workspace, "nonl.txt", "beta", "BETA")
        assert target.read_bytes() == b"alpha\nBETA"

    def test_zero_matches_is_refused_with_the_count(self, mock_workspace: Path) -> None:
        (mock_workspace / "sample.py").write_text("alpha\n", encoding="utf-8")
        result = execute_apply_patch(mock_workspace, "sample.py", "absent", "x")
        assert "matched 0 times" in result
        assert "Widen old_text" in result

    def test_multiple_matches_are_refused_unchanged(self, mock_workspace: Path) -> None:
        """Patching an ambiguous match would edit an arbitrary one of them."""
        target = mock_workspace / "sample.py"
        target.write_text("x = 1\nx = 1\n", encoding="utf-8")
        assert "matched 2 times" in execute_apply_patch(mock_workspace, "sample.py", "x = 1", "x = 2")
        assert target.read_text(encoding="utf-8") == "x = 1\nx = 1\n"

    def test_empty_old_text_is_refused(self, mock_workspace: Path) -> None:
        """An empty needle counts once per position, so the uniqueness rule
        refuses it without needing a special case."""
        (mock_workspace / "sample.py").write_text("abc", encoding="utf-8")
        assert "expected exactly 1" in execute_apply_patch(mock_workspace, "sample.py", "", "x")

    def test_path_escaping_the_workspace_is_refused(self, mock_workspace: Path) -> None:
        assert "path escapes workspace" in execute_apply_patch(mock_workspace, "../../etc/passwd", "root", "pwned")

    def test_a_protected_path_is_refused(self, mock_workspace: Path) -> None:
        """Same write policy as write_file, because it reaches the same paths."""
        hooks = mock_workspace / ".mango" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-nemotron-run.sh").write_text("echo safe\n", encoding="utf-8")
        result = execute_apply_patch(mock_workspace, ".mango/hooks/pre-nemotron-run.sh", "safe", "pwned")
        assert "protected path" in result

    def test_a_git_path_is_refused(self, mock_workspace: Path) -> None:
        git_dir = mock_workspace / ".git"
        git_dir.mkdir(exist_ok=True)
        (git_dir / "config").write_text("[core]\n", encoding="utf-8")
        assert ".git directory" in execute_apply_patch(mock_workspace, ".git/config", "core", "x")

    def test_a_directory_target_reports_the_error_without_crashing(self, mock_workspace: Path) -> None:
        (mock_workspace / "adir").mkdir()
        assert execute_apply_patch(mock_workspace, "adir", "x", "y").startswith("Error patching file")

    def test_a_non_utf8_file_reports_the_error_without_crashing(self, mock_workspace: Path) -> None:
        (mock_workspace / "bin.dat").write_bytes(bytes([0xFF, 0xFE, 0x00, 0x01]))
        assert execute_apply_patch(mock_workspace, "bin.dat", "x", "y").startswith("Error patching file")

    def test_a_missing_file_reports_the_error(self, mock_workspace: Path) -> None:
        assert execute_apply_patch(mock_workspace, "nope.txt", "a", "b").startswith("Error patching file")

    def test_a_failing_write_reports_the_error(self, mock_workspace: Path, mocker) -> None:
        """The read succeeds and the write fails -- the branch a read-only
        checkout or a full disk takes. Driven by mocking rather than `chmod`,
        because the CI user may be root and root ignores the mode bits."""
        (mock_workspace / "ro.txt").write_text("alpha\n", encoding="utf-8")
        real_open = open

        def fail_on_write(file, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
            if "w" in mode:
                raise OSError("read-only file system")
            return real_open(file, mode, *args, **kwargs)

        mocker.patch("builtins.open", side_effect=fail_on_write)
        result = execute_apply_patch(mock_workspace, "ro.txt", "alpha", "beta")
        assert result.startswith("Error patching file")
        assert "read-only file system" in result


class TestWriteFileIsUnchanged:
    """The confinement preamble moved into a helper; behaviour did not."""

    def test_success(self, mock_workspace: Path) -> None:
        assert execute_write_file(mock_workspace, "out/sub.txt", "hello").startswith("Success:")
        assert (mock_workspace / "out" / "sub.txt").read_text(encoding="utf-8") == "hello"

    def test_path_escapes_workspace(self, mock_workspace: Path) -> None:
        assert "path escapes workspace" in execute_write_file(mock_workspace, "../../etc/passwd", "pwned")


class TestApplyPatchConsultsTheReadPolicy:
    """A patch reads before it writes (code-quality-tech-debt-plan R-CQ-4).

    `execute_apply_patch` reported `matched 0 times` or `matched 1 times`, which
    answers a question about the file's contents. Over a file the read policy
    refuses, that is a substring oracle: an attacker recovers `.env` a character
    at a time without ever calling `read_file`.

    Every assertion here names the *read* policy's wording. The write policy now
    refuses `.env` too, so an assertion on `"credential-bearing"` alone -- a
    phrase both policies use -- passes with the read gate deleted, which is the
    only gate this class exists to pin. `reading it is` appears in
    `read_denial_reason` and nowhere else.
    """

    #: The read policy's own sentence fragment, absent from `write_denial_reason`
    #: (which says `writing it is`). Asserting on it is what makes these tests
    #: fail when the read gate is removed rather than passing on the write gate.
    READ_GATE_PHRASE = "reading it is the secret_access action"

    def test_patching_a_credential_file_is_refused(self, mock_workspace: Path) -> None:
        (mock_workspace / ".env").write_text("NVIDIA_API_KEY=nvapi-secret\n", encoding="utf-8")
        result = execute_apply_patch(mock_workspace, ".env", "nvapi-s", "x")
        assert self.READ_GATE_PHRASE in result, f"the write gate answered instead: {result}"
        assert "matched" not in result

    def test_the_read_gate_answers_before_the_write_gate(self, mock_workspace: Path) -> None:
        """Order is the property, not just refusal.

        Both policies refuse `.env`, so a refusal proves only that one of them
        ran. The read gate has to be the one that answers: it is the gate that
        exists for `apply_patch`'s `matched N times` oracle, and a future
        relaxation of the write policy (a credential file the agent may
        *rewrite* but not read) must not silently take the read gate with it.
        """
        (mock_workspace / ".env").write_text("k=v\n", encoding="utf-8")
        result = execute_apply_patch(mock_workspace, ".env", "k=v", "k=w")
        assert self.READ_GATE_PHRASE in result
        assert "writing it is" not in result

    def test_the_oracle_answers_identically_for_present_and_absent_text(self, mock_workspace: Path) -> None:
        """The refusal must not depend on the file's contents, or the denial
        itself becomes the oracle it replaced."""
        (mock_workspace / ".env").write_text("NVIDIA_API_KEY=nvapi-secret\n", encoding="utf-8")
        present = execute_apply_patch(mock_workspace, ".env", "nvapi-s", "x")
        absent = execute_apply_patch(mock_workspace, ".env", "nvapi-ZZZZ", "x")
        assert present == absent
        assert self.READ_GATE_PHRASE in present

    def test_the_credential_file_is_not_modified(self, mock_workspace: Path) -> None:
        target = mock_workspace / ".env"
        original = "NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1\n"
        target.write_text(original, encoding="utf-8")
        execute_apply_patch(mock_workspace, ".env", "https://integrate.api.nvidia.com/v1", "http://evil")
        assert target.read_text(encoding="utf-8") == original

    def test_a_git_directory_file_is_refused_by_the_read_gate(self, mock_workspace: Path) -> None:
        (mock_workspace / ".git").mkdir(exist_ok=True)
        (mock_workspace / ".git" / "config").write_text("[remote]\n", encoding="utf-8")
        assert "no agent read may target" in execute_apply_patch(mock_workspace, ".git/config", "[remote]", "[x]")

    def test_an_ordinary_file_still_patches(self, mock_workspace: Path) -> None:
        """Control: the added gate must not close the tool it guards."""
        (mock_workspace / "notes.md").write_text("hello world\n", encoding="utf-8")
        assert "Success" in execute_apply_patch(mock_workspace, "notes.md", "world", "there")
        assert (mock_workspace / "notes.md").read_text(encoding="utf-8") == "hello there\n"


class TestOneWriteAuthorizationPath:
    """Both transports ask the same question before writing (R-CQ-5).

    `mcp_server` asked the policy decision point whether the acting role may
    write; `ToolDispatcher` -- the path the orchestrator actually runs -- asked
    nothing and went straight to the executor. `execute_write_file` enforces the
    write *policy* (protected paths, credential names, containment) but knows
    nothing about roles, so the verifier, which holds no `write` action, was
    refused by one door and admitted by the other.
    """

    def test_the_two_transports_share_one_function(self) -> None:
        from harness.shared import mcp_server
        from harness.shared.orchestrator import dispatcher
        from harness.shared.tool_executors import authorize_write

        assert mcp_server._broker_authorize_write is authorize_write
        assert dispatcher.authorize_write is authorize_write

    @pytest.mark.parametrize("role", ["verifier", "planner"])
    def test_a_role_without_the_write_action_is_refused_by_the_dispatcher(
        self, mock_workspace: Path, role: str
    ) -> None:
        from harness.shared.governance.broker import ExecutionBroker
        from harness.shared.orchestrator.dispatcher import ToolDispatcher

        d = ToolDispatcher(workspace_dir=mock_workspace, broker=ExecutionBroker())
        d.set_active_role(role)

        assert d._execute_write_file("notes.md", "x").startswith("Denied:")
        assert d._execute_apply_patch("notes.md", "x", "y").startswith("Denied:")
        assert not (mock_workspace / "notes.md").exists(), "the write happened despite the denial"

    def test_the_implementing_role_still_writes(self, mock_workspace: Path) -> None:
        """Control: an authority check that refuses everyone is an outage."""
        from harness.shared.governance.broker import ExecutionBroker
        from harness.shared.orchestrator.dispatcher import ToolDispatcher

        d = ToolDispatcher(workspace_dir=mock_workspace, broker=ExecutionBroker())
        d.set_active_role("nemotron-reasoner")

        assert "Success" in d._execute_write_file("notes.md", "hello")
        assert (mock_workspace / "notes.md").read_text(encoding="utf-8") == "hello"
        assert "Success" in d._execute_apply_patch("notes.md", "hello", "goodbye")

    #: What the authority model says about `write`, per role, asserted rather
    #: than derived. Symmetry alone (`mcp_denied == loop_denied`) is satisfied by
    #: deleting the gate from *both* transports, which is the regression this
    #: class exists to catch; pinning the expected verdict makes a removal on
    #: either side a failure. Sourced from `agent-policy.json`: only the
    #: implementing role holds `write`.
    EXPECTED_WRITE_DENIAL = {
        "nemotron-reasoner": False,
        "planner": True,
        "verifier": True,
    }

    def test_both_doors_agree_for_every_role(self, mock_workspace: Path) -> None:
        """The property the split lost: one action model, two transports, one answer."""
        from harness.shared.governance.broker import ExecutionBroker
        from harness.shared.mcp_server import _build_tool_handlers
        from harness.shared.orchestrator.dispatcher import ToolDispatcher

        for role, expected_denied in self.EXPECTED_WRITE_DENIAL.items():
            broker = ExecutionBroker()
            handlers = _build_tool_handlers(mock_workspace, broker, role)
            mcp_denied = handlers["write_file"]({"filepath": "probe.md", "content": "x"}).startswith("Denied:")

            d = ToolDispatcher(workspace_dir=mock_workspace, broker=ExecutionBroker())
            d.set_active_role(role)
            loop_denied = d._execute_write_file("probe.md", "x").startswith("Denied:")

            assert mcp_denied == loop_denied, f"the two transports disagree about whether {role} may write"
            assert mcp_denied is expected_denied, (
                f"both transports agree about {role}, but on the wrong answer: "
                f"denied={mcp_denied}, expected denied={expected_denied}"
            )

    def test_the_expected_verdicts_are_the_authority_model_s(self) -> None:
        """`EXPECTED_WRITE_DENIAL` is a second copy of `agent-policy.json` unless
        something holds it to the first. A role gaining or losing `write` there
        must fail here rather than silently re-baselining the table above."""
        from harness.shared.governance.broker import ExecutionBroker
        from harness.shared.tool_executors import WRITE_ACTION, execution_identity

        broker = ExecutionBroker()
        for role, expected_denied in self.EXPECTED_WRITE_DENIAL.items():
            reason = broker.authorize_action(execution_identity(role), WRITE_ACTION)
            assert (reason is not None) is expected_denied, (
                f"the authority model and this table disagree about {role}: reason={reason!r}"
            )
