"""Regression tests that pin the NS-17 rollback state.

NS-17 (agent memory retention and workspace scoping) was reverted on this branch:

Removed from `harness/shared/meta_tools.py`:
- `resolve_memory_dir(workspace_dir)` -- workspace-scoped memory dir resolution
- `_fifo_trim(entries, max_entries)` -- FIFO retention enforcement
- `format_gaps_for_planner(workspace_dir, policy_path)` -- planner prompt injection
- `workspace_dir` / `policy_path` params from `knowledge_gap_log` / `hypothesis_register`

Removed from `harness/shared/governance-policy.json`:
- `agent_memory` block (`max_gaps`, `max_hypotheses`, `planner_gap_limit`)

Removed from `harness/shared/agent_prompts.py`:
- `{open_gaps}` slot from `PLANNER_PROMPT_TEMPLATE`

Removed from `harness/shared/orchestrator/dispatcher.py`:
- `policy_path` parameter from `ToolDispatcher.__init__`

Memory is now fixed-path (`MEMORY_DIR` from `__file__`), workspace-agnostic,
with no retention bound and no planner-prompt injection.

These tests act as a contract so that:
1. A reviewer sees what was simplified.
2. If NS-17 is re-implemented, the delta is explicit.
3. Accidental re-introduction of partial NS-17 surface fails loudly.

These tests do NOT require GNU Make or POSIX shell.
"""

from __future__ import annotations

import inspect
import json

import pytest

from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

GOVERNANCE_POLICY = REPO / "harness" / "shared" / "governance-policy.json"


class TestNS17MetaToolsAPIRolledBack:
    """NS-17 additions to meta_tools are absent."""

    def test_resolve_memory_dir_not_exported(self) -> None:
        """`resolve_memory_dir` was removed; callers must use `MEMORY_DIR` directly."""
        import harness.shared.meta_tools as mt

        assert not hasattr(mt, "resolve_memory_dir"), (
            "resolve_memory_dir is present in meta_tools -- NS-17 workspace-scoped "
            "memory dir resolution was rolled back. If re-implementing, add retention "
            "and planner injection tests before removing this guard."
        )

    def test_fifo_trim_not_exported(self) -> None:
        """`_fifo_trim` was removed; no retention enforcement exists."""
        import harness.shared.meta_tools as mt

        assert not hasattr(mt, "_fifo_trim"), (
            "_fifo_trim is present in meta_tools -- NS-17 FIFO retention was rolled back."
        )

    def test_format_gaps_for_planner_not_exported(self) -> None:
        """`format_gaps_for_planner` was removed; the planner prompt has no gap injection."""
        import harness.shared.meta_tools as mt

        assert not hasattr(mt, "format_gaps_for_planner"), (
            "format_gaps_for_planner is present -- NS-17 planner gap surfacing was rolled back."
        )

    def test_knowledge_gap_log_has_no_workspace_dir_param(self) -> None:
        """`knowledge_gap_log` no longer accepts `workspace_dir`."""
        import inspect as _inspect

        from harness.shared.meta_tools import knowledge_gap_log

        sig = _inspect.signature(knowledge_gap_log)
        assert "workspace_dir" not in sig.parameters, (
            "knowledge_gap_log still accepts workspace_dir -- NS-17 was rolled back."
        )

    def test_knowledge_gap_log_has_no_policy_path_param(self) -> None:
        import inspect as _inspect

        from harness.shared.meta_tools import knowledge_gap_log

        sig = _inspect.signature(knowledge_gap_log)
        assert "policy_path" not in sig.parameters, (
            "knowledge_gap_log still accepts policy_path -- NS-17 was rolled back."
        )


class TestNS17PlannerTemplateRolledBack:
    """`PLANNER_PROMPT_TEMPLATE` no longer contains the `{open_gaps}` slot."""

    def test_planner_template_has_no_open_gaps_slot(self) -> None:
        from harness.shared.agent_prompts import PLANNER_PROMPT_TEMPLATE

        assert "{open_gaps}" not in PLANNER_PROMPT_TEMPLATE, (
            "PLANNER_PROMPT_TEMPLATE still contains {open_gaps} -- NS-17 planner "
            "gap injection was rolled back. Update this test when re-implementing."
        )

    def test_planner_template_formats_with_task_only(self) -> None:
        """Template must accept exactly {task} -- no extra slots."""
        from harness.shared.agent_prompts import PLANNER_PROMPT_TEMPLATE

        rendered = PLANNER_PROMPT_TEMPLATE.format(task="verify portability fixes")
        assert "verify portability fixes" in rendered

    def test_planner_template_slots_contain_only_task(self) -> None:
        """Template must expose exactly one format slot: {task}.

        Python's str.format() silently ignores *extra* kwargs, so asserting
        it raises on ``open_gaps=...`` would be wrong. Instead, enumerate
        the slots via string.Formatter and assert the only field name is 'task'.
        """
        import string

        from harness.shared.agent_prompts import PLANNER_PROMPT_TEMPLATE

        field_names = {
            field_name
            for _, field_name, _, _ in string.Formatter().parse(PLANNER_PROMPT_TEMPLATE)
            if field_name is not None
        }
        assert "open_gaps" not in field_names, (
            "PLANNER_PROMPT_TEMPLATE contains an {open_gaps} slot -- NS-17 planner "
            "gap injection was rolled back. Remove this slot or update this test."
        )
        assert "task" in field_names, "PLANNER_PROMPT_TEMPLATE has no {task} slot -- the template is broken."


class TestNS17GovernancePolicyRolledBack:
    """`governance-policy.json` has no `agent_memory` block."""

    def test_policy_has_no_agent_memory_block(self) -> None:
        policy = json.loads(GOVERNANCE_POLICY.read_text(encoding="utf-8"))
        assert "agent_memory" not in policy, (
            "governance-policy.json contains an agent_memory block -- NS-17 retention "
            "policy was rolled back. If re-adding, also restore the FIFO trim tests."
        )


class TestNS17DispatcherRolledBack:
    """`ToolDispatcher.__init__` has no `policy_path` parameter."""

    def test_dispatcher_init_has_no_policy_path(self) -> None:
        from harness.shared.orchestrator.dispatcher import ToolDispatcher

        sig = inspect.signature(ToolDispatcher.__init__)
        assert "policy_path" not in sig.parameters, (
            "ToolDispatcher.__init__ still has policy_path -- NS-17 was rolled back."
        )

    def test_dispatcher_instance_has_no_policy_path_attr(self) -> None:
        """Verify at class-source level -- no self.policy_path assignment."""
        from harness.shared.orchestrator import dispatcher as disp_mod

        src = inspect.getsource(disp_mod.ToolDispatcher.__init__)
        assert "self.policy_path" not in src, (
            "ToolDispatcher.__init__ assigns self.policy_path -- NS-17 was rolled back."
        )
