"""Publish the governance policy as a versioned, digest-pinned artifact.

Requirement Citations (docs/specs/mangomas-integration-core.md):
- R-MMI-8: build pins sha256 + byte size per policy file; policy_version is a
  content digest of governance-policy.json (not its format schema_version)
- R-MMI-9: check mode fails closed (DENY) on any mismatch or malformed input
- R-MMI-10: attestation reuses EvidenceBuilder and transitively covers the
  whole artifact via a canonical core-digest snapshot
- C-MMI-6: requesting attestation without a resolvable key DENYs

Import contract: the module top is stdlib-only so tests can import it without
side effects; ``harness.shared`` imports happen inside functions (with a
sys.path bootstrap for direct ``python harness/control-plane/...`` execution,
where the repo root is not on sys.path). Unlike its siblings in this
directory, argparse runs only under ``main()``.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import typing
from datetime import datetime, timezone
from pathlib import Path

ARTIFACT_SCHEMA_VERSION = "1.0.0"
ARTIFACT_ID = "governance-policy"
POLICY_SOURCE = "harness/shared/governance-policy.json"
POLICY_FILES: tuple[str, ...] = (
    POLICY_SOURCE,
    "harness/shared/agent-policy.json",
)
POLICY_VERSION_HEX_LEN = 16
SHA256_HEX_LEN = 64
_TOOL = "publish_policy_artifact"


def _repo_root_default() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _bootstrap_imports() -> typing.Any:
    """Make ``harness.shared`` importable under direct script execution and
    return the EvidenceBuilder class (function-local to keep import safety)."""
    root = _repo_root_default()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from harness.shared.governance.evidence_manifest import EvidenceBuilder

    return EvidenceBuilder


def _deny(reason: str) -> typing.NoReturn:
    raise SystemExit(f"{_TOOL}: DENY: {reason}")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_core_digest(artifact: dict[str, typing.Any]) -> str:
    """Digest of the artifact minus its attestation, in canonical JSON."""
    core = {k: v for k, v in artifact.items() if k != "attestation"}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode("utf-8")).hexdigest()


def _policy_identity(repo_root: Path) -> tuple[str, str]:
    """(policy_id, content-digest policy_version) from the governance policy."""
    policy_path = repo_root / POLICY_SOURCE
    if not policy_path.is_file():
        _deny(f"missing policy source {POLICY_SOURCE}")
    raw = policy_path.read_bytes()
    try:
        policy_id = str(json.loads(raw.decode("utf-8")).get("policy_id", "unknown"))
    except (ValueError, UnicodeDecodeError):
        _deny(f"unparseable policy source {POLICY_SOURCE}")
    return policy_id, hashlib.sha256(raw).hexdigest()[:POLICY_VERSION_HEX_LEN]


def build_artifact(
    repo_root: Path,
    *,
    attest: bool = False,
    signing_key: str | None = None,
) -> dict[str, typing.Any]:
    """Build the versioned artifact (R-MMI-8), optionally attested (R-MMI-10)."""
    policy_id, policy_version = _policy_identity(repo_root)
    files: dict[str, dict[str, typing.Any]] = {}
    for rel in POLICY_FILES:
        path = repo_root / rel
        if not path.is_file():
            _deny(f"missing policy file {rel}")
        raw = path.read_bytes()
        files[rel] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    artifact: dict[str, typing.Any] = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_id": ARTIFACT_ID,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "attestation": None,
    }

    if attest:
        evidence_builder_cls = _bootstrap_imports()
        builder = evidence_builder_cls(project_root=repo_root, signing_key=signing_key)
        for rel, meta in files.items():
            builder.add_policy_snapshot(rel, policy_version, meta["sha256"])
        # Final snapshot binds the whole artifact core, so the HMAC transitively
        # covers schema_version, identity, and every file digest (R-MMI-10).
        builder.add_policy_snapshot(ARTIFACT_ID, ARTIFACT_SCHEMA_VERSION, _canonical_core_digest(artifact))
        try:
            artifact["attestation"] = builder.export()
        except ValueError as exc:
            _deny(str(exc))  # C-MMI-6: no key -> DENY, never silent null
    return artifact


def check_artifact(repo_root: Path, artifact: dict[str, typing.Any]) -> None:
    """Fail-closed verification of the working tree against an artifact (R-MMI-9)."""
    if not isinstance(artifact, dict):
        _deny("artifact is not a JSON object")
    if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        _deny(
            f"unknown artifact schema_version {artifact.get('schema_version')!r}; "
            f"accepted: {ARTIFACT_SCHEMA_VERSION}"
        )
    files = artifact.get("files")
    if not isinstance(files, dict) or not files:
        _deny("artifact carries no file manifest")
    for rel, meta in files.items():
        expected = meta.get("sha256", "") if isinstance(meta, dict) else ""
        if len(expected) != SHA256_HEX_LEN:
            _deny(f"malformed digest for {rel}")
        path = repo_root / rel
        if not path.is_file():
            _deny(f"missing file {rel}")
        actual = digest(path)
        if actual != expected:
            _deny(f"digest mismatch for {rel}: expected {expected}, found {actual}")


def verify_attestation(
    artifact: dict[str, typing.Any],
    signing_key: str | None = None,
) -> bool:
    """Verify the HMAC, the core-digest binding, and the file cross-checks."""
    import os

    attestation = artifact.get("attestation")
    if not isinstance(attestation, dict) or "_signature" not in attestation:
        return False
    key_str = signing_key or os.environ.get("AGENT_EVIDENCE_KEY")
    if not key_str:
        return False
    unsigned = {k: v for k, v in attestation.items() if k != "_signature"}
    expected = hmac.new(
        key_str.encode("utf-8"),
        json.dumps(unsigned, sort_keys=True).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, str(attestation["_signature"])):
        return False

    snapshots = {s.get("policy_id"): s for s in unsigned.get("policies", []) if isinstance(s, dict)}
    core_snapshot = snapshots.get(ARTIFACT_ID)
    if core_snapshot is None or core_snapshot.get("content_hash") != _canonical_core_digest(artifact):
        return False
    files = artifact.get("files")
    if not isinstance(files, dict):
        return False
    for rel, meta in files.items():
        snap = snapshots.get(rel)
        if snap is None or snap.get("content_hash") != (meta or {}).get("sha256"):
            return False
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog=_TOOL, description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=_repo_root_default())
    sub = parser.add_subparsers(dest="command", required=True)

    build_p = sub.add_parser("build", help="build a policy artifact")
    build_p.add_argument("--output", type=Path, required=True)
    build_p.add_argument(
        "--attest",
        action="store_true",
        help="sign via EvidenceBuilder (key from AGENT_EVIDENCE_KEY)",
    )

    check_p = sub.add_parser("check", help="verify the working tree against an artifact")
    check_p.add_argument("--artifact", type=Path, required=True)
    check_p.add_argument("--verify-attestation", action="store_true")

    args = parser.parse_args(argv)

    _bootstrap_imports()  # ensure repo root is on sys.path for the import below
    from harness.shared.json_logging import setup_json_logging

    setup_json_logging()
    root = args.repo_root

    if args.command == "build":
        artifact = build_artifact(root, attest=args.attest)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
        print(f"{_TOOL}: built {args.output} (policy_version {artifact['policy_version']})")
    else:
        try:
            artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _deny(f"unreadable artifact {args.artifact}: {exc}")
        check_artifact(root, artifact)
        if args.verify_attestation and not verify_attestation(artifact):
            _deny("attestation verification failed")
        print(f"{_TOOL}: passed")


if __name__ == "__main__":
    main()
