"""
Meta-tools: in-process memory and hypothesis tracking for the Mango MAS agent loop.

Provides file-locked JSON stores for gap tracking (``gaps.json``) and hypothesis
logging (``hypotheses.json``). When ``workspace_dir`` is supplied the store lives
under ``<workspace>/.mango/memory/``; otherwise the legacy install-root
``MEMORY_DIR`` is used for backward compatibility. Retention bounds come from
``policy_loader.agent_memory_defaults`` (NS-17).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
import typing
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Legacy install-root store. Prefer resolve_memory_dir(workspace_dir) for new callers.
MEMORY_DIR = Path(__file__).resolve().parent.parent.parent / ".mango" / "memory"
GAPS_FILE = MEMORY_DIR / "gaps.json"
HYPOTHESES_FILE = MEMORY_DIR / "hypotheses.json"


def resolve_memory_dir(workspace_dir: Path | None = None) -> Path:
    """Return the memory directory for ``workspace_dir``, or the legacy install root.

    ``workspace_dir=None`` preserves pre-NS-17 behaviour (``MEMORY_DIR`` under the
    harness install path) so existing monkeypatches and out-of-workspace callers
    keep working.
    """
    if workspace_dir is not None:
        resolved = Path(workspace_dir) / ".mango" / "memory"
        logger.debug("memory dir resolved to workspace scope: %s", resolved)
        return resolved
    logger.debug("memory dir resolved to legacy install root: %s", MEMORY_DIR)
    return MEMORY_DIR


def _gaps_path(workspace_dir: Path | None = None) -> Path:
    return resolve_memory_dir(workspace_dir) / "gaps.json"


def _hypotheses_path(workspace_dir: Path | None = None) -> Path:
    return resolve_memory_dir(workspace_dir) / "hypotheses.json"


def _ensure_memory_files(workspace_dir: Path | None = None) -> tuple[Path, Path]:
    """Ensure the JSON memory files exist; return (gaps_file, hypotheses_file)."""
    memory_dir = resolve_memory_dir(workspace_dir)
    gaps_file = memory_dir / "gaps.json"
    hypotheses_file = memory_dir / "hypotheses.json"
    memory_dir.mkdir(parents=True, exist_ok=True)
    if not gaps_file.exists():
        gaps_file.write_text("[]", encoding="utf-8")
    if not hypotheses_file.exists():
        hypotheses_file.write_text("[]", encoding="utf-8")
    return gaps_file, hypotheses_file


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


DEFAULT_LOCK_TIMEOUT_S = 10.0
DEFAULT_LOCK_POLL_S = 0.1
#: Floor for the poll interval: keeps the poll budget finite and prevents a
#: zero/negative interval from becoming a busy-spin.
MIN_LOCK_POLL_S = 0.001


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
    early ``TimeoutError`` instead of hanging the caller — and, in CI, the job.
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


def knowledge_gap_log(
    question: str,
    what_needed: str,
    proposed_approach: str,
    workspace_dir: Path | None = None,
    policy_path: Path | None = None,
) -> str:
    """
    Record a knowledge gap: something the agent could not answer or do, and what would be needed to fill the gap.
    This is the explicit alternative to hallucinating an answer.

    When ``workspace_dir`` is set the entry is scoped under that workspace's
    ``.mango/memory/``; otherwise the legacy install-root store is used.
    After append the store is FIFO-trimmed to ``agent_memory.max_gaps``.
    ``policy_path`` selects which governance policy supplies that bound
    (``None`` keeps the loader default).
    """
    from harness.shared.policy_loader import agent_memory_defaults

    gaps_file, _ = _ensure_memory_files(workspace_dir)
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "question": question,
        "what_needed": what_needed,
        "proposed_approach": proposed_approach,
    }

    max_gaps = agent_memory_defaults(policy_path)["max_gaps"]
    with _file_lock(gaps_file):
        gaps = _read_json_safe(gaps_file)
        gaps.append(entry)
        gaps = _fifo_trim(gaps, max_gaps, label="knowledge gaps")

        # Write to a temp file first for atomic replacement
        temp_file = gaps_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(gaps, indent=2), encoding="utf-8")
        temp_file.replace(gaps_file)

    if max_gaps == 0:
        return f"Knowledge gap entry not retained: retention disabled (agent_memory.max_gaps=0). ID: {entry['id']}."
    return f"Knowledge gap logged successfully. ID: {entry['id']}. Total gaps logged: {len(gaps)}"


def hypothesis_register(
    claim: str,
    reasoning: str,
    confidence: float,
    workspace_dir: Path | None = None,
    policy_path: Path | None = None,
) -> str:
    """
    Record a provisional belief: 'I think X is true because Y.'
    Hypotheses can be updated or falsified later as evidence arrives.

    When ``workspace_dir`` is set the entry is scoped under that workspace's
    ``.mango/memory/``; otherwise the legacy install-root store is used.
    After append the store is FIFO-trimmed to ``agent_memory.max_hypotheses``.
    ``policy_path`` selects which governance policy supplies that bound
    (``None`` keeps the loader default).
    """
    from harness.shared.policy_loader import agent_memory_defaults

    _, hypotheses_file = _ensure_memory_files(workspace_dir)
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "claim": claim,
        "reasoning": reasoning,
        "confidence": confidence,
        "status": "provisional",
    }

    max_hypotheses = agent_memory_defaults(policy_path)["max_hypotheses"]
    with _file_lock(hypotheses_file):
        hypotheses = _read_json_safe(hypotheses_file)
        hypotheses.append(entry)
        hypotheses = _fifo_trim(hypotheses, max_hypotheses, label="hypotheses")

        temp_file = hypotheses_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(hypotheses, indent=2), encoding="utf-8")
        temp_file.replace(hypotheses_file)

    if max_hypotheses == 0:
        return f"Hypothesis entry not retained: retention disabled (agent_memory.max_hypotheses=0). ID: {entry['id']}."
    return f"Hypothesis registered successfully. ID: {entry['id']}. Total hypotheses: {len(hypotheses)}"


def load_open_gaps(workspace_dir: Path | None = None) -> list:
    """Return knowledge gaps most-recent-first (empty list when the store is absent)."""
    gaps_file = _gaps_path(workspace_dir)
    if not gaps_file.exists():
        return []
    gaps = _read_json_safe(gaps_file)
    # Append order is chronological; reverse for most-recent-first.
    return list(reversed(gaps))


def format_gaps_for_planner(
    gaps: list | None = None,
    *,
    workspace_dir: Path | None = None,
    limit: int | None = None,
    policy_path: Path | None = None,
) -> str:
    """Format open gaps for injection into the planner prompt.

    Truncates to ``planner_gap_limit`` from policy (or ``limit`` when given).
    ``policy_path`` selects which governance policy supplies that limit
    (``None`` keeps the loader default). Returns ``""`` when there is nothing
    to surface so the prompt stays clean.
    """
    from harness.shared.policy_loader import agent_memory_defaults

    if gaps is None:
        gaps = load_open_gaps(workspace_dir)
    if limit is None:
        limit = agent_memory_defaults(policy_path)["planner_gap_limit"]
    selected = list(gaps)[:limit]
    if not selected:
        return ""
    lines = ["Open knowledge gaps (most recent first):"]
    for gap in selected:
        question = gap.get("question", "")
        what_needed = gap.get("what_needed", "")
        lines.append(f"- Q: {question}; need: {what_needed}")
    return "\n".join(lines) + "\n"


META_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "knowledge_gap_log",
            "description": (
                "Record a knowledge gap: something the agent could not answer or do, "
                "and what would be needed to fill the gap. This is the explicit "
                "alternative to hallucinating an answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question or task that could not be completed."},
                    "what_needed": {
                        "type": "string",
                        "description": "What specific context, dependency, or tool is needed to answer it.",
                    },
                    "proposed_approach": {
                        "type": "string",
                        "description": "How the gap might be resolved in the future.",
                    },
                },
                "required": ["question", "what_needed", "proposed_approach"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hypothesis_register",
            "description": (
                "Record a provisional belief: 'I think X is true because Y.' "
                "Hypotheses can be updated or falsified later as evidence arrives."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "The provisional belief or claim."},
                    "reasoning": {"type": "string", "description": "The logic or evidence supporting the claim."},
                    "confidence": {"type": "number", "description": "Confidence level between 0.0 and 1.0"},
                },
                "required": ["claim", "reasoning", "confidence"],
                "additionalProperties": False,
            },
        },
    },
]
