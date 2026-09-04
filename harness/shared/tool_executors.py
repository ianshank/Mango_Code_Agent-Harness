"""Isolated executors for local tool operations (file read/write/patch & brokered execution)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from harness.shared.agent_authority import execution_identity
from harness.shared.governance.process_backend import DEFAULT_MAX_OUTPUT_BYTES, _cap
from harness.shared.governance.verdict import BROKER_BLOCKED
from harness.shared.read_policy import read_denial_reason
from harness.shared.tool_result_format import format_execution_result
from harness.shared.write_policy import active_policy_path, write_denial_reason

if TYPE_CHECKING:
    from harness.shared.governance.broker import ExecutionBroker

#: The action a file write requires, named once. `authorize_write` asks the
#: policy decision point for exactly this and cannot be steered off it by a
#: filename, which is how a `-find` filepath previously graded `read`.
WRITE_ACTION = "write"

logger = logging.getLogger(__name__)


def _resolve_in_workspace(workspace_dir: Path, filepath: str) -> tuple[Path, Path, str | None]:
    """Resolve ``filepath`` under ``workspace_dir``, refusing anything that escapes.

    Returns ``(workspace, target, denial)``. ``.resolve()`` follows symlinks
    before the comparison, so a link pointing out of the tree is refused by its
    destination rather than its name.

    Extracted because three tools now need the identical preamble, and three
    copies of a containment check are three chances for one of them to drift.
    """
    workspace = workspace_dir.resolve()
    target_path = (workspace / filepath).resolve()
    if not target_path.is_relative_to(workspace):
        return workspace, target_path, "path escapes workspace"
    return workspace, target_path, None


def _read_preserving_newlines(target_path: Path) -> str:
    """Read text without translating line endings.

    ``Path.read_text`` opens in universal-newline mode, so a CRLF file arrives as
    LF and is written back as LF: a one-word patch silently rewrites every line
    in the file. ``newline=""`` disables the translation in both directions, and
    the ``newline=`` keyword on ``Path.read_text`` itself is 3.13+, above this
    repository's 3.9 floor (R-RPT-7).
    """
    with open(target_path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _slice_bounds_denial(start_line: int | None, end_line: int | None) -> str | None:
    """Reject bounds that would silently mean something else.

    A negative or zero ``start_line`` indexes from the end of the list rather
    than failing, so a model that sends ``0`` gets a different slice than it
    asked for and no error to react to.
    """
    for name, value in (("start_line", start_line), ("end_line", end_line)):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{name} must be an integer, got {type(value).__name__}"
        if value < 1:
            return f"{name} must be 1 or greater, got {value}"
    if start_line is not None and end_line is not None and end_line < start_line:
        return f"end_line ({end_line}) is before start_line ({start_line})"
    return None


def _write_preserving_newlines(target_path: Path, content: str) -> None:
    """Write text without translating line endings."""
    with open(target_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def execute_write_file(workspace_dir: Path, filepath: str, content: str) -> str:
    """Local tool implementation to write a file with workspace confinement & write policy.

    Two checks, in order:
    1. Confinement keeps the write inside the workspace;
    2. Write policy keeps it off the control surface within the workspace.
    """
    workspace, target_path, denial = _resolve_in_workspace(workspace_dir, filepath)
    if denial is not None:
        logger.warning("Denied write outside the workspace: %s", filepath)
        return f"Error writing file {filepath}: {denial}"

    # `policy_path` is passed explicitly rather than defaulted: a parameter no
    # caller supplies is never exercised outside tests, which is how the write
    # gate came to match this repository's patterns against any tree at all
    # (R-PPP-4). `active_policy_path` still resolves to the harness policy
    # unless one is supplied, and a supplied one can only add denials.
    denial = write_denial_reason(
        str(target_path.relative_to(workspace)), policy_path=active_policy_path()
    )
    if denial is not None:
        logger.warning("Denied write to a governed path: %s (%s)", filepath, denial)
        return f"Error writing file {filepath}: {denial}"

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        _write_preserving_newlines(target_path, content)
        return f"Success: Wrote {len(content)} characters to {target_path.resolve()}"
    except Exception as e:
        logger.exception("Failed writing %s", filepath)
        return f"Error writing file {filepath}: {str(e)}"


def execute_read_file(
    workspace_dir: Path,
    filepath: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read a workspace file without spawning a subprocess (R-RPT-1).

    Three checks, in order: confinement, read policy, then bounds. The read
    policy is the point of this function existing rather than the model calling
    ``run_command("cat ...")`` -- that path is graded by ``command_actions``, and
    a direct read that skipped an equivalent check would be a second, ungoverned
    door onto the same credentials (R-RPT-2, R-RPT-3).

    Content is returned verbatim, never line-number-prefixed: ``apply_patch``
    matches an exact substring, and a model that copied a line number into
    ``old_text`` would miss every time. A header is emitted only when the result
    is *not* the whole file, so a full read stays byte-for-byte pasteable.
    """
    workspace, target_path, denial = _resolve_in_workspace(workspace_dir, filepath)
    if denial is not None:
        logger.warning("Denied read outside the workspace: %s", filepath)
        return f"Error reading file {filepath}: {denial}"

    denial = read_denial_reason(str(target_path.relative_to(workspace)))
    if denial is not None:
        logger.warning("Denied read of a governed path: %s (%s)", filepath, denial)
        return f"Error reading file {filepath}: {denial}"

    denial = _slice_bounds_denial(start_line, end_line)
    if denial is not None:
        logger.warning("Denied read with bad bounds: %s (%s)", filepath, denial)
        return f"Error reading file {filepath}: {denial}"

    if target_path.is_dir():
        try:
            entries = sorted(p.name for p in target_path.iterdir())
            listing = "\n".join(entries)
            prefix = f"Error reading file {filepath}: Path is a directory. Directory contents:\n"
            return _cap(prefix + listing, DEFAULT_MAX_OUTPUT_BYTES)
        except OSError as e:
            return f"Error reading file {filepath}: {e}"

    try:
        content = _read_preserving_newlines(target_path)
    except FileNotFoundError:
        logger.info("File does not exist: %s", filepath)
        return f"Error reading file {filepath}: File does not exist. You can create it with write_file."
    except Exception as e:
        logger.exception("Failed reading %s", filepath)
        return f"Error reading file {filepath}: {str(e)}"

    header = ""
    if start_line is not None or end_line is not None:
        # `keepends=True` and a plain join so a sliced CRLF file keeps its own
        # line endings, the same property `apply_patch` preserves.
        lines = content.splitlines(keepends=True)
        first = start_line or 1
        # `end_line` is reported after clamping to the file's actual length, not
        # echoed back raw: `lines[first - 1:end_line]` already clamps a too-large
        # `end_line` to `len(lines)` (Python slice semantics), but the header used
        # to print the *requested* value regardless -- "lines 1-200 of 3" for a
        # 3-line file, describing a range that was never returned.
        last = min(end_line, len(lines)) if end_line is not None else len(lines)
        content = "".join(lines[first - 1:last])
        header = f"# {filepath} lines {first}-{last} of {len(lines)}\n"

    # `header + content` is capped as one unit, not `content` alone: capping only
    # the body and prepending the header afterward let the combined result exceed
    # `DEFAULT_MAX_OUTPUT_BYTES` by `len(header)` bytes, silently breaking the
    # parity `run_command` output R-RPT-4 exists to guarantee. `_cap` is applied
    # exactly once, to the same string that is returned.
    if not header and len(content.encode("utf-8")) > DEFAULT_MAX_OUTPUT_BYTES:
        header = f"# {filepath} truncated\n"
    return _cap(header + content, DEFAULT_MAX_OUTPUT_BYTES)


