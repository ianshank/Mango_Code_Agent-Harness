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

import hashlib
import json
import logging
import os
import posixpath
import re
import warnings
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from harness.shared.validate_invariants import is_protected, load_protected_patterns

logger = logging.getLogger(__name__)

#: Resolved next to this module so the policy travels with the installed harness
#: rather than being read out of whatever tree the agent is working in.
DEFAULT_POLICY_PATH = Path(__file__).resolve().parent / "governance-policy.json"

#: Names the policy in force for this process. A policy can therefore be
#: *supplied* without adding a CLI or HTTP surface that accepts a target
#: repository, which C-PPP-1 rejects.
#:
#: Supplying one cannot widen what an agent may write. A supplied policy is
#: unioned with the harness policy rather than substituted for it (R-PPP-1), and
#: it is denied outright unless a digest record held outside the tree it governs
#: pins it (R-PPP-3). Reading a policy out of the governed tree without those two
#: constraints would let a tree an agent can write to widen the policy that
#: governs writes to it, which is the INV-6 inversion this module exists to
#: refuse.
WRITE_POLICY_PATH_ENV = "MANGO_WRITE_POLICY_PATH"

#: Names the digest record. Defaults next to this module -- inside the installed
#: harness, never inside the tree being governed.
POLICY_PIN_RECORD_ENV = "MANGO_POLICY_PIN_RECORD"

#: Resolved next to this module for the same reason ``DEFAULT_POLICY_PATH`` is:
#: the anchor for a supplied policy has to travel with the harness, because a
#: record stored in the tree it governs makes that tree its own root of trust.
DEFAULT_PIN_RECORD_PATH = Path(__file__).resolve().parent / "supplied-policy-pins.json"

#: Keys through which a supplied policy could try to *take away* a harness
#: denial. None of them is honoured -- the union already makes removal
#: inoperative -- but each one found is reported, so a removal attempt is a
#: recorded event rather than a silent no-op (R-PPP-1, AC-PPP-1).
REMOVAL_DIRECTIVE_KEYS = (
    "protected_paths_removed",
    "protected_paths_disabled",
    "protected_paths_override",
)

#: Fillers used to turn a glob into concrete paths so two patterns' reach can be
#: compared. Two of them, because one filler can match by coincidence.
_PROBE_FILLERS = (("aa", "bb"), ("cc", "dd"))

#: Denied regardless of ``protected_paths``, matched as a whole **path segment**
#: rather than a prefix. Git's own directory is invisible to
#: ``validate_invariants``: it enumerates staged, tracked-modified and untracked
#: files, and ``git ls-files``/``git diff`` never report anything under ``.git``.
#: A hook written there, or a ``core.fsmonitor`` entry in ``.git/config``, runs on
#: the host at the next commit or index refresh with no gate able to see it.
#:
#: Segment matching rather than prefix matching because a prefix check allows
#: ``sub/.git/hooks/pre-commit`` -- a nested repository or submodule is still a
#: git directory, and writing a hook into one is the same escape one level down.
#: It must also not catch ``.gitignore`` or ``.gitleaks.toml``, which share the
#: prefix but are ordinary files; both are pinned by tests.
ALWAYS_DENIED_SEGMENTS = (".git",)

#: The credential-filename alternation, unanchored, so each caller composes the
#: boundaries its own input needs: this module and ``read_policy`` anchor it to a
#: whole path segment, while ``command_actions`` wraps it in
#: ``(?:^|[\s/])...(?:\s|$)`` to find it inside a command string. One alternation,
#: three anchorings -- not three patterns.
#:
#: It lives here, on the write side, because ``read_policy`` already imports
#: ``ALWAYS_DENIED_SEGMENTS`` from this module and the reverse edge would be a
#: cycle. ``read_policy`` re-exports both names, so its published surface is
#: unchanged.
CREDENTIAL_FILENAME_ALTERNATION = r"\.env(?:\.[\w-]+)?|\.netrc|\.npmrc|\.pypirc|id_[rd]sa|[\w.-]+\.pem"

#: Anchored to a whole path segment. Matching a *segment* rather than searching
#: the string keeps ``prod.pem.txt`` and ``notenv`` from reading as credentials
#: while still catching ``secrets/id_rsa``. Case-insensitive: a case-sensitive
#: match let ``.ENV``, ``ID_RSA`` and ``SECRETS.PEM`` -- valid names on the
#: case-preserving filesystems this harness targets -- through untouched.
CREDENTIAL_FILENAME_PATTERN = re.compile(rf"^(?:{CREDENTIAL_FILENAME_ALTERNATION})$", re.IGNORECASE)

