import datetime as dt
import json
from pathlib import Path

import pytest

from harness.shared.validate_agent_policy import main as validate_agent_policy
from harness.shared.validate_governance_docs import main as validate_governance_docs
from harness.shared.validate_policy import main as validate_policy


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    gov = tmp_path / ".governance"
    gov.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    agents = tmp_path / "agents"
    agents.mkdir()

    # Valid agent-policy
    valid_agent = {
        "agents": [
            {"id": "orchestrator", "allowed_actions": ["a", "b"], "human_approval_required_for": ["a"], "delegation_depth": 0},
            {"id": "spec-analyst", "allowed_actions": [], "human_approval_required_for": [], "delegation_depth": 0},
            {"id": "implementer", "allowed_actions": [], "human_approval_required_for": [], "delegation_depth": 0},
            {"id": "test-eval", "allowed_actions": [], "human_approval_required_for": [], "delegation_depth": 0},
            {"id": "security-reviewer", "allowed_actions": [], "human_approval_required_for": [], "delegation_depth": 0},
            {"id": "peer-reviewer", "allowed_actions": [], "human_approval_required_for": [], "delegation_depth": 0},
            {"id": "release-auditor", "allowed_actions": [], "human_approval_required_for": [], "delegation_depth": 0},
        ],
        "default_deny": True,
        "limits": {"max_delegation_depth": 5},
        "high_risk_actions": ["a"],
        "rules": {
            "self_modify_policy": False,
            "secrets_may_not_be_propagated_to_subagents": True,
            "delegation_does_not_transfer_authority": True,
            "every_side_effect_requires_trace_id": True
        }
    }
    (gov / "agent-policy.json").write_text(json.dumps(valid_agent))

    # Valid policy
    valid_policy_doc = {
        "target_contract": "yes",
        "pre_pr_order": "yes",
        "ci_required_targets": ["cov", "lint", "types", "secrets", "specs", "audit", "remotes", "projections", "traceability", "governance"],
        "decision_id_pattern": ".*",
        "agent_defaults": {"deny_unclassified_side_effects": True},
        "protected_paths": [".governance/**", ".github/workflows/**", "Makefile", "scripts/remotes.py", "scripts/verify_zero_skips.py"],
        "charter_version": "1",
        "governance_skill_path": "agents/GOVERNANCE_SKILL.md",
        "skill_max_age_days": 90,
        "external_root_of_trust_required": True
    }
    (gov / "policy.json").write_text(json.dumps(valid_policy_doc))

    # Valid Docs
    (docs / "PROJECT-CHARTER.md").write_text("Charter v1")
    today = dt.date.today().isoformat()
    (agents / "GOVERNANCE_SKILL.md").write_text(f"Reviewed: {today}\n## Decisions since 2026-01-01\nxyz")
    (gov / "decision-log.md").write_text("2026-01-02 | xyz | reason")

    return tmp_path

# --- validate_agent_policy tests ---

def test_agent_policy_valid(temp_workspace):
    """The happy path. Every sibling test asserts a SystemExit; this one is
    what proves those failures come from the specific mutation rather than
    from a fixture the validator would reject outright."""
    policy = temp_workspace / ".governance/agent-policy.json"
    validate_agent_policy(policy)
    # Pin that the fixture really is the shape under test, so a fixture that
    # drifted into something trivially valid cannot quietly weaken the suite.
    assert json.loads(policy.read_text())["agents"], "fixture declares no agents to validate"

def test_agent_policy_missing_roles(temp_workspace):
    p = temp_workspace / ".governance/agent-policy.json"
    d = json.loads(p.read_text())
    d["agents"].pop(0)
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="agent-policy: missing roles"):
        validate_agent_policy(p)

def test_agent_policy_default_deny(temp_workspace):
    p = temp_workspace / ".governance/agent-policy.json"
    d = json.loads(p.read_text())
    d["default_deny"] = False
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="agent-policy: default_deny must be true"):
        validate_agent_policy(p)

def test_agent_policy_missing_high_risk(temp_workspace):
    p = temp_workspace / ".governance/agent-policy.json"
    d = json.loads(p.read_text())
    d["high_risk_actions"] = []
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="agent-policy: high_risk_actions must be declared"):
        validate_agent_policy(p)

