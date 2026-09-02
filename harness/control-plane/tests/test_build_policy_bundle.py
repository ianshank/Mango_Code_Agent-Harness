"""Tests for the control-plane bundle builder.

Now wired into `make digest-regen` as the only regenerator of the bundle's
top-level governance/agent policy digests -- the values verify_repository.py
checks (exercised in CI by test_harness.py). It previously had zero coverage
and no invocation anywhere: a regenerator nothing ran, for digests something
verified.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO / "harness" / "control-plane" / "build_policy_bundle.py"
BUNDLE = REPO / "harness" / "control-plane" / "policy-bundle.example.json"

pytestmark = pytest.mark.governance


def _load_module():
    """Load by path: `harness/control-plane` is not an importable package name."""
    spec = importlib.util.spec_from_file_location("build_policy_bundle", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bpb = _load_module()


class TestBuild:
    def test_rebuild_from_the_real_stacks_matches_the_committed_bundle(self):
        """Mirror of the extended `digest-regen` stage: a stale committed bundle
        (including a stale TOP-LEVEL policy digest, which
        regenerate_bundle_digests.py never touches) fails here as well as in CI."""
        bundle = bpb.build({"node": REPO / "harness" / "node", "jvm": REPO / "harness" / "jvm"})
        committed = json.loads(BUNDLE.read_text(encoding="utf-8"))
        assert bundle == committed, (
            "policy-bundle.example.json is stale; run `make digest-regen` and commit"
        )

    def test_top_level_digests_track_the_per_stack_policies(self):
        bundle = bpb.build({"node": REPO / "harness" / "node", "jvm": REPO / "harness" / "jvm"})
        node = REPO / "harness" / "node" / ".governance"
        assert bundle["governance_policy_sha256"] == hashlib.sha256(
            (node / "policy.json").read_bytes()
        ).hexdigest()
        assert bundle["agent_policy_sha256"] == hashlib.sha256(
            (node / "agent-policy.json").read_bytes()
        ).hexdigest()

    def test_missing_protected_file_fails_closed_and_names_it(self, tmp_path: Path):
        """A stack root lacking a protected file must abort, not emit a thin bundle."""
        node = tmp_path / "node"
        shutil.copytree(REPO / "harness" / "node", node, ignore=shutil.ignore_patterns("node_modules"))
        (node / "vitest.config.ts").unlink()
        with pytest.raises(SystemExit) as exc:
            bpb.build({"node": node, "jvm": REPO / "harness" / "jvm"})
        assert "vitest.config.ts" in str(exc.value)

    def test_main_writes_the_bundle_and_is_idempotent(self, tmp_path: Path):
        out = tmp_path / "bundle.json"
        argv = [
            "--node", str(REPO / "harness" / "node"),
            "--jvm", str(REPO / "harness" / "jvm"),
            "--output", str(out),
        ]
        assert bpb.main(argv) == 0
        first = out.read_text(encoding="utf-8")
        assert bpb.main(argv) == 0
        assert out.read_text(encoding="utf-8") == first
        assert first.endswith("}\n") and not first.endswith("\n\n")

    def test_sha_is_the_sha256_of_the_bytes(self, tmp_path: Path):
        target = tmp_path / "f"
        target.write_bytes(b"governance")
        assert bpb.sha(target) == hashlib.sha256(b"governance").hexdigest()
