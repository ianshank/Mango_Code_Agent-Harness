"""Runtime write policy for the agent's file-write tool.

``protected_paths`` in ``governance-policy.json`` is enforced by
``validate_invariants.py`` at CI time, against the set of files a commit changed.
That is a review gate: it reports the modification after the fact. Nothing
consulted it while an agent was running, so within a single task an agent could
rewrite the guard that checks it, the policy that bounds it, the hooks the
orchestrator executes on the host, or its own persona -- and the CI gate would
only notice afterwards, on a branch where CI is advisory.

Enforcement was not absent, it was at the wrong granularity. The orchestrator
runs ``validate_invariants.py`` through ``pre-nemotron-run`` at the top of every
``execute_agent`` call, so a protected-path write by one agent is caught at the
*next* agent boundary. An agent has up to ``max_iterations`` turns and a
per-task tool-call budget between boundaries, and the last agent in the loop is
never re-validated before its own post-run hook fires. This module moves the
same matcher to tool-call granularity.

It deliberately reuses ``validate_invariants.is_protected`` rather than
reimplementing the match: two matchers would be two behaviours, and the CI gate
is the one with the liveness suite behind it.

Spec: ``docs/specs/agent-containment.md`` (R-AC-6, R-AC-7).
"""

from __future__ import annotations

import posixpath
from pathlib import Path

from harness.shared.validate_invariants import is_protected, load_protected_patterns

#: Resolved next to this module so the policy travels with the installed harness
#: rather than being read out of whatever tree the agent is working in.
DEFAULT_POLICY_PATH = Path(__file__).resolve().parent / "governance-policy.json"

#: Denied regardless of ``protected_paths``. Git's own directory is invisible to
#: ``validate_invariants``: it enumerates staged, tracked-modified and untracked
#: files, and ``git ls-files``/``git diff`` never report anything under ``.git``.
#: A hook written there, or a ``core.fsmonitor`` entry in ``.git/config``, runs on
#: the host at the next commit or index refresh with no gate able to see it.
ALWAYS_DENIED_PREFIXES = (".git/",)


def _normalise(relpath: str) -> str:
    """Return a POSIX, workspace-relative path suitable for pattern matching.

    ``protected_paths`` patterns are written repo-root-relative with forward
    slashes, which is what ``is_protected`` matches against.

    ``normpath`` already drops a leading ``./``. Stripping one with
    ``lstrip("./")`` would be a character-set strip, not a prefix strip: it eats
    the leading dot of every dotfile, turning ``.mango/hooks/x.sh`` into
    ``mango/hooks/x.sh`` and ``.git/config`` into ``git/config`` -- neither of
    which matches any pattern, so the entire control surface would read as
    unprotected. Pinned by ``test_dot_prefixed_paths_are_not_mangled``.
    """
    return posixpath.normpath(Path(relpath).as_posix())


def write_denial_reason(relpath: str, policy_path: Path | None = None) -> str | None:
    """Return why ``relpath`` may not be written, or ``None`` when it may.

    Fails closed: a policy that cannot be read denies the write. The alternative
    -- defaulting to the built-in pattern list, or to allowing -- is the
    inversion this repository has already had to fix in three separate gates,
    where an unreadable policy silently relaxed the control it configured.
    """
    candidate = _normalise(relpath)

    for prefix in ALWAYS_DENIED_PREFIXES:
        if candidate == prefix.rstrip("/") or candidate.startswith(prefix):
            return f"{candidate} is inside the git directory, which no agent write may target"

    try:
        patterns = load_protected_patterns(policy_path or DEFAULT_POLICY_PATH)
    except (Exception, SystemExit) as exc:
        # An unreadable policy must deny. Falling back to a built-in list would let
        # a malformed policy widen what an agent may write, which is the failure
        # mode this module exists to prevent.
        #
        # SystemExit is listed explicitly because it is not an Exception:
        # load_protected_patterns fails closed by calling sys.exit(1), which is
        # right for a CLI gate and fatal here -- an unreadable policy would kill
        # the agent process mid-run instead of refusing one tool call.
        return f"the write policy could not be read, so the write is denied: {exc}"

    if is_protected(candidate, patterns):
        return (
            f"{candidate} matches a protected path; changing it requires a reviewed "
            "change with the infra-reviewed attestation, not an agent write"
        )
    return None
