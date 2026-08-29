"""Cross-file consistency gates for the governance policy family.

An audit traced every key in `harness/shared/governance-policy.json` to the code
that reads it and found three structural risks this suite pins:

1. **The shared policy is a template the per-stack policies instantiate.** Every
   key in `harness/{node,jvm}/.governance/policy.json` also exists in the shared
   file with the same value (`protected_paths` excepted -- the per-stack copies
   deliberately keep the single-stack adopter frame that `validate_policy.py`
   requires). Nothing enforced that superset relation, so a shared-file edit
   could silently orphan the template from its instances.

2. **Several keys are declared but wired to nothing.** Deleting them looks like
   hygiene but destroys declarations other artifacts (specs, the evidence
   subsystem) still reference, and the per-stack digests (root-of-trust +
   bundle) make deletion a rotation-sized change. So they are *classified*, the
   same way `UNENFORCED_IN_ROOT_CI` classifies unenforced coverage thresholds:
   present, with a reviewed reason, and this suite fails when an entry goes
   stale in either direction.

3. **Some values are duplicated across files with no reader comparing them**
   (`decision_id_pattern` x5, `agent_defaults` vs `agent-policy.json`,
   `GITLEAKS_VERSION` x3 with a "bump both together" comment). Each pair is now
   an equality assertion, which is what makes the duplicated key load-bearing:
   editing one copy without the others turns this suite red.

Everything here is read-only over committed files -- no digests move.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import cast

import pytest

REPO = Path(__file__).resolve().parents[3]
SHARED_POLICY = REPO / "harness" / "shared" / "governance-policy.json"
STACK_POLICIES = {
    "node": REPO / "harness" / "node" / ".governance" / "policy.json",
    "jvm": REPO / "harness" / "jvm" / ".governance" / "policy.json",
}
AGENT_POLICIES = {
    "shared": REPO / "harness" / "shared" / "agent-policy.json",
    "node": REPO / "harness" / "node" / ".governance" / "agent-policy.json",
    "jvm": REPO / "harness" / "jvm" / ".governance" / "agent-policy.json",
}
MAKEFILES = {
    "root": REPO / "Makefile",
    "node": REPO / "harness" / "node" / "Makefile",
    "jvm": REPO / "harness" / "jvm" / "Makefile",
}

pytestmark = pytest.mark.governance

# Common keys whose values legitimately differ between the shared template and a
# per-stack instance. Every entry needs a reason; an entry for a key that has
# stopped diverging (or existing) is itself a failure, so the waiver cannot rot.
DIVERGENT_COMMON_KEYS = {
    "protected_paths": (
        "The per-stack copies keep the single-stack adopter frame "
        "(scripts/remotes.py, .github/workflows/ci.yml) that validate_policy.py "
        "hard-requires for the file it actually validates; the shared file "
        "carries this repository's multi-stack frame. Documented at "
        "test_protected_path_liveness.py."
    ),
}

# Keys that are declared in the shared policy but enforced by no code path today.
# Mirrors UNENFORCED_IN_ROOT_CI: presence with a reviewed reason, not silence,
# and never deletion-by-default -- the per-stack mirrors of these keys sit under
# root-of-trust + bundle digests, so removal is a rotation-sized change.
DECLARED_NOT_YET_ENFORCED = {
    "schema_version": (
        "Read by nothing: shadow_planner deliberately versions policy *content* "
        "(sha256), and publish_policy_artifact carries its own "
        "ARTIFACT_SCHEMA_VERSION. Remove from all three policies at the next "
        "root-of-trust rotation."
    ),
    "authority_model": (
        "Prose describing the human/agent authority split; zero readers in code "
        "or tests across all three policy copies. Remove at the next "
        "root-of-trust rotation, or wire into validate_policy.py if the "
        "declaration is to become checkable."
    ),
    "synthesis.lats_quality_threshold": (
        "Declared by the neurosym synthesis spec as the LATS acceptance bar, but "
        "no code reads it and test_neurosym_synthesis.py asserts only "
        "max_repair_cycles/lats_enabled/critique_schema_version/"
        "prohibited_imports. The spec flags its current 0.0 as BLOCKING, so the "
        "value needs a decision before wiring, not silent deletion."
    ),
    "synthesis.seed_task_suite_version": (
        "Declared by the neurosym synthesis spec for seed-suite pinning; zero "
        "readers today. Wiring lands with the synthesis evaluation harness; "
        "until then this entry keeps the declaration from reading as enforced."
    ),
    "synthesis.critique_schema_version": (
        "Pinned but unconsumed -- a different state from its siblings below, which "
        "are unpinned *and* unconsumed. test_neurosym_synthesis.py asserts the value "
        "is exactly \"1.0\", so it cannot drift silently, but no production path "
        "reads it: there is no critique.py and no repair loop (INV-11 is declared "
        "dormant in test_invariant_liveness.py for that reason). DEC-NS-002, which "
        "proposes this exact value, is still marked BLOCKING in a DRAFT openspec "
        "document, so the pin records a proposal rather than a decision. Wiring "
        "lands with openspec Milestone 5."
    ),
    "synthesis.max_repair_cycles": (
        "Same state as critique_schema_version, and grouped with it by CONTRACT.md "
        "as a schema-shape guard. test_neurosym_synthesis.py asserts it is a bounded "
        "positive integer, which constrains the policy value's shape and not any "
        "loop's behaviour -- there is no repair loop to bound, so INV-12 is declared "
        "dormant. Any value in 1..10 passes today; the budget becomes meaningful "
        "only when Milestone 5 builds something that spends it."
    ),
    "agent_defaults.evidence_required_for": (
        "Names the action categories the evidence-manifest subsystem must cover. "
        "harness/shared/governance/evidence_manifest.py is live, but nothing "
        "cross-checks its coverage against this list yet; the cross-check "
        "belongs with the evidence subsystem, not with silent deletion."
    ),
}


def _load(path: Path) -> dict:
    return cast(dict, json.loads(path.read_text(encoding="utf-8")))


def _lookup(policy: dict, dotted: str):
    node = policy
    for part in dotted.split("."):
        assert isinstance(node, dict) and part in node, (
            f"policy path {dotted!r} broke at {part!r}"
        )
        node = node[part]
    return node


class TestSharedPolicyIsTheTemplate:
    """The shared policy must remain a superset of every per-stack instance."""

    @pytest.mark.parametrize("stack", sorted(STACK_POLICIES))
    def test_every_per_stack_key_exists_in_the_shared_policy(self, stack):
        shared = _load(SHARED_POLICY)
        instance = _load(STACK_POLICIES[stack])
        missing = sorted(set(instance) - set(shared))
        assert not missing, (
            f"{stack} policy declares keys the shared template lost: {missing}. "
            "Deleting a shared key while instances still carry it orphans the "
            "template/instance relation."
        )

    @pytest.mark.parametrize("stack", sorted(STACK_POLICIES))
    def test_common_keys_are_value_equal_outside_declared_divergences(self, stack):
        shared = _load(SHARED_POLICY)
        instance = _load(STACK_POLICIES[stack])
        drifted = sorted(
            k
            for k in instance
            if k in shared and k not in DIVERGENT_COMMON_KEYS and shared[k] != instance[k]
        )
        assert not drifted, (
            f"{stack} policy drifted from the shared template on {drifted}; "
            "either fix the drift or declare the key in DIVERGENT_COMMON_KEYS "
            "with a reason."
        )

    def test_declared_divergences_still_diverge(self):
        """A divergence waiver must not outlive the divergence it excuses."""
        shared = _load(SHARED_POLICY)
        for stack, path in STACK_POLICIES.items():
            instance = _load(path)
            for key, reason in DIVERGENT_COMMON_KEYS.items():
                assert len(reason.strip()) > 80, f"DIVERGENT_COMMON_KEYS[{key!r}] needs a real reason"
                assert key in instance, f"{stack}: divergence declared for absent key {key!r}"
                assert shared[key] != instance[key], (
                    f"{stack}: {key!r} no longer diverges from the shared template; "
                    "drop it from DIVERGENT_COMMON_KEYS"
                )

    def test_the_two_stacks_agree_with_each_other(self):
        assert _load(STACK_POLICIES["node"]) == _load(STACK_POLICIES["jvm"]), (
            "node and jvm per-stack policies drifted apart"
        )


class TestDeclaredNotYetEnforced:
    """Unwired keys are classified with reasons, exactly like UNENFORCED_IN_ROOT_CI."""

    @pytest.mark.parametrize("dotted", sorted(DECLARED_NOT_YET_ENFORCED))
    def test_declared_key_still_exists(self, dotted):
        """A classification for a key the policy no longer has is dead weight.

        Asserted against the *parent* object rather than the looked-up value:
        an earlier version bound `sentinel = object()` and checked
        `value is not sentinel`, which cannot fail -- a unique object is
        exactly what a lookup can never return. Membership in the parent is
        the claim being made, and it fails when the key is gone.
        """
        policy = _load(SHARED_POLICY)
        parent_path, _, leaf = dotted.rpartition(".")
        parent = _lookup(policy, parent_path) if parent_path else policy
        assert isinstance(parent, dict), f"policy path {parent_path!r} is not an object"
        assert leaf in parent, (
            f"DECLARED_NOT_YET_ENFORCED classifies {dotted!r}, which the policy no longer has"
        )

    @pytest.mark.parametrize("dotted", sorted(DECLARED_NOT_YET_ENFORCED))
    def test_each_entry_has_a_substantive_reason(self, dotted):
        assert len(DECLARED_NOT_YET_ENFORCED[dotted].strip()) > 80, (
            f"DECLARED_NOT_YET_ENFORCED[{dotted!r}] needs a real reason, not a placeholder"
        )


def _string_literal_from_source(path: Path, name: str) -> str:
    """Extract the string literal in a `NAME = r"..."` module-level assignment.

    AST, not text regex: parsing a raw-string literal that *contains* a regex
    with a regex breaks on incidental reformatting. AST rather than import so
    the pin also holds for a scanner whose import-time state depends on the
    policy file being present.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return cast(str, node.value.value)
    raise AssertionError(f"no `{name} = \"...\"` assignment found in {path}")


