"""Whitelist for the `vulture` dead-code gate in `make lint-python`.

vulture reports a name as unused when no Python source references it. Names
that a framework resolves at runtime by string or decorator registration look
unused to it and are listed here so the gate can run at `--min-confidence 80`
without waivers in the source (tech-debt-hardening-plan R-TDH-17).

Each entry names the mechanism that consumes the symbol. An entry whose symbol
no longer exists is itself dead: keep this file short and re-verify it when a
framework-registered surface changes.

vulture parses this file as ordinary Python; the `_` sentinel is its documented
convention for "this attribute is used".
"""

# ruff: noqa: B018 - every line below is a deliberate attribute access, vulture's whitelist convention
from __future__ import annotations

from typing import Any

_: Any = object()

# FastAPI resolves route handlers through the `@app.post(...)` decorator.
_.orchestrate_task

# MCP resolves the handlers through `@server.list_tools()` / `@server.call_tool()`.
_.handle_list_tools
_.handle_call_tool

# pytest hooks in the repository-root conftest.py (delegating to
# harness/shared/tests/_session_hooks.py, DEC-030) are looked up by name.
_.pytest_collection_modifyitems
_.pytest_report_header
_.pytest_runtest_logreport
_.pytest_sessionfinish