def test_agent_policy_delegation_depth(temp_workspace):
    p = temp_workspace / ".governance/agent-policy.json"
    d = json.loads(p.read_text())
    d["agents"][0]["delegation_depth"] = 10
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="agent-policy: orchestrator exceeds delegation depth"):
        validate_agent_policy(p)

def test_agent_policy_allowed_not_list(temp_workspace):
    p = temp_workspace / ".governance/agent-policy.json"
    d = json.loads(p.read_text())
    d["agents"][0]["allowed_actions"] = "all"
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="agent-policy: orchestrator has no allowed_actions"):
        validate_agent_policy(p)

def test_agent_policy_approvals_not_list(temp_workspace):
    p = temp_workspace / ".governance/agent-policy.json"
    d = json.loads(p.read_text())
    d["agents"][0]["human_approval_required_for"] = "none"
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="agent-policy: orchestrator has no human_approval_required_for list"):
        validate_agent_policy(p)

def test_agent_policy_approvals_not_subset(temp_workspace):
    p = temp_workspace / ".governance/agent-policy.json"
    d = json.loads(p.read_text())
    d["agents"][0]["human_approval_required_for"] = ["c"]
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="agent-policy: orchestrator approval action is not allowed to the role"):
        validate_agent_policy(p)

def test_agent_policy_unapproved_high_risk(temp_workspace):
    p = temp_workspace / ".governance/agent-policy.json"
    d = json.loads(p.read_text())
    d["agents"][0]["allowed_actions"] = ["a", "b"]
    d["agents"][0]["human_approval_required_for"] = []
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="agent-policy: orchestrator high-risk actions lack human approval"):
        validate_agent_policy(p)

def test_agent_policy_missing_rule(temp_workspace):
    p = temp_workspace / ".governance/agent-policy.json"
    d = json.loads(p.read_text())
    d["rules"].pop("self_modify_policy")
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="agent-policy: missing rule self_modify_policy"):
        validate_agent_policy(p)

def test_agent_policy_self_modify_true(temp_workspace):
    p = temp_workspace / ".governance/agent-policy.json"
    d = json.loads(p.read_text())
    d["rules"]["self_modify_policy"] = True
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="agent-policy: agents may not self-modify policy"):
        validate_agent_policy(p)

def test_agent_policy_secrets_prop_false(temp_workspace):
    p = temp_workspace / ".governance/agent-policy.json"
    d = json.loads(p.read_text())
    d["rules"]["secrets_may_not_be_propagated_to_subagents"] = False
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="agent-policy: secret propagation must be prohibited"):
        validate_agent_policy(p)

def test_agent_policy_delegation_transfer_false(temp_workspace):
    p = temp_workspace / ".governance/agent-policy.json"
    d = json.loads(p.read_text())
    d["rules"]["delegation_does_not_transfer_authority"] = False
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="agent-policy: delegation must not transfer authority"):
        validate_agent_policy(p)

def test_agent_policy_trace_id_false(temp_workspace):
    p = temp_workspace / ".governance/agent-policy.json"
    d = json.loads(p.read_text())
    d["rules"]["every_side_effect_requires_trace_id"] = False
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="agent-policy: side effects require trace IDs"):
        validate_agent_policy(p)

# --- validate_policy tests ---

def test_policy_valid(temp_workspace):
    """Happy path; see test_agent_policy_valid for why it asserts on the
    fixture as well as on the absence of an exception."""
    policy = temp_workspace / ".governance/policy.json"
    validate_policy(policy)
    assert json.loads(policy.read_text())["target_contract"], "fixture has no target_contract to validate"

def test_policy_missing_key(temp_workspace):
    p = temp_workspace / ".governance/policy.json"
    d = json.loads(p.read_text())
    d.pop("target_contract")
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="policy: missing target_contract"):
        validate_policy(p)

def test_policy_missing_ci(temp_workspace):
    p = temp_workspace / ".governance/policy.json"
    d = json.loads(p.read_text())
    d["ci_required_targets"] = ["lint"]
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="policy: critical CI gates omitted: "):
        validate_policy(p)

def test_policy_missing_protected(temp_workspace):
    p = temp_workspace / ".governance/policy.json"
    d = json.loads(p.read_text())
    d["protected_paths"].pop(0)
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="policy: critical protected path omitted: "):
        validate_policy(p)