class TestDecisionIdPatternIsSingleSourced:
    """All five copies of the decision-ID grammar must stay in lockstep.

    The policies carry the anchored full-match form `^(...)$`. Since the
    policy-single-source change, both scanners LOAD that pattern at runtime
    (converting to the word-boundary search form) and keep only an adopter-path
    FALLBACK literal for repos without a policy file; the lockstep now pins
    those fallbacks to the policy body so the fallback grammar cannot rot.
    """

    SCANNERS = {
        "check_projections.FALLBACK_ID_PATTERN": (
            REPO / "harness" / "shared" / "check_projections.py",
            "FALLBACK_ID_PATTERN",
        ),
        "verify_zero_skips.FALLBACK_ID_PATTERN": (
            REPO / "harness" / "shared" / "governance" / "verify_zero_skips.py",
            "FALLBACK_ID_PATTERN",
        ),
    }

    def _policy_body(self, path: Path) -> str:
        pattern = _load(path)["decision_id_pattern"]
        m = re.fullmatch(r"\^\((.*)\)\$", pattern)
        assert m, f"{path}: decision_id_pattern is not in the anchored `^(...)$` form: {pattern!r}"
        return m.group(1)

    def _scanner_body(self, path: Path, name: str) -> str:
        pattern = _string_literal_from_source(path, name)
        m = re.fullmatch(r"\\b\((.*)\)\\b", pattern)
        assert m, f"{path}: {name} is not in the `\\b(...)\\b` search form: {pattern!r}"
        return m.group(1)

    def test_all_five_copies_share_one_grammar(self):
        bodies = {f"shared:{SHARED_POLICY.name}": self._policy_body(SHARED_POLICY)}
        for stack, path in STACK_POLICIES.items():
            bodies[f"{stack}:{path.name}"] = self._policy_body(path)
        for label, (path, name) in self.SCANNERS.items():
            bodies[label] = self._scanner_body(path, name)
        distinct = set(bodies.values())
        assert len(distinct) == 1, f"decision-ID grammar has drifted between copies: {bodies}"

    def test_the_grammar_accepts_known_decision_ids(self):
        """Guards against the lockstep set drifting to something that matches nothing."""
        body = self._policy_body(SHARED_POLICY)
        for decision_id in ("DEC-004", "RB-12a", "G-CI", "S1.2"):
            assert re.fullmatch(body, decision_id), f"grammar rejects {decision_id}"


