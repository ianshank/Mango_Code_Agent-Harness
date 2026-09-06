"""Meta-tools: in-process memory and hypothesis tracking for the Mango MAS agent loop.

The tool surface over the two JSON stores: where this harness keeps them
(``gaps.json``, ``hypotheses.json``), the record shapes, the hypothesis
lifecycle, and the ``META_TOOLS_SCHEMA`` the model is shown. When
``workspace_dir`` is supplied the store lives under
``<workspace>/.mango/memory/``; otherwise the legacy install-root ``MEMORY_DIR``
is used for backward compatibility. Retention bounds come from
``policy_loader.agent_memory_defaults`` (NS-17).

The generic store mechanics -- the advisory file lock, malformed-file recovery,
FIFO retention and the atomic append -- live in ``harness.shared.memory_store``
and are re-exported here under their original names, so every caller that reads
``meta_tools.file_lock`` or ``meta_tools._read_json_safe`` still resolves them.

That re-export is for *reading* the names. It is deliberately not a claim that
they can be monkeypatched here: ``append_locked`` resolves its collaborators
from ``memory_store``'s own namespace, so patching ``meta_tools._read_json_safe``
would rebind a name the write path never consults. Patch them on
``memory_store``. ``MEMORY_DIR`` and the path helpers that read it are the
exception and stay in this module on purpose -- they are this repository's
layout rather than store mechanics, and relocating that constant would have
silently broken every existing test that patches it.

Revision semantics are specified in ``docs/specs/hypothesis-revision.md`` and
decided in ``docs/decisions/DEC-057.md``.
"""

from __future__ import annotations

import logging
import time
import typing
import uuid
from pathlib import Path

from harness.shared.memory_store import (
    DEFAULT_LOCK_POLL_S,
    DEFAULT_LOCK_TIMEOUT_S,
    MIN_LOCK_POLL_S,
    append_locked,
)

# Re-exported under their own names (the redundant-alias form marks them as a
# deliberate re-export, so `ruff` does not strip them as unused). Callers and
# tests reach these as `meta_tools.<name>`; the split must not move them.
from harness.shared.memory_store import _fifo_trim as _fifo_trim
from harness.shared.memory_store import _file_lock as _file_lock
from harness.shared.memory_store import _read_json_safe as _read_json_safe
from harness.shared.memory_store import file_lock as file_lock
from harness.shared.tool_result_format import failed

logger = logging.getLogger(__name__)

#: Re-exported from ``memory_store`` so this module's long-standing surface is
#: unchanged by the split. Named explicitly rather than star-imported so the
#: promise is auditable and `vulture` does not read them as dead.
__all__ = [
    "DEFAULT_LOCK_POLL_S",
    "DEFAULT_LOCK_TIMEOUT_S",
    "GAPS_FILE",
    "HYPOTHESES_FILE",
    "HYPOTHESIS_STATUSES",
    "HYPOTHESIS_STATUS_CONFIRMED",
    "HYPOTHESIS_STATUS_PROVISIONAL",
    "HYPOTHESIS_STATUS_RETRACTED",
    "HYPOTHESIS_SUPERSEDED_BY",
    "MEMORY_DIR",
    "META_TOOLS_SCHEMA",
    "MIN_LOCK_POLL_S",
    "file_lock",
    "format_gaps_for_planner",
    "hypothesis_register",
    "knowledge_gap_log",
    "load_open_gaps",
    "resolve_memory_dir",
]

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
    gaps = append_locked(gaps_file, entry, max_gaps, label="knowledge gaps")

    if max_gaps == 0:
        return f"Knowledge gap entry not retained: retention disabled (agent_memory.max_gaps=0). ID: {entry['id']}."
    return f"Knowledge gap logged successfully. ID: {entry['id']}. Total gaps logged: {len(gaps)}"


#: The status a model may assert on a hypothesis entry. ``provisional`` is the
#: default and what every entry carried before revision existed; ``confirmed``
#: and ``retracted`` are the two ways evidence can settle a belief.
HYPOTHESIS_STATUS_PROVISIONAL = "provisional"
HYPOTHESIS_STATUS_CONFIRMED = "confirmed"
HYPOTHESIS_STATUS_RETRACTED = "retracted"
HYPOTHESIS_STATUSES: tuple[str, ...] = (
    HYPOTHESIS_STATUS_PROVISIONAL,
    HYPOTHESIS_STATUS_CONFIRMED,
    HYPOTHESIS_STATUS_RETRACTED,
)
#: The range the tool schema advertises for ``confidence``. Facts about a
#: probability, not operational limits: 0.0 and 1.0 are the ends of the interval
#: the field is defined on, and a policy able to widen them would be a policy
#: able to accept a confidence of 42 -- which this store did until these
#: existed. ``tool_arg_validation`` models ``type`` but not ``minimum`` /
#: ``maximum``, so an advertised range is only kept if the function keeps it.
_CONFIDENCE_MIN = 0.0
_CONFIDENCE_MAX = 1.0

