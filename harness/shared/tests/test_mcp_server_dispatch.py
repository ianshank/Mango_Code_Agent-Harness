"""Tests for MCP server tool dispatch, role authorization, registry parity, and logging."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import harness.shared.mcp_server as mcp_mod
from harness.shared.agent_authority import execution_identity, tools_for_role
from harness.shared.governance.broker import ExecutionBroker
from harness.shared.mcp_server import create_mcp_server
from harness.shared.orchestrator.dispatcher import ToolDispatcher
from harness.shared.tests._mcp_helpers import make_mock_broker, setup_mock_mcp
from harness.shared.tool_schemas import NEMOTRON_TOOLS

# Windows portability note (DEC-062): loopback TCP fallback for asyncio
if sys.platform == "win32":
    pytestmark = pytest.mark.enable_socket


@pytest.fixture(autouse=True)
def ensure_mock_mcp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    setup_mock_mcp(monkeypatch, tmp_path)


@pytest.fixture
def broker() -> ExecutionBroker:
    return make_mock_broker()


def test_every_declared_tool_has_a_handler(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Declaration (NEMOTRON_TOOLS) and dispatch (_build_tool_handlers) must not
    drift -- mirrors mango_mas_orchestrator.py's identical registry-drift test
    for its own copy of this same six-tool dispatch table."""
    handlers = mcp_mod._build_tool_handlers(tmp_path, broker, "nemotron-reasoner")
    tools: list[dict[str, Any]] = NEMOTRON_TOOLS
    declared = {t["function"]["name"] for t in tools}
    registered = set(handlers)
    assert declared == registered, (
        f"declared-but-unhandled: {declared - registered}; handled-but-undeclared: {registered - declared}"
    )