def test_policy_no_root_trust(temp_workspace):
    p = temp_workspace / ".governance/policy.json"
    d = json.loads(p.read_text())
    d["external_root_of_trust_required"] = False
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="policy: external root of trust must be required"):
        validate_policy(p)

def test_policy_no_side_effects(temp_workspace):
    p = temp_workspace / ".governance/policy.json"
    d = json.loads(p.read_text())
    d["agent_defaults"]["deny_unclassified_side_effects"] = False
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="policy: unclassified side effects must be denied"):
        validate_policy(p)

# --- validate_governance_docs tests ---

def test_docs_valid(temp_workspace):
    """Happy path; see test_agent_policy_valid for the fixture assertion."""
    validate_governance_docs(temp_workspace)
    assert (temp_workspace / ".governance/policy.json").is_file()
    assert json.loads((temp_workspace / ".governance/policy.json").read_text())["charter_version"]

def test_docs_missing_version(temp_workspace):
    p = temp_workspace / ".governance/policy.json"
    d = json.loads(p.read_text())
    d["charter_version"] = ""
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="policy has no charter_version"):
        validate_governance_docs(temp_workspace)

def test_docs_missing_charter(temp_workspace):
    (temp_workspace / "docs/PROJECT-CHARTER.md").unlink()
    with pytest.raises(SystemExit, match="charter is missing or does not declare"):
        validate_governance_docs(temp_workspace)

def test_docs_missing_skill(temp_workspace):
    (temp_workspace / "agents/GOVERNANCE_SKILL.md").unlink()
    with pytest.raises(SystemExit, match="governance skill missing:"):
        validate_governance_docs(temp_workspace)

def test_docs_missing_reviewed(temp_workspace):
    (temp_workspace / "agents/GOVERNANCE_SKILL.md").write_text("No reviewed date")
    with pytest.raises(SystemExit, match="governance skill has no Reviewed: YYYY-MM-DD"):
        validate_governance_docs(temp_workspace)

def test_docs_future_reviewed(temp_workspace):
    future = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    (temp_workspace / "agents/GOVERNANCE_SKILL.md").write_text(f"Reviewed: {future}\n## Decisions since 2026-01-01\nxyz")
    with pytest.raises(SystemExit, match="governance skill review date is in the future"):
        validate_governance_docs(temp_workspace)

def test_docs_stale_reviewed(temp_workspace):
    past = (dt.date.today() - dt.timedelta(days=91)).isoformat()
    (temp_workspace / "agents/GOVERNANCE_SKILL.md").write_text(f"Reviewed: {past}\n## Decisions since 2026-01-01\nxyz")
    with pytest.raises(SystemExit, match="governance skill review is stale"):
        validate_governance_docs(temp_workspace)

def test_docs_missing_since(temp_workspace):
    today = dt.date.today().isoformat()
    (temp_workspace / "agents/GOVERNANCE_SKILL.md").write_text(f"Reviewed: {today}\nNo decisions section")
    with pytest.raises(SystemExit, match="governance skill lacks Decisions since YYYY-MM-DD section"):
        validate_governance_docs(temp_workspace)

def test_docs_missing_log(temp_workspace):
    (temp_workspace / ".governance/decision-log.md").unlink()
    with pytest.raises(SystemExit, match="decision log missing"):
        validate_governance_docs(temp_workspace)

def test_docs_missing_decision_in_skill(temp_workspace):
    (temp_workspace / ".governance/decision-log.md").write_text("2026-01-02 | missed-id | reason")
    today = dt.date.today().isoformat()
    (temp_workspace / "agents/GOVERNANCE_SKILL.md").write_text(f"Reviewed: {today}\n## Decisions since 2026-01-01\nNot here")
    with pytest.raises(SystemExit, match="governance skill is missing recent decisions: missed-id"):
        validate_governance_docs(temp_workspace)

def test_docs_multiple_failures(temp_workspace):
    (temp_workspace / ".governance/decision-log.md").unlink()
    (temp_workspace / "docs/PROJECT-CHARTER.md").unlink()
    with pytest.raises(SystemExit) as exc_info:
        validate_governance_docs(temp_workspace)
    assert "charter is missing" in str(exc_info.value)
    assert "decision log missing" in str(exc_info.value)
