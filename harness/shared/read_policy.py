"""Runtime read policy for the agent's file-read tool.

``command_actions.classify`` grades ``cat .env`` as ``secret_access`` -- an action
no role in ``agent-policy.json`` holds -- so reading a credential through
``run_command`` is denied for every agent. That grading is a property of the
*command*, and it protected the only file-reading door the agent had.

``read_file`` is a second door. It resolves a path and reads it directly, so
nothing in ``command_actions`` sees it. Mapped to the ``read`` action and left
ungoverned, ``read_file(".env")`` would return ``NVIDIA_API_KEY`` into
``conversation_history``, which is sent back to the model API on the next turn --
the exact inversion ``command_actions`` documents at its credential rule: *the
action model grades the effect rather than the tool*.

This module is that door's policy, and it is the single source of the pattern
both doors match. ``command_actions`` composes its command-scanning form from
``CREDENTIAL_FILENAME_ALTERNATION`` here rather than restating it, because two
spellings of one control are two controls that drift.

It deliberately does **not** consult ``protected_paths``. The agent has to read
the Makefile, the policies and its own contracts to do its work; reading is not
writing, and a read policy that mirrored the write policy would stop the agent
doing the job it is for.

Spec: ``docs/specs/agent-read-patch-tools.md`` (R-RPT-2, R-RPT-3).
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path, PurePosixPath

from harness.shared.write_policy import ALWAYS_DENIED_SEGMENTS

#: The filename alternation, unanchored, so each caller composes the boundaries
#: its own input needs: this module anchors it to a whole path segment, while
#: ``command_actions`` wraps it in ``(?:^|[\s/])...(?:\s|$)`` to find it inside a
#: command string. One alternation, two anchorings -- not two patterns.
CREDENTIAL_FILENAME_ALTERNATION = r"\.env(?:\.[\w-]+)?|\.netrc|\.npmrc|\.pypirc|id_[rd]sa|[\w.-]+\.pem"

#: Anchored to a whole path segment. Matching a *segment* rather than searching
#: the string keeps ``prod.pem.txt`` and ``notenv`` from reading as credentials
#: while still catching ``secrets/id_rsa``.
CREDENTIAL_FILENAME_PATTERN = re.compile(rf"^(?:{CREDENTIAL_FILENAME_ALTERNATION})$")


def _normalise(relpath: str) -> str:
    """Return a POSIX, workspace-relative path suitable for segment matching.

    ``normpath`` already drops a leading ``./``. Stripping one with
    ``lstrip("./")`` would be a character-set strip rather than a prefix strip:
    it eats the leading dot of every dotfile, turning ``.env`` into ``env`` and
    ``.git/config`` into ``git/config`` -- neither of which matches anything
    here, so the whole policy would read as permissive. ``write_policy`` carries
    the same note for the same reason; pinned by
    ``test_dot_prefixed_paths_are_not_mangled``.
    """
    return posixpath.normpath(Path(relpath).as_posix())


def read_denial_reason(relpath: str) -> str | None:
    """Return why ``relpath`` may not be read, or ``None`` when it may.

    Every check is a segment comparison against a static pattern, so this
    function reads no files and cannot fail closed on an unreadable policy --
    which is why, unlike ``write_denial_reason``, it takes no policy path.
    """
    candidate = _normalise(relpath)
    segments = candidate.split("/")

    # Defence in depth. `execute_read_file` rejects both of these before calling
    # here via `is_relative_to(workspace)`; repeating the check keeps this
    # function safe for any other caller, because a helper that only holds when
    # its caller already checked is a helper waiting to be misused.
    if PurePosixPath(candidate).is_absolute():
        return f"{candidate} is an absolute path, and a read target must be workspace-relative"
    if ".." in segments:
        return f"{candidate} climbs out of the workspace"

    # `.git` holds the credentials a remote URL carries and the hooks that run on
    # the host. The write policy already refuses to write there; refusing to read
    # it keeps a push token out of the conversation history. Segment matching, so
    # `.gitignore` and `.gitleaks.toml` -- ordinary files sharing the prefix --
    # stay readable.
    for denied in ALWAYS_DENIED_SEGMENTS:
        if denied in segments:
            return f"{candidate} is inside a {denied} directory, which no agent read may target"

    # Every segment, not just the last: `secrets/.env/note` names a credential
    # directory, and being stricter than `command_actions` on the read side keeps
    # the parity property one-directional and safe.
    for segment in segments:
        if CREDENTIAL_FILENAME_PATTERN.match(segment):
            return (
                f"{candidate} names a credential-bearing file; reading it is the "
                "secret_access action, which no agent role holds"
            )
    return None


__all__ = [
    "CREDENTIAL_FILENAME_ALTERNATION",
    "CREDENTIAL_FILENAME_PATTERN",
    "read_denial_reason",
]