#: The key that records supersession, on the entry that was revised: the list of
#: ids that revised it, oldest first.
#:
#: Supersession is deliberately **structural, not a status**. Marking the prior
#: entry ``status: "superseded"`` -- the shape this started with, mirroring a
#: decision record's ``supersedes`` / ``superseded_by`` pair -- destroyed the
#: very thing the store exists to keep: a hypothesis registered ``confirmed`` on
#: evidence, then later revised, read back as ``superseded`` and the verdict the
#: evidence produced was gone. A decision record can afford that because its
#: status *is* a lifecycle state; a hypothesis's status is an epistemic verdict,
#: and the two do not belong on one field. So ``status`` keeps what the model
#: asserted for the life of the entry, and the presence of this key is what says
#: the entry was later revised.
#:
#: It is a list because revision fans out: A revised by B, and A revised again
#: by C on further evidence, are both real. A scalar recorded only the last and
#: silently dropped the first, leaving the store holding two contradictory views
#: of one graph -- ``revises`` naming both, ``superseded_by`` naming one.
HYPOTHESIS_SUPERSEDED_BY = "superseded_by"


def hypothesis_register(
    claim: str,
    reasoning: str,
    confidence: float,
    workspace_dir: Path | None = None,
    policy_path: Path | None = None,
    *,
    revises: str | None = None,
    status: str | None = None,
) -> str:
    """
    Record a provisional belief: 'I think X is true because Y.'
    Hypotheses can be updated or falsified later as evidence arrives.

    Revision is append-only in the strong sense: a call carrying ``revises=<id>``
    records a *new* entry pointing at the prior one, and the prior entry keeps
    every field it was written with -- ``claim``, ``reasoning``, ``confidence``
    and, importantly, the ``status`` its own evidence produced. It gains one
    key, ``superseded_by``: the list of ids that revised it, oldest first. The
    presence of that key is what says "later revised"; nothing is overwritten,
    so the trail of what was believed, on what evidence, and in what order
    survives intact. Revising one entry twice appends to that list rather than
    replacing it, because two revisions of a belief are both real.

    A ``revises`` id the store no longer holds (FIFO-trimmed, or mistyped) is
    still recorded, and the result says the prior entry was not found.

    ``status`` is the model's own verdict: ``provisional`` (default),
    ``confirmed`` or ``retracted``. A value outside ``HYPOTHESIS_STATUSES`` --
    ``superseded`` included, which is not a status at all -- is refused before
    anything is written, as a ``failed`` result the model can correct.
    ``confidence`` is held to the range the schema advertises for the same
    reason: ``tool_arg_validation`` models ``type`` but neither ``enum`` nor
    ``minimum`` / ``maximum``, so a promise made in the schema has to be kept
    here or it is kept nowhere.

    When ``workspace_dir`` is set the entry is scoped under that workspace's
    ``.mango/memory/``; otherwise the legacy install-root store is used.
    After append the store is FIFO-trimmed to ``agent_memory.max_hypotheses``.
    ``policy_path`` selects which governance policy supplies that bound
    (``None`` keeps the loader default).
    """
    from harness.shared.policy_loader import agent_memory_defaults

    resolved_status = status or HYPOTHESIS_STATUS_PROVISIONAL
    if resolved_status not in HYPOTHESIS_STATUSES:
        allowed = ", ".join(HYPOTHESIS_STATUSES)
        # WARNING, not DEBUG: the model asserted a state the store does not
        # offer and nothing was written. `superseded` lands here too -- it is a
        # structural fact the store records, never a verdict a caller may claim
        # -- so this is also the audit line for an attempt to forge one. The
        # dispatcher grades a `failed` outcome at DEBUG (FAILED is not in
        # `DENIALS`), so without this a model looping on a bad status would be
        # invisible at normal levels on both doors.
        logger.warning(
            "hypothesis rejected: status %r is not one of %s (nothing written)",
            resolved_status,
            allowed,
        )
        return failed(f"Hypothesis not recorded: status {resolved_status!r} is not one of {allowed}.")

    # `isinstance(confidence, bool)` first: `True` satisfies the range check
    # (it equals 1) and would be stored as JSON `true`. The schema door already
    # refuses a boolean for a `number` field, so accepting one here would make
    # the store's contract weaker than the door's for direct callers.
    if isinstance(confidence, bool) or not _CONFIDENCE_MIN <= confidence <= _CONFIDENCE_MAX:
        logger.warning("hypothesis rejected: confidence outside the advertised range (nothing written)")
        return failed(
            f"Hypothesis not recorded: confidence {confidence!r} is outside "
            f"the advertised range {_CONFIDENCE_MIN}-{_CONFIDENCE_MAX}."
        )

    # Normalised here rather than at the door so the store's contract holds for
    # every caller. The dispatcher maps "" -> None, but a direct call can still
    # pass whitespace, and " " is truthy.
    revises_id = revises.strip() if isinstance(revises, str) else revises
    _, hypotheses_file = _ensure_memory_files(workspace_dir)
    entry: dict[str, typing.Any] = {
        "id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "claim": claim,
        "reasoning": reasoning,
        "confidence": confidence,
        "status": resolved_status,
    }
    if revises_id:
        entry["revises"] = revises_id

    max_hypotheses = agent_memory_defaults(policy_path)["max_hypotheses"]
    prior_found = False

    def _mark_superseded(entries: list) -> None:
        """Append this entry's id to every matching prior's successor list.

        Runs inside the store lock (see ``append_locked``), so the read of the
        prior and the write of its pointer cannot straddle a concurrent
        revision and lose one of them.
        """
        nonlocal prior_found
        for prior in entries:
            if isinstance(prior, dict) and prior.get("id") == revises_id:
                successors = prior.get(HYPOTHESIS_SUPERSEDED_BY)
                # Tolerate a scalar written by an older build of this module
                # rather than discarding it: the store outlives the code.
                if isinstance(successors, str):
                    successors = [successors]
                elif not isinstance(successors, list):
                    successors = []
                if entry["id"] not in successors:
                    successors.append(entry["id"])
                prior[HYPOTHESIS_SUPERSEDED_BY] = successors
                prior_found = True

    hypotheses = append_locked(
        hypotheses_file,
        entry,
        max_hypotheses,
        label="hypotheses",
        before_append=_mark_superseded if revises_id else None,
    )

    if revises_id:
        # Ids, statuses and counts only -- never `claim` or `reasoning`, which
        # are model-authored free text and follow the same no-content rule the
        # dispatcher's tool events do (2026 standards audit H6).
        if prior_found:
            logger.info("hypothesis %s supersedes %s (status=%s)", entry["id"], revises_id, resolved_status)
        else:
            # INFO rather than WARNING: a pointer whose target aged out under
            # `agent_memory.max_hypotheses` is retention working as configured,
            # not a fault. Logged because a chain that silently loses its
            # ancestor is otherwise indistinguishable from one that never had one.
            logger.info(
                "hypothesis %s names prior %s, which the store does not hold (trimmed or unknown)",
                entry["id"],
                revises_id,
            )

    # Built before the retention check so a revision under a disabled or
    # exhausted bound still reports whether its pointer resolved. `prior_found`
    # is what the store saw *inside the lock*; the trim that follows may then
    # have dropped that very entry, and the message says so rather than claiming
    # a supersession the reader cannot find on disk.
    revision_note = ""
    if revises_id:
        if not prior_found:
            revision_note = (
                f" Prior entry {revises_id} not found (trimmed or unknown); recorded with the pointer anyway."
            )
        elif any(isinstance(h, dict) and h.get("id") == revises_id for h in hypotheses):
            revision_note = f" Supersedes {revises_id}."
        else:
            revision_note = f" Supersedes {revises_id}, which retention then trimmed; the pointer is kept."

    if max_hypotheses == 0:
        # The revision note above describes a store that still holds something.
        # Under a zero bound nothing does -- not the prior entry, not this one --
        # so the pointer is reported as observed-then-discarded rather than kept.
        zero_note = ""
        if revises_id:
            zero_note = (
                f" Prior entry {revises_id} was {'found' if prior_found else 'not found'}, "
                "but retention is disabled so nothing was kept."
            )
        return (
            f"Hypothesis entry not retained: retention disabled "
            f"(agent_memory.max_hypotheses=0). ID: {entry['id']}.{zero_note}"
        )
    return (
        f"Hypothesis registered successfully. ID: {entry['id']}. Status: {resolved_status}."
        f"{revision_note} Total hypotheses: {len(hypotheses)}"
    )


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
                "Record a belief: 'I think X is true because Y.' Set 'status' on any call: "
                "'provisional' (the default) when the claim is unsettled, or 'confirmed'/'retracted' "
                "when evidence already settles it. "
                "When later evidence bears on a claim you already registered, revise it: call again "
                "with 'revises' set to that entry's ID. That ID is returned in this tool's result and "
                "is the only place you will see it, so keep it. Revise when the new evidence concerns "
                "the SAME claim; register a fresh hypothesis for a different claim. The earlier entry "
                "is kept exactly as written -- including the status its own evidence produced -- and "
                "records this new entry as one that superseded it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "The provisional belief or claim."},
                    "reasoning": {"type": "string", "description": "The logic or evidence supporting the claim."},
                    "confidence": {"type": "number", "description": "Confidence level between 0.0 and 1.0"},
                    "revises": {
                        "type": "string",
                        "description": "ID of an earlier hypothesis this entry revises. Optional.",
                    },
                    "status": {
                        "type": "string",
                        "description": "One of 'provisional' (default), 'confirmed', or 'retracted'. Optional.",
                    },
                },
                "required": ["claim", "reasoning", "confidence"],
                "additionalProperties": False,
            },
        },
    },
]
