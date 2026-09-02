"""Regressions for orchestrator tool dispatch and debug-history redaction.

Defects reproduced here (all present on ``main`` before this change):

1. ``arguments: null`` reached ``json.loads(None)``, raising TypeError past an
   ``except json.JSONDecodeError`` that could not catch it.
2. ``arguments: "[]"`` parsed to a list, and every registry lambda then died
   on ``.get``.
3. A handler that raised aborted ``execute_agent`` mid-loop, so the model's
   ``tool_calls`` message was never answered and the post-run hook never fired.
4. Debug dumps were redacted only when ``self.api_key`` was set -- which is not
   the normal configuration, because the bridge resolves the credential
   downstream. ``MANGO_DEBUG_DUMP=1`` therefore wrote plaintext credentials to
   a predictably named file in the shared temp directory.
5. The dump directory was created with the default mode.

The wire contract under test throughout: **exactly one tool message per
requested tool call**. The API rejects the next turn otherwise, so a dispatch
path that can skip a message is a hang, not a cosmetic flaw.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from harness.shared import mango_mas_orchestrator as orch_module
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator
from harness.shared.tests._helpers import chat_response, tool_call
from harness.shared.tests.conftest import POSIX_ONLY


def _tool_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in messages if m.get("role") == "tool"]


class TestMalformedToolArguments:
    """Each shape must yield one tool message, never an exception."""

    @pytest.mark.parametrize(
        ("label", "raw"),
        [
            ("json null", None),
            ("json array", "[]"),
            ("json scalar", "42"),
            ("json string", '"hello"'),
            ("unparseable", "{not json"),
            ("empty string", ""),
            ("whitespace", "   "),
        ],
    )
    def test_malformed_arguments_produce_a_tool_result(self, label: str, raw: Any) -> None:
        normalized = orch_module._normalize_tool_arguments(raw, "write_file")
        assert normalized == {}, f"{label} should degrade to no arguments"

    def test_missing_arguments_key_is_tolerated(self) -> None:
        call = tool_call("run_command", omit_arguments=True)
        assert orch_module._normalize_tool_arguments(call["function"].get("arguments"), "run_command") == {}

    def test_well_formed_arguments_pass_through_unchanged(self) -> None:
        assert orch_module._normalize_tool_arguments('{"filepath": "a.txt"}', "write_file") == {"filepath": "a.txt"}

    def test_null_arguments_do_not_crash_the_agent_loop(self, agent_workspace: Path) -> None:
        """End-to-end: the defect surfaced as a TypeError escaping execute_agent."""
        calls = [chat_response(None, tool_calls=[tool_call("write_file", None)]), chat_response("done")]
        with patch.object(orch_module, "complete_chat", side_effect=calls):
            orch = MangoMASOrchestrator(workspace_dir=agent_workspace)
            result = orch.execute_agent("nemotron-reasoner", "go")
        assert result == "done"

    def test_array_arguments_do_not_crash_the_agent_loop(self, agent_workspace: Path) -> None:
        calls = [chat_response(None, tool_calls=[tool_call("write_file", "[]")]), chat_response("done")]
        with patch.object(orch_module, "complete_chat", side_effect=calls):
            orch = MangoMASOrchestrator(workspace_dir=agent_workspace)
            result = orch.execute_agent("nemotron-reasoner", "go")
        assert result == "done"


class TestHandlerFailureContract:
    def test_a_raising_handler_still_answers_the_tool_call(self, agent_workspace: Path) -> None:
        """A meta-tool lock timeout used to escape the whole agent loop."""
        messages: list[dict[str, Any]] = []
        orch = MangoMASOrchestrator(workspace_dir=agent_workspace)

        def boom(_args: dict[str, Any]) -> str:
            raise TimeoutError("could not acquire the register lock")

        orch.dispatcher.tool_handlers["knowledge_gap_log"] = boom
        orch.dispatcher.dispatch(messages, [tool_call("knowledge_gap_log", {"question": "q"})])

        results = _tool_messages(messages)
        assert len(results) == 1, "the wire protocol requires one tool message per tool call"
        assert "could not acquire the register lock" in results[0]["content"]
        assert results[0]["tool_call_id"] == "call_1"

    def test_every_call_is_answered_even_when_some_fail(self, agent_workspace: Path) -> None:
        messages: list[dict[str, Any]] = []
        orch = MangoMASOrchestrator(workspace_dir=agent_workspace)
        orch.dispatcher.tool_handlers["knowledge_gap_log"] = lambda _a: (_ for _ in ()).throw(RuntimeError("nope"))

        calls = [
            tool_call("knowledge_gap_log", {"question": "q"}, call_id="c1"),
            tool_call("does_not_exist", {}, call_id="c2"),
            tool_call("write_file", {"filepath": "ok.txt", "content": "x"}, call_id="c3"),
        ]
        orch.dispatcher.dispatch(messages, calls)

        results = _tool_messages(messages)
        assert [m["tool_call_id"] for m in results] == ["c1", "c2", "c3"]
        assert all(isinstance(m["content"], str) for m in results)

    def test_unknown_tool_is_reported_not_raised(self, agent_workspace: Path) -> None:
        messages: list[dict[str, Any]] = []
        orch = MangoMASOrchestrator(workspace_dir=agent_workspace)
        orch.dispatcher.dispatch(messages, [tool_call("no_such_tool", {})])
        assert "Unknown tool" in _tool_messages(messages)[0]["content"]


class TestDebugDumpRedaction:
    """The dump path is opt-in, but when it is on it must not leak."""

    def test_redacts_when_the_orchestrator_holds_no_key(
        self, agent_workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The defect in one line: ``api_key=None`` is the normal case, and it
        was the case in which redaction was skipped entirely."""
        secret = "nvapi-live-credential-value-1234"
        monkeypatch.setenv("NVIDIA_API_KEY", secret)
        monkeypatch.setenv("MANGO_DEBUG_DUMP", "1")
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

        with patch.object(orch_module, "complete_chat", return_value=chat_response(f"leaked {secret}")):
            orch = MangoMASOrchestrator(workspace_dir=agent_workspace)  # note: no api_key=
            assert orch.api_key is None
            orch.execute_agent("nemotron-reasoner", "go")

        dumps = list((tmp_path / "mango_debug").glob("debug_nemotron-reasoner_*.json"))
        assert dumps, "expected a debug dump"
        written = dumps[0].read_text(encoding="utf-8")
        assert secret not in written
        assert "<REDACTED_API_KEY>" in written

    def test_redacts_a_provider_shaped_token_from_no_known_source(
        self, agent_workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_ambient_credentials: None
    ) -> None:
        """A key echoed back by a tool never equals any value we hold, so
        value-equality redaction could not have caught it."""
        monkeypatch.setenv("MANGO_DEBUG_DUMP", "1")
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        stray = "nvapi-echoed-back-by-a-tool-9999"

        with patch.object(orch_module, "complete_chat", return_value=chat_response(f"tool said {stray}")):
            MangoMASOrchestrator(workspace_dir=agent_workspace).execute_agent("nemotron-reasoner", "go")

        written = next((tmp_path / "mango_debug").glob("*.json")).read_text(encoding="utf-8")
        assert stray not in written

    @POSIX_ONLY
    def test_dump_directory_is_owner_only(
        self, agent_workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dumps contain prompts and tool output; the default mode left them
        readable by every user on a shared runner."""
        monkeypatch.setenv("MANGO_DEBUG_DUMP", "1")
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        with patch.object(orch_module, "complete_chat", return_value=chat_response("ok")):
            MangoMASOrchestrator(workspace_dir=agent_workspace).execute_agent("nemotron-reasoner", "go")
        assert (tmp_path / "mango_debug").stat().st_mode & 0o777 == 0o700

    def test_dump_is_written_as_utf8(
        self, agent_workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without an explicit encoding the dump used the platform default and
        raised UnicodeEncodeError on non-UTF-8 locales."""
        monkeypatch.setenv("MANGO_DEBUG_DUMP", "1")
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        with patch.object(orch_module, "complete_chat", return_value=chat_response("naïve — 日本語")):
            MangoMASOrchestrator(workspace_dir=agent_workspace).execute_agent("nemotron-reasoner", "go")
        written = next((tmp_path / "mango_debug").glob("*.json")).read_text(encoding="utf-8")
        assert "日本語" in json.dumps(json.loads(written), ensure_ascii=False)

    def test_no_dump_without_the_flag(
        self, agent_workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MANGO_DEBUG_DUMP", raising=False)
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        with patch.object(orch_module, "complete_chat", return_value=chat_response("ok")):
            MangoMASOrchestrator(workspace_dir=agent_workspace).execute_agent("nemotron-reasoner", "go")
        assert not (tmp_path / "mango_debug").exists()