class TestAgentDefaultsMirrorAgentPolicy:
    """`agent_defaults` duplicates agent-policy.json with no reader comparing them.

    Two validators read the two files (`validate_policy.py` -> policy.json,
    `validate_agent_policy.py` -> agent-policy.json) and neither cross-references
    the other. This is that cross-reference.
    """

    LIMIT_KEYS = ("max_delegation_depth", "max_parallel_subagents", "max_tool_calls_per_task")

    @pytest.mark.parametrize("stack", sorted(AGENT_POLICIES))
    def test_limits_match(self, stack):
        policy_path = SHARED_POLICY if stack == "shared" else STACK_POLICIES[stack]
        defaults = _load(policy_path)["agent_defaults"]
        limits = _load(AGENT_POLICIES[stack])["limits"]
        for key in self.LIMIT_KEYS:
            assert defaults[key] == limits[key], (
                f"{stack}: agent_defaults.{key}={defaults[key]!r} != "
                f"agent-policy.json limits.{key}={limits[key]!r}"
            )

    @pytest.mark.parametrize("stack", sorted(AGENT_POLICIES))
    def test_human_approval_list_matches_high_risk_actions(self, stack):
        policy_path = SHARED_POLICY if stack == "shared" else STACK_POLICIES[stack]
        approval = _load(policy_path)["agent_defaults"]["human_approval_required"]
        high_risk = _load(AGENT_POLICIES[stack])["high_risk_actions"]
        assert approval == high_risk, (
            f"{stack}: agent_defaults.human_approval_required != "
            f"agent-policy.json high_risk_actions ({approval} vs {high_risk})"
        )


