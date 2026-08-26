import contextlib
import json
import os
import time
import uuid
from pathlib import Path

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


@contextlib.contextmanager
def _file_lock(filepath: Path):
    lockfile = filepath.with_suffix(".lock")
    timeout = 10.0
    start = time.time()
    while True:
        try:
            fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except (FileExistsError, OSError):
            if time.time() - start > timeout:
                raise TimeoutError(f"Could not acquire lock for {filepath}")
            time.sleep(0.1)
    try:
        yield
    finally:
        try:
            lockfile.unlink(missing_ok=True)
        except OSError:
            pass


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
        gaps = json.loads(GAPS_FILE.read_text(encoding="utf-8"))
        gaps.append(entry)

        # Write to a temp file first for atomic replacement
        temp_file = GAPS_FILE.with_suffix(".tmp")
        temp_file.write_text(json.dumps(gaps, indent=2), encoding="utf-8")
        os.replace(temp_file, GAPS_FILE)

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
        hypotheses = json.loads(HYPOTHESES_FILE.read_text(encoding="utf-8"))
        hypotheses.append(entry)

        temp_file = HYPOTHESES_FILE.with_suffix(".tmp")
        temp_file.write_text(json.dumps(hypotheses, indent=2), encoding="utf-8")
        os.replace(temp_file, HYPOTHESES_FILE)

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
