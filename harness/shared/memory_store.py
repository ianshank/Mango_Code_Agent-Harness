"""Generic append-only JSON-list store mechanics: locking, recovery, retention.

Split out of ``meta_tools`` when the hypothesis revision path (DEC-057) pushed
that module past ``limits.size_budget_lines``. The seam is where the knowledge
actually divides. Nothing here knows what a knowledge gap or a hypothesis is,
nor where this repository keeps them: these are the mechanics of *any*
append-only JSON list on disk -- how concurrent writers are ordered, how a
malformed file is recovered without losing it, how a retention bound is applied,
how a write is made atomic. ``meta_tools`` keeps what is specific to this
harness: the memory directory layout, the record shapes, the hypothesis
lifecycle, and the schemas the model is shown.

Deliberately *not* moved: ``MEMORY_DIR`` and everything that reads it
(``resolve_memory_dir`` and the path helpers). Those are this repository's
memory layout rather than store mechanics, and they are also the seam the test
suite monkeypatches -- relocating the constant would have silently broken every
``monkeypatch.setattr(meta_tools, "MEMORY_DIR", ...)`` by leaving the patch
pointing at a name the code no longer reads.

Every public name here is re-exported from ``meta_tools``, so existing callers
and monkeypatches keep working against either module.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_LOCK_TIMEOUT_S = 10.0
DEFAULT_LOCK_POLL_S = 0.1
#: Floor for the poll interval: keeps the poll budget finite and prevents a
#: zero/negative interval from becoming a busy-spin.
MIN_LOCK_POLL_S = 0.001


def _fifo_trim(entries: list, max_entries: int, *, label: str) -> list:
    """Keep the newest ``max_entries`` items (FIFO drop from the front).

    ``max_entries == 0`` means retention is disabled: return an empty list.
    Python's ``entries[-0:]`` is ``entries[0:]`` (the full list), so the zero
    case must be handled explicitly rather than falling through to a slice.
    """
    if max_entries < 0:
        raise ValueError(f"max_entries must be non-negative, got {max_entries}")
    if max_entries == 0:
        if entries:
            logger.info("trimmed %d oldest %s (retained=0; policy disabled)", len(entries), label)
        return []
    if len(entries) <= max_entries:
        return entries
    trimmed = len(entries) - max_entries
    logger.info(
        "trimmed %d oldest %s (retained=%d)",
        trimmed,
        label,
        max_entries,
    )
    return entries[-max_entries:]


def _read_json_safe(file_path: Path) -> list:
    """Read a JSON file safely, backing it up and resetting if malformed."""
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Expected JSON list")
        return data
    except FileNotFoundError:
        # The store can vanish between `_ensure_memory_files` and the lock (a
        # cleaned workspace, a concurrent `rm -rf`). An absent store is an empty
        # one; raising here would surface as a `RAISED` tool outcome on one door
        # and an exception to library callers, where every other failure mode is
        # a `failed` string the model can read.
        logger.info("Memory store %s is absent; treating as empty", file_path)
        return []
    except (json.JSONDecodeError, ValueError) as exc:
        backup_path = file_path.with_name(f"{file_path.name}.malformed.{int(time.time())}")
        try:
            file_path.rename(backup_path)
        except OSError as backup_err:
            # The only surviving copy cannot be backed up; preserve it rather
            # than destroying the malformed store, and propagate the failure so
            # callers can route a structured alert into the errors channel.
            logger.error(
                "Malformed JSON in %s could not be backed up to %s (backup error: %s; parse error: %s)."
                " Store NOT reset to prevent data loss.",
                file_path,
                backup_path,
                backup_err,
                exc,
            )
            raise RuntimeError(
                f"Memory store {file_path} is malformed and the backup attempt failed: {backup_err}"
            ) from exc
        file_path.write_text("[]", encoding="utf-8")
        logger.error(
            "Malformed JSON in %s backed up to %s (Error: %s). Resetting store.",
            file_path,
            backup_path,
            exc,
        )
        return []


@contextlib.contextmanager
def file_lock(
    filepath: Path,
    timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
    poll_s: float = DEFAULT_LOCK_POLL_S,
) -> typing.Iterator[None]:
    """Best-effort single-host advisory lock via an O_CREAT|O_EXCL lockfile.

    Only contention (the lockfile already existing) is retried; any other
    OSError (permissions, disk full) propagates immediately rather than
    spinning until the timeout.

    The retry loop is bounded by a poll budget as well as by the deadline, so
    "this never spins forever" is a structural property of the loop rather than
    a consequence of the clock behaving. A clock regression then degrades to an
    early ``TimeoutError`` instead of hanging the caller -- and, in CI, the job.
    """
    lockfile = filepath.with_suffix(".lock")
    effective_poll_s = max(poll_s, MIN_LOCK_POLL_S)
    deadline = time.monotonic() + timeout_s
    max_polls = max(1, int(timeout_s / effective_poll_s) + 2)
    acquired = False
    for _ in range(max_polls):
        try:
            fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                break
            time.sleep(effective_poll_s)
    if not acquired:
        raise TimeoutError(f"Could not acquire lock for {filepath}")
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lockfile.unlink(missing_ok=True)


# Backward-compatible alias for existing internal callers.
_file_lock = file_lock


def append_locked(
    store_file: Path,
    entry: dict[str, typing.Any],
    max_entries: int,
    *,
    label: str,
    before_append: typing.Callable[[list], None] | None = None,
) -> list:
    """Append ``entry`` to ``store_file`` under its lock and return the kept list.

    The read-modify-write both meta-tool stores perform, in one place: acquire
    the advisory lock, read (repairing a malformed store), optionally let the
    caller amend the entries already there, append, FIFO-trim to ``max_entries``,
    then replace the file atomically via a temp file.

    ``before_append`` runs *inside* the lock and receives the live list, which is
    what makes a cross-record update -- a revision marking the entry it
    supersedes -- safe against a concurrent writer. Doing it outside would read
    one list and write another, losing whichever update landed second.

    Extracted from ``knowledge_gap_log`` and ``hypothesis_register``, which had
    carried near-identical copies of this sequence. The duplication was invisible
    to ``check_dedup.py`` (it polices per-stack script shims, not intra-module
    repetition), so it would have been maintained twice indefinitely -- and the
    revision path was the first change to make the two copies diverge.
    """
    # Recreate the store's directory if it went away. `_read_json_safe` already
    # treats an absent *file* as an empty store, but that recovery was
    # unreachable when the whole directory had gone: `file_lock` opens
    # `<store>.lock` beside it and raised `FileNotFoundError` first, and the
    # temp-file write below would have failed for the same reason. Done here
    # rather than inside `file_lock` because it is this function that promises
    # store recovery -- a bare advisory lock has no business creating
    # directories for a path its caller chose. A permission error still
    # propagates: only the missing-directory case is recovered.
    store_file.parent.mkdir(parents=True, exist_ok=True)

    with file_lock(store_file):
        entries = _read_json_safe(store_file)
        if before_append is not None:
            before_append(entries)
        entries.append(entry)
        entries = _fifo_trim(entries, max_entries, label=label)

        # Write to a temp file first for atomic replacement.
        temp_file = store_file.with_suffix(".tmp")
        # Recover from an interrupted prior write while still under the store lock.
        with contextlib.suppress(FileNotFoundError):
            temp_file.unlink()

        fd = -1
        try:
            fd = os.open(temp_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                json.dump(entries, handle, indent=2)
            temp_file.replace(store_file)
        except BaseException:
            if fd != -1:
                os.close(fd)
            with contextlib.suppress(OSError):
                temp_file.unlink()
            raise
    return entries