def execute_apply_patch(workspace_dir: Path, filepath: str, old_text: str, new_text: str) -> str:
    """Replace one exactly-unique substring in a workspace file.

    Confinement and write policy are the same two checks ``execute_write_file``
    makes, in the same order, because this writes to the same places for the same
    reasons (R-RPT-6).

    The uniqueness requirement is the safety property: a patch that matched twice
    would edit an arbitrary one of them, and a patch that matched zero times
    would silently do nothing. Both are refused, and the count is reported so the
    model can widen ``old_text`` rather than retry the same call (R-RPT-5).
    """
    workspace, target_path, denial = _resolve_in_workspace(workspace_dir, filepath)
    if denial is not None:
        logger.warning("Denied patch outside the workspace: %s", filepath)
        return f"Error patching file {filepath}: {denial}"

    relpath = str(target_path.relative_to(workspace))

    # The read policy is consulted first because a patch *reads* before it
    # writes, and the count it reports is an answer about the file's contents:
    # `matched 0 times` and `matched 1 times` distinguish `old_text` present from
    # absent, one call at a time. That made `apply_patch` a substring oracle over
    # every file `read_file` refuses -- `.env` included, whose bytes could
    # therefore be recovered a character at a time without ever calling the tool
    # that is gated. Checking write first would hide this behind the write
    # denial and leave the oracle live for any path the write policy allowed.
    denial = read_denial_reason(relpath)
    if denial is not None:
        logger.warning("Denied patch reading a governed path: %s (%s)", filepath, denial)
        return f"Error patching file {filepath}: {denial}"

    denial = write_denial_reason(relpath, policy_path=active_policy_path())
    if denial is not None:
        logger.warning("Denied patch of a governed path: %s (%s)", filepath, denial)
        return f"Error patching file {filepath}: {denial}"

    try:
        content = _read_preserving_newlines(target_path)
    except Exception as e:
        logger.exception("Failed reading %s before patch", filepath)
        return f"Error patching file {filepath}: {str(e)}"

    # An empty `old_text` counts once per position, so it is refused here by the
    # same rule rather than needing a special case.
    count = content.count(old_text)
    if count != 1:
        logger.warning("Denied patch with a non-unique match: %s (matched %d times)", filepath, count)
        return (
            f"Error patching file {filepath}: old_text matched {count} times, expected exactly 1. "
            "Widen old_text with surrounding lines until it identifies one place in the file."
        )

    try:
        with open(target_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content.replace(old_text, new_text, 1))
    except Exception as e:
        logger.exception("Failed writing patched %s", filepath)
        return f"Error patching file {filepath}: {str(e)}"
    return f"Success: patched {filepath}"


