"""`read_file` must not become a second, ungoverned door onto credentials.

`command_actions.classify` grades `cat .env` as `secret_access` -- an action no
role in `agent-policy.json` holds -- so reading a credential through
`run_command` is denied for every agent. That grading is a property of the
*command*, and it protected the only file-reading door the agent had.

`read_file` resolves a path and reads it directly, so nothing in
`command_actions` sees it. Declared with `TOOL_REQUIRED_ACTION["read_file"] =
"read"` and no read policy, `read_file(".env")` would have returned
`NVIDIA_API_KEY` into `conversation_history` -- which is sent back to the model
API on the next turn, written to the debug dump, and held in memory for the rest
of the task. The tool would have been *permitted*, because `read` is exactly the
action the implementer holds.

This is a property test, not a regression-tier reproduction, and it lives here
rather than in `harness/shared/tests/regression/` because it does not meet that
tier's own bar: `harness/CONTRACT.md` defines the regression/AQA tier as one
reproduction per defect that has *already reached* `main`, each "confirmed
failing against the pre-fix commit." `read_file` does not exist on `main` --
the hazard below was caught during this feature's own design, before any commit
that would have shipped it, so there is no pre-fix commit to be confirmed
failing against. Filing it under `regression/` anyway would be the same kind of
quiet definition-drift this codebase's gates exist to catch elsewhere.

The property below is asserted over a corpus rather than a list of filenames.
A list drifts the moment someone adds a credential family to one door and not
the other; the property fails when they do.

Spec: ``docs/specs/agent-read-patch-tools.md`` (R-RPT-2, R-RPT-3).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.shared.agent_authority import tool_is_permitted
from harness.shared.governance.command_actions import classify
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator
from harness.shared.read_policy import read_denial_reason

pytestmark = pytest.mark.governance

#: Paths spanning every family either door models, plus near-misses that must
#: stay readable. The property is asserted over all of them; the near-misses are
#: what stops "deny everything" from passing.
CANDIDATE_PATHS = [
    ".env",
    ".env.local",
    ".env.production",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "id_rsa",
    "id_dsa",
    "server.pem",
    "config/secrets.pem",
    "keys/id_rsa",
    ".gitignore",
    ".gitleaks.toml",
    "README.md",
    "harness/shared/tool_schemas.py",
    "docs/specs/agent-containment.md",
    "Makefile",
]


@pytest.mark.parametrize("path", CANDIDATE_PATHS)
def test_the_read_door_is_no_wider_than_the_command_door(path: str) -> None:
    """Anything `cat <path>` is denied for, `read_file` is denied for too.

    One-directional on purpose: the read policy may be *stricter* (it denies
    `.git/**`, which `cat` does not), but it may never be looser.
    """
    if classify(f"cat {path}").action != "secret_access":
        return
    assert read_denial_reason(path) is not None, (
        f"`cat {path}` is denied as secret_access but read_file would have returned it"
    )


def test_the_corpus_actually_exercises_the_property() -> None:
    """A parity test over a corpus that triggers nothing passes vacuously."""
    denied = [p for p in CANDIDATE_PATHS if classify(f"cat {p}").action == "secret_access"]
    permitted = [p for p in CANDIDATE_PATHS if read_denial_reason(p) is None]
    assert len(denied) >= 8, f"corpus exercises only {len(denied)} secret_access paths"
    assert len(permitted) >= 5, f"corpus has only {len(permitted)} readable paths"


def test_read_file_is_permitted_but_still_refuses_the_credential(tmp_path: Path) -> None:
    """The regression in one assertion: the tool is *allowed* for this role, and
    the file is *present*, and the secret still does not come back."""
    (tmp_path / ".env").write_text("NVIDIA_API_KEY=sk-live-secret\n", encoding="utf-8")
    assert tool_is_permitted("nemotron-reasoner", "read_file") is True

    orch = MangoMASOrchestrator(workspace_dir=tmp_path, active_role="nemotron-reasoner")
    result = orch._tool_handlers["read_file"]({"filepath": ".env"})

    assert "sk-live-secret" not in result
    assert "credential-bearing" in result


def test_the_verifier_cannot_patch_the_work_it_judges(tmp_path: Path) -> None:
    """R-AC-8 for the new write-shaped tool: `apply_patch` reaches the same
    paths as `write_file`, so the role that judges the work must not hold it."""
    assert tool_is_permitted("verifier", "apply_patch") is False
    assert tool_is_permitted("verifier", "read_file") is True