#: Placeholder files that share a credential's name and carry none of its bytes.
#: ``.env.example`` is tracked in this repository, ``.gitleaks.toml`` already
#: declares ``.*\.example.*`` non-secret, and an agent asked to document
#: configuration has to be able to write one. Denying them was a regression
#: introduced with the write-side credential rule, not a property of it:
#: ``.env.production`` still matches, because ``production`` is not a placeholder.
CREDENTIAL_PLACEHOLDER_SUFFIXES = ("example", "sample", "template", "dist", "defaults")

_CREDENTIAL_PLACEHOLDER = re.compile(rf"\.(?:{'|'.join(CREDENTIAL_PLACEHOLDER_SUFFIXES)})$", re.IGNORECASE)


def is_credential_filename(segment: str) -> bool:
    """Whether one path segment names a credential-bearing file.

    The single decision every door asks, so the placeholder carve-out and the
    trailing-character normalisation cannot be applied by one caller and
    forgotten by another. A trailing dot or space is stripped first: Win32
    removes them when opening a file, so ``.env `` and ``.env.`` name ``.env``
    there while matching the anchored pattern nowhere.
    """
    candidate = segment.rstrip(" .") or segment
    if _CREDENTIAL_PLACEHOLDER.search(candidate):
        return False
    return bool(CREDENTIAL_FILENAME_PATTERN.match(candidate))


#: The pre-segment-matching name. No first-party caller imports it; it is served
#: through ``__getattr__`` below with a DeprecationWarning for one minor release
#: (tech-debt-hardening-plan R-TDH-17, C-TDH-2) and removed after that.
_ALWAYS_DENIED_PREFIXES = tuple(f"{segment}/" for segment in ALWAYS_DENIED_SEGMENTS)

_DEPRECATED_NAMES = {
    "ALWAYS_DENIED_PREFIXES": (
        _ALWAYS_DENIED_PREFIXES,
        "ALWAYS_DENIED_PREFIXES is deprecated; the gate matches ALWAYS_DENIED_SEGMENTS, use that",
    ),
}


def __getattr__(name: str) -> object:
    """PEP 562: deprecated module names warn on first use instead of vanishing."""
    if name in _DEPRECATED_NAMES:
        value, message = _DEPRECATED_NAMES[name]
        warnings.warn(message, DeprecationWarning, stacklevel=2)
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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


def active_policy_path() -> Path:
    """Return the write policy in force for this process.

    Call sites pass this explicitly rather than letting ``write_denial_reason``
    default: a parameter that no caller supplies is a parameter that is never
    exercised outside tests, which is exactly how the portability defect stayed
    invisible (R-PPP-4).
    """
    override = os.environ.get(WRITE_POLICY_PATH_ENV, "").strip()
    return Path(override).expanduser() if override else DEFAULT_POLICY_PATH


def pin_record_path(pin_path: Path | None = None) -> Path:
    """Return where the digest record for a supplied policy is read from."""
    if pin_path is not None:
        return pin_path
    override = os.environ.get(POLICY_PIN_RECORD_ENV, "").strip()
    return Path(override).expanduser() if override else DEFAULT_PIN_RECORD_PATH


def policy_digest(raw: bytes) -> str:
    """The digest a policy is pinned by: sha256 over its exact bytes."""
    return hashlib.sha256(raw).hexdigest()


def pin_key(policy_path: Path) -> str:
    """The key a supplied policy is recorded under, so the record and the reader
    cannot disagree about the spelling of a path."""
    return policy_path.resolve().as_posix()


def _probe_paths(pattern: str) -> list[str]:
    """Concrete paths ``pattern`` matches, used to compare two patterns' reach.

    ``fnmatch`` offers no subset relation between two globs, so reach is compared
    on probes instead. This is a heuristic and is used only to *report*; nothing
    is permitted or denied on its result.
    """
    return [
        pattern.replace("**", f"{first}/{second}").replace("*", first).replace("?", second[0])
        for first, second in _PROBE_FILLERS
    ]


def _narrows(candidate: str, harness_pattern: str) -> bool:
    """True when ``candidate`` reaches strictly inside ``harness_pattern``'s reach.

    ``is_protected`` is the matcher, not a second copy of ``fnmatch``: two
    matchers would be two behaviours, and the reported finding has to be about
    the semantics the gate actually enforces.
    """
    if candidate == harness_pattern:
        return False
    if not all(is_protected(probe, [harness_pattern]) for probe in _probe_paths(candidate)):
        return False
    return any(not is_protected(probe, [candidate]) for probe in _probe_paths(harness_pattern))


