"""Fixtures shared by the ``agents_doc`` suites.

Extracted when `test_agents_doc.py` reached ``limits.test_size_budget_lines``
and the policy half had to move out. The split mirrors the source seam --
`agents_doc_policy` resolves thresholds, `agents_doc` judges documents -- and
these builders are the one thing both halves need. A second copy of
`policy_block` in each file is precisely the shim-versus-copy drift
`check_dedup` exists to refuse, one directory over.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.shared.agents_doc import document_findings, parse_document
from harness.shared.agents_doc_policy import POLICY_BLOCK, AgentsDocConfig

CONFIG = AgentsDocConfig()

#: The keys a declared block owes. Derived from the dataclass rather than typed
#: out, so a threshold added to the module cannot leave this helper behind: the
#: new key would be missing from every synthetic policy and the whole suite
#: would fail closed, which is the direction a drifting fixture should fail in.
NUMERIC_KEYS = tuple(
    name for name, value in vars(AgentsDocConfig()).items() if isinstance(value, int) and not isinstance(value, bool)
)


def policy_block(**overrides: object) -> dict[str, object]:
    """A complete `agents_doc` block at its defaults, with `overrides` applied.

    Complete on purpose. A declared block owes every numeric key it reads, so a
    partial one is not a lighter fixture -- it is a different test.
    """
    block: dict[str, object] = {key: getattr(AgentsDocConfig(), key) for key in NUMERIC_KEYS}
    block.update(overrides)
    return block


def write_policy(tmp_path: Path, block: object) -> Path:
    """A policy file carrying only the block under test."""
    path = tmp_path / "governance-policy.json"
    payload: dict[str, object] = {} if block is None else {POLICY_BLOCK: block}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_document(
    directory: Path,
    *,
    scope: str = "`a.py`, `b.py`, `c.py`",
    reviewed: str | None = "2026-09-19",
    key_files: tuple[str, ...] = ("a.py",),
    diagram: str | None = 'flowchart LR\n  A["one"] --> B["two"]\n',
    extra_lines: int = 0,
    companion: str | None = "@AGENTS.md",
) -> Path:
    """A document that passes every rule, minus whatever the caller breaks."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("a.py", "b.py", "c.py"):
        (directory / name).write_text("x = 1\n", encoding="utf-8")
    body = [f"# AGENTS.md — {directory.name}", "", f"**Scope:** {scope}"]
    if reviewed is not None:
        body.append(f"**Reviewed:** {reviewed}")
    body += ["", "## What this does", "It exists so a test has something true to read.", ""]
    if diagram is not None:
        body += ["## Map", "", "```mermaid", diagram.rstrip("\n"), "```", ""]
    body += ["## Key files", "", "| File | Role |", "| --- | --- |"]
    body += [f"| `{name}` | a module |" for name in key_files]
    body += [""] + [f"<!-- filler {n} -->" for n in range(extra_lines)]
    path = directory / "AGENTS.md"
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    if companion is not None:
        (directory / "CLAUDE.md").write_text(companion + "\n", encoding="utf-8")
    return path


def findings_for(directory: Path, config: AgentsDocConfig = CONFIG) -> list[str]:
    return document_findings(parse_document(directory / "AGENTS.md", directory), directory.name, config)