def authorize_write(broker: ExecutionBroker, active_role: str, filepath: str) -> str | None:
    """Return why the policy decision point refuses this role a write, or ``None``.

    The `write` action is asked for **directly**. The first version of this
    function synthesised a command (``tee <path>``) and let `classify` derive the
    action from it, which put model-controlled text between the caller and the
    question being asked -- and the text won. A `filepath` of ``-find`` makes
    `classify` return `read` (the `find` shape rule matches the substring) and
    `write_targets` return nothing (a leading `-` reads as a flag), so the
    verifier and the planner -- neither of which holds `write` -- created files
    through *both* transports. A filepath containing a space graded the wrong
    token; one containing a quote graded `destructive`.

    Deriving an action from a command is right when the input *is* a command:
    `run_command` must be graded on what it will do. It is wrong here, where the
    action is known before the call. `decide` is asked for `write` and cannot be
    told otherwise, so no filename can change the question.

    This began as `mcp_server._broker_authorize_write`, called before `write_file`
    and `apply_patch` there -- and nowhere else. `ToolDispatcher`, the path the
    orchestrator actually runs, asked the PDP nothing: it went straight to
    `execute_write_file`, which enforces the *write policy* (protected paths,
    credential names, containment) but knows nothing about which role is acting
    (code-quality-tech-debt-plan R-CQ-5).
    """
    return broker.authorize_action(execution_identity(active_role), WRITE_ACTION)


def execute_run_command(
    broker: ExecutionBroker,
    active_role: str,
    workspace_dir: Path,
    command: str,
    timeout: int | None = None,
) -> str:
    """Run a command through the approved execution broker (INV-8)."""
    kwargs: dict[str, Any] = {
        "context": {"agent_id": execution_identity(active_role)},
        "cwd": workspace_dir,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    result = broker.execute_command(command, **kwargs)
    if result.status == BROKER_BLOCKED:
        from harness.shared.debug_dump import redact_text
        logger.warning("Broker denied command %r for role %s: %s", redact_text(command), active_role, result.reason)
    return format_execution_result(result)


__all__ = [
    "WRITE_ACTION",
    "authorize_write",
    "execute_apply_patch",
    "execute_read_file",
    "execute_run_command",
    "execute_write_file",
]