def merge_protected_patterns(
    harness_patterns: list[str], supplied_policy: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    """Union a supplied pattern set into the harness one and report the attempts
    the union made inoperative.

    The merge has a direction. Harness denials are the floor: a supplied policy
    may add a pattern and may never remove, disable or narrow one (R-PPP-1).
    Substitution was rejected in DEC-PPP-001 -- it converts a silent no-match
    failure into a self-modification failure, which is worse, because the tree
    being governed would be the tree supplying the constraint.

    Returns ``(merged_patterns, findings)``. ``findings`` never affects the
    merged set; it exists so a removal attempt is reported rather than silently
    honoured or silently dropped.
    """
    findings: list[str] = []
    additions: list[str] = []

    for entry in supplied_policy.get("protected_paths", []) or []:
        if not isinstance(entry, str):
            findings.append(f"supplied protected_paths entry {entry!r} is not a string and was ignored")
            continue
        if entry.startswith("!"):
            findings.append(
                f"supplied policy negates {entry[1:]!r}; harness denials are a floor, so the "
                "negation is inoperative and the pattern still applies"
            )
            continue
        additions.append(entry)

    for key in REMOVAL_DIRECTIVE_KEYS:
        for entry in supplied_policy.get(key, []) or []:
            findings.append(
                f"supplied policy lists {entry!r} under {key!r}; a supplied policy may only add "
                "denials, so the entry is inoperative and every harness pattern still applies"
            )

    for harness_pattern in harness_patterns:
        if harness_pattern in additions:
            continue
        for addition in additions:
            if _narrows(addition, harness_pattern):
                findings.append(
                    f"supplied pattern {addition!r} reaches inside harness pattern "
                    f"{harness_pattern!r}; both are enforced and the harness pattern is unchanged"
                )

    # `dict.fromkeys` de-duplicates while keeping the harness patterns first, so
    # the merged list reads as "the floor, then what was added to it".
    merged = list(dict.fromkeys([*harness_patterns, *additions]))
    return merged, findings


def pin_denial_reason(policy_path: Path, raw: bytes, pin_path: Path | None = None) -> str | None:
    """Return why a supplied policy is not trusted, or ``None`` when it is.

    Three ways to fail, all denials rather than warnings (R-PPP-3):

    * the record lives inside the tree the policy governs, which would make that
      tree its own root of trust and is the INV-6 inversion;
    * no record exists, or it names no digest for this policy -- a missing record
      is never a default-allow, because "unpinned" and "trusted" would then be
      the same state;
    * the digest recorded and the digest of the bytes actually loaded differ.
    """
    record = pin_record_path(pin_path)
    policy = policy_path.resolve()
    governed_tree = policy.parent

    if record.resolve().is_relative_to(governed_tree):
        return (
            f"the digest record {record} lies inside {governed_tree}, the tree the supplied policy "
            "governs; a tree may not be its own root of trust, so the policy is denied"
        )
    # Absence is told from unusability by the errno, not by ``is_file()``: that
    # predicate answers False for an absent path, for a directory left by a
    # container mount whose source is missing, and for a present-but-
    # inaccessible file whose OSError it swallows. Both branches here deny, so
    # nothing fails open either way -- but the operator is told which happened,
    # and the shape ``test_policy_path_fail_closed`` bans is not reintroduced.
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
        pinned = data["pinned_policies"]
    except FileNotFoundError:
        return (
            f"the supplied policy {policy} has no digest record at {record}; an unpinned policy is "
            "denied rather than defaulting to the harness set"
        )
    except Exception as exc:  # noqa: BLE001 - an unreadable record must deny, with the reason
        return f"the digest record {record} could not be read, so the supplied policy is denied: {exc}"

    expected = pinned.get(pin_key(policy_path)) if isinstance(pinned, Mapping) else None
    if not isinstance(expected, str) or not expected.strip():
        return (
            f"the digest record {record} pins no digest for the supplied policy {policy}; an "
            "unpinned policy is denied rather than defaulting to the harness set"
        )

    actual = policy_digest(raw)
    if actual.lower() != expected.strip().lower():
        return (
            f"digest mismatch for the supplied policy {policy}: it hashes to {actual}, but {record} "
            f"pins it to {expected.strip()}"
        )
    return None


def _load_supplied_policy(policy_path: Path) -> tuple[bytes, Mapping[str, Any]]:
    """Read a supplied policy's exact bytes and its parsed object.

    The bytes are what the digest is taken over, so they are read once and the
    parse is made from the same read: hashing one read and parsing another is a
    time-of-check/time-of-use gap in the pin itself.
    """
    raw = policy_path.read_bytes()
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, Mapping):
        raise ValueError(f"{policy_path} is not a JSON object")
    return raw, parsed


