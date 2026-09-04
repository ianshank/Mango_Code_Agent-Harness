"""Digest the enforcement layer of a workspace, so a verdict can tell whether it
was earned against the files that were there when the loop began.

``VerificationRunner`` earns the verdict by running ``make -f Makefile
test-python`` in the agent's workspace. ``Makefile`` is a protected path, so the
direct door (``write_file``) refuses to change it. The indirect door does not:
a script the agent wrote and then ran with ``python3 forge.py`` -- graded
``test_execute``, an action every role holds -- rewrote ``Makefile`` so the
target was a no-op, and the next verification returned ``VERIFIED`` on a
workspace whose real suite failed (2026 standards audit, B4, reproduced end to
end through the real dispatcher, broker and process backend).

OS isolation of the process backend is the fix; it is a later capability
profile that this repository's CI runners cannot exercise. Until it lands, the
cheapest sound mitigation is to notice: record the digest of every file in the
workspace that ``protected_paths`` names **before the first agent turn**, and
refuse to grade a run in which any of them changed, appeared or vanished. That
does not stop the script from running -- it stops the forged verdict from being
issued, and names the file that was forged.

The set is the policy's own definition of the enforcement layer, read through
the same ``protected_paths`` matcher the CI gate and the write policy use, so
nothing here restates which files matter. The digest is ``write_policy
.policy_digest`` -- sha256 over the exact bytes -- which is the algorithm
``harness/control-plane/build_policy_bundle.py`` and
``regenerate_bundle_digests.py`` pin the bundle with (they carry their own copy
by design: DEC-019 forbids the control plane importing from the governed tree).

Spec: ``docs/reports/2026-STANDARDS-AUDIT.md`` (B4).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from harness.shared.validate_invariants import SKIP_DIR_PARTS, is_protected, load_protected_patterns
from harness.shared.write_policy import DEFAULT_POLICY_PATH, policy_digest

logger = logging.getLogger(__name__)


class EnforcementDigestError(RuntimeError):
    """The enforcement set could not be established. Raised, never swallowed:
    a verdict issued without knowing what it was earned against would be the
    fail-open this module exists to remove."""


def enforcement_digests(workspace: Path, policy_path: Path | None = None) -> dict[str, str]:
    """``{workspace-relative posix path: sha256}`` for every protected file present.

    Walks ``workspace`` once, pruning the directories ``validate_invariants``
    already declares as not first-party (virtualenvs, caches, ``node_modules``,
    ``.git``). Symlinked directories are not followed; a symlinked *file* that
    matches is digested by content, which is what the recipe would read.

    ``policy_path`` names the policy whose ``protected_paths`` define the set;
    it defaults to the harness policy, the floor every supplied policy is
    unioned with. Fails closed on an unreadable policy or an unreadable file.
    """
    root = workspace.resolve()
    try:
        patterns = load_protected_patterns(policy_path or DEFAULT_POLICY_PATH)
    except (Exception, SystemExit) as exc:
        # Fail-closed boundary: `load_protected_patterns` exits for a CLI gate,
        # which here would kill the orchestrator instead of refusing one verdict.
        raise EnforcementDigestError(f"the protected-path policy could not be read: {exc}") from exc

    digests: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIR_PARTS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if not is_protected(rel, patterns):
                continue
            try:
                digests[rel] = policy_digest(path.read_bytes())
            except OSError as exc:
                raise EnforcementDigestError(f"protected file {rel} could not be read: {exc}") from exc
    logger.debug("enforcement digests: %d protected file(s) under %s", len(digests), root)
    return digests


def tampered_files(baseline: dict[str, str], current: dict[str, str]) -> list[str]:
    """Paths whose digest differs between two snapshots, in sorted order.

    A file that appeared is tampering as much as one that changed: a
    ``GNUmakefile`` or ``pytest.ini`` that did not exist at loop start is a
    new input to the recipe that no review saw. A file that vanished is
    reported for the same reason.
    """
    return sorted(
        path
        for path in baseline.keys() | current.keys()
        if baseline.get(path) != current.get(path)
    )


__all__ = ["EnforcementDigestError", "enforcement_digests", "tampered_files"]