def test_mcp_server_tools_sync_by_role(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-2: Tool descriptions match the schemas allowed for the active role."""
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    assert server._list_tools_handler is not None

    tools = asyncio.run(server._list_tools_handler())
    expected_schemas = tools_for_role("nemotron-reasoner", NEMOTRON_TOOLS)
    assert len(tools) == len(expected_schemas)

    tool_names = {t.name for t in tools}
    schema_names = {schema["function"]["name"] for schema in expected_schemas}
    assert tool_names == schema_names
    assert {tool.name: tool.input_schema for tool in tools} == {
        schema["function"]["name"]: schema["function"]["parameters"] for schema in expected_schemas
    }


def test_mcp_server_role_unauthorized_tool_denied(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-3: Calling a tool unauthorized for the role returns a permission denial message."""
    server = create_mcp_server(tmp_path, role="verifier", broker=broker)
    assert server._call_tool_handler is not None

    result = asyncio.run(server._call_tool_handler("write_file", {"filepath": "test.py", "content": "print(1)"}))
    assert len(result) == 1
    assert "not permitted for role 'verifier'" in result[0].text


@pytest.mark.parametrize(
    "tool_name, args, expected_snippet",
    [
        ("write_file", {"filepath": "sample.txt", "content": "hello"}, "Wrote"),
        ("read_file", {"filepath": "sample.txt"}, "hello"),
        ("apply_patch", {"filepath": "sample.txt", "old_text": "hello", "new_text": "world"}, "patched"),
        ("run_command", {"command": "echo test"}, "test stdout"),
        ("knowledge_gap_log", {"question": "q", "what_needed": "w", "proposed_approach": "p"}, "Knowledge gap logged"),
        ("hypothesis_register", {"claim": "c", "reasoning": "r", "confidence": 0.9}, "Hypothesis registered"),
        (
            "hypothesis_register",
            {"claim": "c", "reasoning": "r", "confidence": 0.9, "revises": "prior-id", "status": "retracted"},
            "Prior entry prior-id not found",
        ),
    ],
)
def test_mcp_server_execute_tool_success(
    tmp_path: Path, broker: ExecutionBroker, tool_name: str, args: dict[str, Any], expected_snippet: str
) -> None:
    """Test standard success paths for each tool."""
    if tool_name in ("read_file", "apply_patch"):
        (tmp_path / "sample.txt").write_text("hello", encoding="utf-8")

    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    handler = server._call_tool_handler
    assert handler is not None

    res = asyncio.run(handler(tool_name, args))
    assert expected_snippet in res[0].text


def test_mcp_server_execute_tool_broker_crash(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Test tools gracefully handle execution exceptions from the broker or executors."""
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    handler = server._call_tool_handler
    assert handler is not None

    with patch("harness.shared.orchestrator.dispatcher.execute_run_command", side_effect=RuntimeError("broker crash")):
        res = asyncio.run(handler("run_command", {"command": "broken"}))
        assert "Error executing tool" in res[0].text


def test_mcp_server_read_file_lines(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Test read_file properly applies start_line and end_line bounds."""
    target = tmp_path / "lines.txt"
    target.write_text("one\ntwo\nthree\nfour\nfive", encoding="utf-8")
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    handler = server._call_tool_handler
    assert handler is not None

    res = asyncio.run(handler("read_file", {"filepath": "lines.txt", "start_line": 2, "end_line": 4}))
    assert "two" in res[0].text
    assert "four" in res[0].text
    assert "one" not in res[0].text
    assert "five" not in res[0].text


def test_mcp_server_write_file_empty_path(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Test write_file handles empty filepath cleanly (falls back to executor error)."""
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    handler = server._call_tool_handler
    assert handler is not None

    res = asyncio.run(handler("write_file", {"filepath": "", "content": "test"}))
    assert "Error" in res[0].text or "denied" in res[0].text.lower() or "missing" in res[0].text.lower()


def test_mcp_server_apply_patch_not_found(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Test apply_patch properly handles when old_text is not found in file."""
    target = tmp_path / "notfound.txt"
    target.write_text("actual text", encoding="utf-8")
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    handler = server._call_tool_handler
    assert handler is not None

    res = asyncio.run(
        handler("apply_patch", {"filepath": "notfound.txt", "old_text": "missing text", "new_text": "replacement"})
    )
    assert "error patching file" in res[0].text.lower() and "matched 0 times" in res[0].text.lower()


def test_mcp_server_broker_pdp_blocks_write(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-3 (C-MCP-1): broker PDP denial for write_file is honoured before the write executes."""
    broker.authorize_action.return_value = (  # type: ignore[attr-defined]
        "action 'write' is not granted to implementer"
    )
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    result = asyncio.run(server._call_tool_handler("write_file", {"filepath": "x.py", "content": ""}))
    assert len(result) == 1
    assert "Denied" in result[0].text
    assert not (tmp_path / "x.py").exists()


def test_mcp_server_broker_pdp_blocks_apply_patch(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-3 (C-MCP-1): broker PDP denial applies to apply_patch too, not just write_file."""
    target = tmp_path / "x.py"
    target.write_text("hello", encoding="utf-8")
    broker.authorize_action.return_value = (  # type: ignore[attr-defined]
        "action 'write' is not granted to implementer"
    )
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    result = asyncio.run(
        server._call_tool_handler("apply_patch", {"filepath": "x.py", "old_text": "hello", "new_text": "world"})
    )
    assert len(result) == 1
    assert "Denied" in result[0].text
    assert target.read_text(encoding="utf-8") == "hello"


def test_mcp_server_unknown_tool_error_message_preserved(tmp_path: Path, broker: ExecutionBroker) -> None:
    """The registry refactor must not change the 'Unknown tool' wire message."""
    with patch("harness.shared.mcp_server.tool_is_permitted", return_value=True):
        server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
        result = asyncio.run(server._call_tool_handler("not_a_real_tool", {}))
    assert len(result) == 1
    assert result[0].text == "Error executing tool 'not_a_real_tool': Unknown tool: not_a_real_tool"


def test_mcp_server_policy_lookup_failure_denies(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Policy lookup errors inside the handler must return a structured denial, not raise."""
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    with patch("harness.shared.mcp_server.tool_is_permitted", side_effect=RuntimeError("policy read failure")):
        result = asyncio.run(server._call_tool_handler("write_file", {"filepath": "x.py", "content": ""}))
    assert len(result) == 1
    assert "denied" in result[0].text.lower()


# --- One registry, two transports (audit M8) ---------------------------------


def _assert_registry_parity(mcp_names: set[str], dispatcher_names: set[str]) -> None:
    assert mcp_names == dispatcher_names, (
        f"mcp-only: {mcp_names - dispatcher_names}; dispatcher-only: {dispatcher_names - mcp_names}"
    )


def test_mcp_handler_names_equal_dispatcher_handler_names(tmp_path: Path, broker: ExecutionBroker) -> None:
    """A tool added to (or dropped from) ToolDispatcher.tool_handlers appears
    in (or leaves) the MCP registry in the same commit -- the two are one table."""
    dispatcher = ToolDispatcher(workspace_dir=tmp_path, broker=broker)
    mcp_names = set(mcp_mod._build_tool_handlers(tmp_path, broker, "nemotron-reasoner"))
    _assert_registry_parity(mcp_names, set(dispatcher.tool_handlers))
    assert mcp_names == set(dispatcher.tool_handlers)
    assert mcp_names, "an empty registry would satisfy parity vacuously"


def test_registry_parity_check_fails_when_a_name_is_dropped(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Negative variant: removing one name from either side must make it raise."""
    dispatcher_names = set(ToolDispatcher(workspace_dir=tmp_path, broker=broker).tool_handlers)
    mcp_names = set(mcp_mod._build_tool_handlers(tmp_path, broker, "nemotron-reasoner"))
    dropped = mcp_names - {"run_command"}
    assert "run_command" in mcp_names, "precondition: the dropped name was registered"
    with pytest.raises(AssertionError, match="dispatcher-only: \\{'run_command'\\}"):
        _assert_registry_parity(dropped, dispatcher_names)


def test_mcp_registry_is_the_dispatcher_table_not_a_copy(
    tmp_path: Path, broker: ExecutionBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mcp_server derives its table from the dispatcher rather than mirroring it by hand."""

    class DispatcherWithoutRunCommand(ToolDispatcher):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            del self.tool_handlers["run_command"]

    monkeypatch.setattr(mcp_mod, "ToolDispatcher", DispatcherWithoutRunCommand)
    handlers = mcp_mod._build_tool_handlers(tmp_path, broker, "nemotron-reasoner")
    assert "run_command" not in handlers
    assert set(handlers) == set(ToolDispatcher(workspace_dir=tmp_path, broker=broker).tool_handlers) - {"run_command"}


def test_shared_registry_carries_the_acting_role(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Role scoping must survive the shared registry."""
    broker.authorize_action.return_value = "action 'write' is not granted to verifier"  # type: ignore[attr-defined]
    handlers = mcp_mod._build_tool_handlers(tmp_path, broker, "verifier")
    assert handlers["write_file"]({"filepath": "x.py", "content": ""}).startswith("Denied:")
    broker.authorize_action.assert_called_with(execution_identity("verifier"), "write")  # type: ignore[attr-defined]
    assert not (tmp_path / "x.py").exists()


# --- Structured per-call logging ----------------------------------------------


def _tool_call_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == mcp_mod.__name__ and r.getMessage().startswith("mcp_tool_call ")]


def test_permitted_call_logs_at_debug_with_keys_only(
    tmp_path: Path, broker: ExecutionBroker, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "hunter2-do-not-log"
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    with caplog.at_level(logging.DEBUG, logger=mcp_mod.__name__):
        asyncio.run(server._call_tool_handler("write_file", {"filepath": "note.txt", "content": secret}))

    records = _tool_call_records(caplog)
    assert len(records) == 1
    record = records[0]
    message = record.getMessage()
    assert record.levelno == logging.DEBUG
    assert "tool=write_file" in message
    assert "role=nemotron-reasoner" in message
    assert "permitted=True" in message
    assert "duration_ms=" in message
    assert "argument_keys=['content', 'filepath']" in message
    assert secret not in message, "argument values leaked into the log"
    assert secret not in caplog.text


def test_denied_call_logs_at_warning(tmp_path: Path, broker: ExecutionBroker, caplog: pytest.LogCaptureFixture) -> None:
    server = create_mcp_server(tmp_path, role="verifier", broker=broker)
    with caplog.at_level(logging.DEBUG, logger=mcp_mod.__name__):
        asyncio.run(server._call_tool_handler("write_file", {"filepath": "x.py", "content": "print(1)"}))

    records = _tool_call_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    message = records[0].getMessage()
    assert "tool=write_file" in message and "role=verifier" in message and "permitted=False" in message
    assert "print(1)" not in caplog.text


def test_policy_lookup_failure_logs_the_call_as_denied(
    tmp_path: Path, broker: ExecutionBroker, caplog: pytest.LogCaptureFixture
) -> None:
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    with (
        caplog.at_level(logging.DEBUG, logger=mcp_mod.__name__),
        patch("harness.shared.mcp_server.tool_is_permitted", side_effect=RuntimeError("policy read failure")),
    ):
        asyncio.run(server._call_tool_handler("write_file", None))

    records = _tool_call_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "permitted=False" in records[0].getMessage()
    assert "argument_keys=[]" in records[0].getMessage()


def test_unknown_argument_names_are_counted_not_logged(
    tmp_path: Path, broker: ExecutionBroker, caplog: pytest.LogCaptureFixture
) -> None:
    smuggled = "nvapi-secret-in-a-key-name"
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    with caplog.at_level(logging.DEBUG, logger=mcp_mod.__name__):
        asyncio.run(server._call_tool_handler("read_file", {"filepath": "a.txt", smuggled: "x"}))

    records = _tool_call_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert "argument_keys=['filepath']" in message
    assert "unknown_key_count=1" in message
    assert smuggled not in caplog.text, "an unknown key name reached the log"


def test_a_handler_denial_is_logged_as_denied(
    tmp_path: Path, broker: ExecutionBroker, caplog: pytest.LogCaptureFixture
) -> None:
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    with caplog.at_level(logging.DEBUG, logger=mcp_mod.__name__):
        result = asyncio.run(server._call_tool_handler("write_file", {"filepath": ".env", "content": "K=v"}))

    assert result[0].text.startswith("Error writing file .env"), result[0].text
    records = _tool_call_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    message = records[0].getMessage()
    assert "permitted=False" in message and "outcome=denied_policy" in message


def test_a_successful_read_of_a_file_that_begins_with_error_is_logged_as_permitted(
    tmp_path: Path, broker: ExecutionBroker, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "log.txt").write_text("Error: this is the file's own content\n", encoding="utf-8")
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    with caplog.at_level(logging.DEBUG, logger=mcp_mod.__name__):
        result = asyncio.run(server._call_tool_handler("read_file", {"filepath": "log.txt"}))

    assert result[0].text.startswith("Error: this is the file's own content")
    records = _tool_call_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.DEBUG
    message = records[0].getMessage()
    assert "permitted=True" in message and "outcome=executed" in message


def test_a_missing_file_is_logged_as_a_permitted_failure_not_a_denial(
    tmp_path: Path, broker: ExecutionBroker, caplog: pytest.LogCaptureFixture
) -> None:
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    with caplog.at_level(logging.DEBUG, logger=mcp_mod.__name__):
        asyncio.run(server._call_tool_handler("read_file", {"filepath": "absent.txt"}))
    (record,) = _tool_call_records(caplog)
    assert record.levelno == logging.DEBUG
    assert "permitted=True" in record.getMessage() and "outcome=failed" in record.getMessage()


def test_a_call_the_schema_rejects_never_starts_the_handler(tmp_path: Path, broker: ExecutionBroker) -> None:
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    result = asyncio.run(server._call_tool_handler("write_file", {"filepath": "hole.txt"}))
    assert result[0].text.startswith("Error: invalid_arguments:"), result[0].text
    assert "content" in result[0].text
    assert not (tmp_path / "hole.txt").exists(), "the executor ran on a call the schema rejects"

    extra = asyncio.run(server._call_tool_handler("read_file", {"filepath": "a.txt", "sneaky": 1}))
    assert extra[0].text.startswith("Error: invalid_arguments:"), extra[0].text


def test_a_schema_rejection_is_logged_as_denied(
    tmp_path: Path, broker: ExecutionBroker, caplog: pytest.LogCaptureFixture
) -> None:
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    with caplog.at_level(logging.DEBUG, logger=mcp_mod.__name__):
        asyncio.run(server._call_tool_handler("write_file", {"filepath": "hole.txt"}))
    records = _tool_call_records(caplog)
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    assert "permitted=False" in records[0].getMessage()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