def write_denial_reason(relpath: str, policy_path: Path | None = None, pin_path: Path | None = None) -> str | None:
    """Return why ``relpath`` may not be written, or ``None`` when it may.

    Fails closed: a policy that cannot be read denies the write. The alternative
    -- defaulting to the built-in pattern list, or to allowing -- is the
    inversion this repository has already had to fix in three separate gates,
    where an unreadable policy silently relaxed the control it configured.

    ``policy_path`` names the policy in force. When it is the harness policy the
    behaviour is exactly what it was. When it is anything else the policy is
    *supplied*: it is pinned by digest against a record outside the tree it
    governs (R-PPP-3) and then unioned with the harness policy, which stays the
    floor (R-PPP-1). The always-denied segments below are decided before any
    policy is read at all and are outside the merge entirely (R-PPP-2).
    """
    candidate = _normalise(relpath)
    segments = candidate.split("/")

    # Defence in depth. The orchestrator rejects both of these before calling
    # here, via `is_relative_to(workspace)`; repeating the check keeps this
    # function safe for any other caller, because a helper that only holds when
    # its caller already checked is a helper waiting to be misused.
    if PurePosixPath(candidate).is_absolute():
        return f"{candidate} is an absolute path, and a write target must be workspace-relative"
    if ".." in segments:
        return f"{candidate} climbs out of the workspace"

    for denied in ALWAYS_DENIED_SEGMENTS:
        if denied in segments:
            return f"{candidate} is inside a {denied} directory, which no agent write may target"

    # A credential file is denied on the way *in* as well as on the way out.
    # `read_policy` has refused to read `.env` since it shipped, and the write
    # side did not refuse to write one: `protected_paths` names control-surface
    # files, and `.env` is deliberately untracked, so it matched nothing.
    #
    # That asymmetry was a key-exfiltration path rather than an untidiness.
    # `nemotron_bridge.resolve_environment` reads `NVIDIA_BASE_URL` from the
    # repository-root `.env` whenever the process environment does not supply it,
    # and the API server's workspace is that root -- so a single
    # `apply_patch(".env", ...)` redirected the next `complete_chat` to a host of
    # the model's choosing, with the real bearer token attached. Writing a
    # credential file is the `secret_access` action either way, and no role holds
    # it. Decided before any policy is read, like the segments above.
    for segment in segments:
        if is_credential_filename(segment):
            return (
                f"{candidate} names a credential-bearing file; writing it is the "
                "secret_access action, which no agent role holds"
            )

    try:
        patterns = load_protected_patterns(DEFAULT_POLICY_PATH)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - fail-closed boundary, see below
        # An unreadable policy must deny. Falling back to a built-in list would let
        # a malformed policy widen what an agent may write, which is the failure
        # mode this module exists to prevent.
        #
        # SystemExit is listed explicitly because it is not an Exception:
        # load_protected_patterns fails closed by calling sys.exit(1), which is
        # right for a CLI gate and fatal here -- an unreadable policy would kill
        # the agent process mid-run instead of refusing one tool call.
        return f"the write policy could not be read, so the write is denied: {exc}"

    if policy_path is not None and policy_path.resolve() != DEFAULT_POLICY_PATH:
        try:
            raw, supplied_policy = _load_supplied_policy(policy_path)
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - same fail-closed boundary as above
            return f"the write policy could not be read, so the write is denied: {exc}"

        pin_denial = pin_denial_reason(policy_path, raw, pin_path)
        if pin_denial is not None:
            return f"the supplied write policy is not trusted, so the write is denied: {pin_denial}"

        patterns, findings = merge_protected_patterns(patterns, supplied_policy)
        for finding in findings:
            # Reported, not obeyed. The union has already made each of these
            # inoperative; logging is what keeps the attempt from being silent.
            logger.warning("supplied write policy %s: %s", policy_path, finding)

    if is_protected(candidate, patterns):
        return (
            f"{candidate} matches a protected path; changing it requires a reviewed "
            "change with the infra-reviewed attestation, not an agent write"
        )
    return None