class TestPinnedToolVersions:
    """GITLEAKS_VERSION is triplicated with only a 'bump both together' comment."""

    VERSION_RE = re.compile(r"^GITLEAKS_VERSION \?= (\S+)$", re.MULTILINE)

    def test_gitleaks_version_is_identical_across_all_makefiles(self):
        versions = {}
        for label, path in MAKEFILES.items():
            m = self.VERSION_RE.search(path.read_text(encoding="utf-8"))
            assert m, f"{path}: no `GITLEAKS_VERSION ?=` assignment found"
            versions[label] = m.group(1)
        assert len(set(versions.values())) == 1, (
            f"pinned gitleaks versions drifted: {versions}; bump all together"
        )


class TestFallbackConstantsMirrorPolicy:
    """Built-in fallback constants exist for the adopter path (no policy file),
    but in this repository they must equal the policy values they shadow —
    otherwise the adopter default silently diverges from the governed one.
    (spec: policy-single-source)"""

    def test_validate_invariants_size_budget(self):
        from harness.shared import validate_invariants

        assert validate_invariants.SIZE_BUDGET_LINES == _load(SHARED_POLICY)["limits"]["size_budget_lines"]

    def test_check_dedup_max_shim_lines(self):
        from harness.shared import check_dedup

        assert check_dedup.DEFAULT_MAX_SHIM_LINES == _load(SHARED_POLICY)["dedup"]["max_shim_lines"]

    def test_policy_loader_orchestrator_fallbacks_mirror_policy(self):
        """Loader defaults (used when no policy exists) == this repo's policy values."""
        from harness.shared import policy_loader

        missing = REPO / "does-not-exist.json"
        assert policy_loader.orchestrator_defaults(missing) == _load(SHARED_POLICY)["orchestrator"]

    def test_policy_loader_nemotron_fallbacks_mirror_policy(self):
        from harness.shared import policy_loader

        missing = REPO / "does-not-exist.json"
        assert policy_loader.nemotron_defaults(missing) == _load(SHARED_POLICY)["nemotron"]

    def test_policy_loader_tool_budget_fallback_mirrors_policy(self):
        from harness.shared import policy_loader

        missing = REPO / "does-not-exist.json"
        assert (
            policy_loader.max_tool_calls_per_task(missing)
            == _load(SHARED_POLICY)["agent_defaults"]["max_tool_calls_per_task"]
        )
