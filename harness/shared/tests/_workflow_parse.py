"""Parse GitHub workflow YAML text without depending on PyYAML.

Helpers lived in ``test_workflow_contracts.py`` until that module sat eight
lines under ``limits.test_size_budget_lines``. They are not tests; keeping
them beside the pin / attestation / ruleset suites would grow three copies
of the same parser. Callers that imported ``job_sections`` from the original
module still can: that file re-exports every public name here.
"""

from __future__ import annotations

import re

#: Lowest major of each action whose runtime is Node 24, verified against each
#: action's `action.yml` (`runs.using: node24`) on 2026-09-02. A `uses:` below
#: these majors runs on the Node 20 runtime GitHub deprecated on its runners.
NODE24_ACTION_MAJORS: dict[str, int] = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/setup-node": 5,
    "actions/setup-go": 6,
    "pnpm/action-setup": 5,
    # Not in use yet; R-CQ-23's build caching is the reference that will need it.
    "actions/cache": 4,
}

#: The only `uses:` form this repository accepts (R-CQ-9): a full 40-hex commit
#: SHA followed by the version comment Dependabot writes. A tag is a moving
#: reference — `@v5` is whatever the owner last pointed `v5` at, so an account
#: compromise upstream reaches this repository's runners without a commit here.
#: The comment is not decoration: a bare SHA says nothing about what it is, and
#: `NODE24_ACTION_MAJORS` is enforced against the major *it* states.
PINNED_USES = re.compile(
    r"^\s*(?:-\s*)?uses:\s*"
    r"(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    r"@(?P<sha>[0-9a-f]{40})"
    r"\s+#\s*v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)\s*$",
    re.M,
)
#: Any `uses:` at all, so a reference the strict form rejects is reported rather
#: than skipped. A `./`-relative composite action lives in this repository and
#: has no SHA to pin, so it is not a finding.
ANY_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<reference>\S.*?)\s*$")


def job_sections(workflow_text: str) -> dict[str, str]:
    """Map job id -> the job's YAML body (text at deeper indentation)."""
    marker = "\njobs:\n"
    start = workflow_text.index(marker) + len(marker)
    body = workflow_text[start:]
    parts = re.split(r"\n  ([A-Za-z0-9_-]+):\n", "\n" + body)
    # parts[0] is any preamble; then alternating (job id, body).
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def uses_lines(workflow_text: str) -> list[tuple[str, int]]:
    """Every SHA-pinned `uses:` as (action, major), the major read off its comment.

    Only well-formed references are returned. Anything the strict form rejects
    is `unpinned_uses`' to report — splitting them keeps a malformed reference
    from arriving here as a silently missing row, which is how an unpinned
    action would otherwise pass the Node 24 table by being invisible to it.
    """
    return [(m.group("action"), int(m.group("major"))) for m in PINNED_USES.finditer(workflow_text)]


def pinnable_uses(workflow_text: str) -> list[str]:
    """Every `uses:` line the pin rule applies to, stripped.

    The `./`-relative exemption lives here and nowhere else. It was duplicated
    once — `unpinned_uses` skipped local composite actions while the test that
    reconciles the graded and reported sets counted them — which passed only
    because neither workflow uses one, and would have failed the first time
    either did.
    """
    lines = []
    for line in workflow_text.splitlines():
        reference = ANY_USES.match(line)
        if reference is None or reference.group("reference").startswith("./"):
            continue
        lines.append(line.strip())
    return lines


def unpinned_uses(workflow_text: str) -> list[str]:
    """Every `uses:` line that is not a SHA pin with a version comment."""
    return [line for line in pinnable_uses(workflow_text) if not PINNED_USES.match(line)]
