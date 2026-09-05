"""
Meta-tools: in-process memory and hypothesis tracking for the Mango MAS agent loop.

Provides file-locked JSON stores for gap tracking (``gaps.json``), hypothesis
logging (``hypotheses.json``), and audit trail writing (``audit.jsonl``), all
rooted at ``<repo-root>/.mango/memory/``. Path is resolved from ``__file__`` so
it is workspace-agnostic and never hardcoded.
"""

import contextlib
import json
import logging
import os
import time
import typing
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

MEMORY_DIR = Path(__file__).resolve().parent.parent.parent / ".mango" / "memory"
GAPS_FILE = MEMORY_DIR / "gaps.json"
HYPOTHESES_FILE = MEMORY_DIR / "hypotheses.json"


def _ensure_memory_files() -> None:
    """Ensure the JSON memory files exist."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if not GAPS_FILE.exists():
        GAPS_FILE.write_text("[]", encoding="utf-8")
    if not HYPOTHESES_FILE.exists():
        HYPOTHESES_FILE.write_text("[]", encoding="utf-8")


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


def knowledge_gap_log(question: str, what_needed: str, proposed_approach: str) -> str:
    """
    Record a knowledge gap: something the agent could not answer or do, and what would be needed to fill the gap.
    This is the explicit alternative to hallucinating an answer.
    """
    _ensure_memory_files()
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "question": question,
        "what_needed": what_needed,
        "proposed_approach": proposed_approach,
    }

    with _file_lock(GAPS_FILE):
        gaps = _read_json_safe(GAPS_FILE)
        gaps.append(entry)

        # Write to a temp file first for atomic replacement
        temp_file = GAPS_FILE.with_suffix(".tmp")
        temp_file.write_text(json.dumps(gaps, indent=2), encoding="utf-8")
        temp_file.replace(GAPS_FILE)

    return f"Knowledge gap logged successfully. ID: {entry['id']}. Total gaps logged: {len(gaps)}"


def hypothesis_register(claim: str, reasoning: str, confidence: float) -> str:
    """
    Record a provisional belief: 'I think X is true because Y.'
    Hypotheses can be updated or falsified later as evidence arrives.
    """
    _ensure_memory_files()
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "claim": claim,
        "reasoning": reasoning,
        "confidence": confidence,
        "status": "provisional",
    }

    with _file_lock(HYPOTHESES_FILE):
        hypotheses = _read_json_safe(HYPOTHESES_FILE)
        hypotheses.append(entry)

        temp_file = HYPOTHESES_FILE.with_suffix(".tmp")
        temp_file.write_text(json.dumps(hypotheses, indent=2), encoding="utf-8")
        temp_file.replace(HYPOTHESES_FILE)

    return f"Hypothesis registered successfully. ID: {entry['id']}. Total hypotheses: {len(hypotheses)}"


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
