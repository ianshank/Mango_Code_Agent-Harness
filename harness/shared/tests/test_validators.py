from __future__ import annotations

import contextlib
import hashlib
import json
import runpy
import subprocess
import sys
from io import StringIO
from pathlib import Path
from typing import Protocol

import pytest

from harness.shared.tests._helpers import utc_today


class RunScript(Protocol):
    """The runner the ``run_script`` fixture hands each test."""

    def __call__(
        self, project_root: Path, cwd: Path, script_name: str, args: list[str] | None = None
    ) -> subprocess.CompletedProcess: ...


@pytest.fixture
def run_script(monkeypatch: pytest.MonkeyPatch) -> RunScript:
    """Execute a governance CLI script in-process via runpy for coverage tracking.

    The working directory and ``sys.argv`` are changed through ``monkeypatch``
    rather than ``os.chdir``/assignment inside a ``try``/``finally``: pytest
    unwinds a monkeypatch at teardown whatever the test did, and the restore is
    scoped to the test rather than to one call, which is what a randomised or
    parallel run needs -- a chdir left behind moves every later test in the
    process (audit H8).
    """

    def _run(
        project_root: Path,
        cwd: Path,
        script_name: str,
        args: list[str] | None = None,
    ) -> subprocess.CompletedProcess:
        with monkeypatch.context() as scope:
            scope.chdir(cwd)
            scope.setattr(sys, "argv", [script_name] + (args or []))
            script = project_root / "harness" / "shared" / script_name

            stdout = StringIO()
            stderr = StringIO()
            returncode = 0

            try:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    runpy.run_path(str(script), run_name="__main__")
            except SystemExit as e:
                if isinstance(e.code, int):
                    returncode = e.code
                elif e.code is None:
                    returncode = 0
                else:
                    returncode = 1
                    stderr.write(str(e.code))
            except Exception as e:  # noqa: BLE001 — intentional catch-all for arbitrary script failures
                returncode = 1
                stderr.write(str(e))

            return subprocess.CompletedProcess(
                args=sys.argv,
                returncode=returncode,
                stdout=stdout.getvalue(),
                stderr=stderr.getvalue(),
            )

    return _run


@pytest.fixture
def mock_repo(tmp_path: Path):
    gov = tmp_path / ".governance"
    gov.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    agents = tmp_path / "agents"
    agents.mkdir()
    gh = tmp_path / ".github" / "workflows"
    gh.mkdir(parents=True)

    # src
    src = tmp_path / "src"
    src.mkdir()
    # tests
    tests = tmp_path / "tests"
    tests.mkdir()

    # specs
    specs = docs / "specs"
    specs.mkdir()

    # We must make source and projection identical for check_projections.py
    # and contain R-123 for check_traceability.py
    content = "R-123\n"
    (src / "test.py").write_text(content)
    (tests / "test.py").write_text(content)
    (specs / "test.md").write_text(content)

    # policy.json
    policy_dict = {
        "charter_version": "1.0",
        "governance_skill_path": "agents/GOVERNANCE_SKILL.md",
        "skill_max_age_days": 90,
        "agents": ["verifier"],
        "target_contract": (
            "install format lint types test cov secrets specs"
            " audit remotes projections traceability governance"
            " guard-probe pre-pr clean"
        ),
        "pre_pr_order": "foo",
        "ci_required_targets": [
            "cov",
            "lint",
            "types",
            "secrets",
            "specs",
            "audit",
            "remotes",
            "projections",
            "traceability",
            "governance",
        ],
        "decision_id_pattern": "^DEC-\\d+$",
        "agent_defaults": {"deny_unclassified_side_effects": True},
        "protected_paths": [
            ".governance/**",
            ".github/workflows/**",
            "Makefile",
            "scripts/remotes.py",
            "scripts/verify_zero_skips.py",
        ],
        "external_root_of_trust_required": True,
    }
    policy_str = json.dumps(policy_dict)
    policy_path = gov / "policy.json"
    policy_path.write_text(policy_str)

    # agent-policy.json
    roles = [
        "implementer",
        "orchestrator",
        "peer-reviewer",
        "release-auditor",
        "security-reviewer",
        "spec-analyst",
        "test-eval",
    ]
    agent_list = [
        {"id": r, "delegation_depth": 1, "allowed_actions": ["foo"], "human_approval_required_for": ["foo"]}
        for r in [*roles, "verifier"]
    ]

    (gov / "agent-policy.json").write_text(
        json.dumps(
            {
                "agents": agent_list,
                "default_deny": True,
                "high_risk_actions": ["foo"],
                "limits": {"max_delegation_depth": 2},
                "rules": {
                    "self_modify_policy": False,
                    "secrets_may_not_be_propagated_to_subagents": True,
                    "delegation_does_not_transfer_authority": True,
                    "every_side_effect_requires_trace_id": True,
                },
            }
        )
    )

    # traceability.json
    (gov / "traceability.json").write_text(
        json.dumps(
            {
                "spec_globs": ["docs/specs/*.md"],
                "implementation_globs": ["src/*.py"],
                "test_globs": ["tests/*.py"],
            }
        )
    )

    # projections.json
    (gov / "projections.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "decision_id": "DEC-123",
                "mappings": [{"source": "src/test.py", "projection": "docs/specs/test.md"}],
            }
        )
    )

    # decision-log.md
    (gov / "decision-log.md").write_text("2020-01-01 | DEC-123 | foo\n")

    # allowed-remotes.txt
    (gov / "allowed-remotes.txt").write_text("github.com/org/repo\n")

    # root-of-trust.json
    digest = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    (gov / "root-of-trust.json").write_text(
        json.dumps(
            {
                "external_policy_ref": "https://example.com/policy",
                "policy_sha256": digest,
            }
        )
    )

    # PROJECT-CHARTER.md
    (docs / "PROJECT-CHARTER.md").write_text("# Charter v1.0\n")

    # GOVERNANCE_SKILL.md
    today = utc_today().isoformat()
    (agents / "GOVERNANCE_SKILL.md").write_text(f"Reviewed: {today}\n## Decisions since 2020-01-01\nDEC-123")

    return tmp_path


# --- validate_governance_docs.py ---
def test_valid_project_passes_gov_docs(run_script: RunScript, project_root: Path, mock_repo: Path):
    res = run_script(project_root, mock_repo, "validate_governance_docs.py")
    assert res.returncode == 0


def test_missing_doc_fails_gov_docs(run_script: RunScript, project_root: Path, mock_repo: Path):
    (mock_repo / "docs" / "PROJECT-CHARTER.md").unlink()
    res = run_script(project_root, mock_repo, "validate_governance_docs.py")
    assert res.returncode != 0


# --- validate_agent_policy.py ---
def test_valid_agent_policy_passes(run_script: RunScript, project_root: Path, mock_repo: Path):
    res = run_script(project_root, mock_repo, "validate_agent_policy.py")
    assert res.returncode == 0


def test_invalid_agent_policy_fails(run_script: RunScript, project_root: Path, mock_repo: Path):
    gov = mock_repo / ".governance"
    (gov / "agent-policy.json").write_text(json.dumps({"bad": "data"}))
    res = run_script(project_root, mock_repo, "validate_agent_policy.py")
    assert res.returncode != 0
    assert "agent-policy:" in res.stderr


def test_valid_policy_passes(run_script: RunScript, project_root: Path, mock_repo: Path):
    res = run_script(project_root, mock_repo, "validate_policy.py")
    assert res.returncode == 0


def test_missing_policy_fails(run_script: RunScript, project_root: Path, mock_repo: Path):
    (mock_repo / ".governance" / "policy.json").unlink()
    res = run_script(project_root, mock_repo, "validate_policy.py")
    assert res.returncode != 0


def test_valid_adoption_passes(run_script: RunScript, project_root: Path, mock_repo: Path):
    wf = mock_repo / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "ci.yml").write_text("uses: actions/checkout@abc123def456")
    res = run_script(project_root, mock_repo, "validate_adoption.py")
    assert res.returncode == 0
    assert "adoption: passed" in res.stdout


def test_adoption_blocker_detected(run_script: RunScript, project_root: Path, mock_repo: Path):
    wf = mock_repo / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "ci.yml").write_text("PIN_FULL_COMMIT_SHA is here")
    res = run_script(project_root, mock_repo, "validate_adoption.py")
    assert res.returncode != 0
    assert "third-party action SHAs are not pinned" in res.stderr


def test_adoption_invalid_root_of_trust_json(run_script: RunScript, project_root: Path, mock_repo: Path):
    (mock_repo / ".governance" / "root-of-trust.json").write_text("not json")
    res = run_script(project_root, mock_repo, "validate_adoption.py")
    assert res.returncode != 0
    assert "root-of-trust.json invalid" in res.stderr


def test_adoption_gradle_files_missing(run_script: RunScript, project_root: Path, mock_repo: Path):
    (mock_repo / "build.gradle.kts").write_text("")
    res = run_script(project_root, mock_repo, "validate_adoption.py")
    assert res.returncode != 0
    assert "gradlew missing" in res.stderr


def test_adoption_commented_remotes_missing_rot_and_lockfile(
    run_script: RunScript, project_root: Path, mock_repo: Path
):
    """Three independent blockers in one pass: an allowed-remotes file with only
    comments counts as empty, a missing root-of-trust declaration is fatal, and
    a package.json without pnpm-lock.yaml fails the Node lock check."""
    wf = mock_repo / ".github" / "workflows"
    (wf / "ci.yml").write_text("uses: actions/checkout@abc123def456")
    (mock_repo / ".governance" / "allowed-remotes.txt").write_text("# no approved destinations yet\n   \n")
    (mock_repo / ".governance" / "root-of-trust.json").unlink()
    (mock_repo / "package.json").write_text("{}")
    res = run_script(project_root, mock_repo, "validate_adoption.py")
    assert res.returncode != 0
    assert "allowed-remotes.txt has no approved destination" in res.stderr
    assert "root-of-trust.json missing" in res.stderr
    assert "pnpm-lock.yaml missing" in res.stderr


def test_adoption_rot_without_external_ref_or_valid_digest(run_script: RunScript, project_root: Path, mock_repo: Path):
    (mock_repo / ".governance" / "root-of-trust.json").write_text(
        json.dumps({"external_policy_ref": "", "policy_sha256": "not-a-digest"})
    )
    res = run_script(project_root, mock_repo, "validate_adoption.py")
    assert res.returncode != 0
    assert "lacks external policy ref or SHA-256 digest" in res.stderr


def test_adoption_rot_valid_but_policy_json_missing(run_script: RunScript, project_root: Path, mock_repo: Path):
    (mock_repo / ".governance" / "policy.json").unlink()
    (mock_repo / ".governance" / "root-of-trust.json").write_text(
        json.dumps({"external_policy_ref": "https://example.com/policy", "policy_sha256": "a" * 64})
    )
    res = run_script(project_root, mock_repo, "validate_adoption.py")
    assert res.returncode != 0
    assert ".governance/policy.json missing" in res.stderr


def test_adoption_rot_digest_mismatch(run_script: RunScript, project_root: Path, mock_repo: Path):
    (mock_repo / ".governance" / "root-of-trust.json").write_text(
        json.dumps({"external_policy_ref": "https://example.com/policy", "policy_sha256": "a" * 64})
    )
    res = run_script(project_root, mock_repo, "validate_adoption.py")
    assert res.returncode != 0
    assert "policy_sha256 does not match local policy.json" in res.stderr


def test_valid_projections_pass(run_script: RunScript, project_root: Path, mock_repo: Path):
    res = run_script(project_root, mock_repo, "check_projections.py")
    assert res.returncode == 0


def test_missing_projection_fails(run_script: RunScript, project_root: Path, mock_repo: Path):
    gov = mock_repo / ".governance"
    (gov / "projections.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "mappings": [{"source": "src.txt", "projection": "missing.txt"}],
            }
        )
    )
    (mock_repo / "src.txt").write_text("hello")
    res = run_script(project_root, mock_repo, "check_projections.py")
    assert res.returncode != 0
    assert "missing mapping endpoint" in res.stderr


def test_projections_disabled_explicitly(run_script: RunScript, project_root: Path, mock_repo: Path):
    gov = mock_repo / ".governance"
    (gov / "projections.json").write_text(
        json.dumps(
            {
                "enabled": False,
                "decision_id": "DEC-456",
                "mappings": [],
            }
        )
    )
    (gov / "decision-log.md").write_text("DEC-456")
    res = run_script(project_root, mock_repo, "check_projections.py")
    assert res.returncode == 0
    assert "explicitly not applicable" in res.stdout


def test_projections_disabled_without_decision(run_script: RunScript, project_root: Path, mock_repo: Path):
    gov = mock_repo / ".governance"
    (gov / "projections.json").write_text(
        json.dumps(
            {
                "enabled": False,
                "decision_id": "DEC-999",
                "mappings": [],
            }
        )
    )
    res = run_script(project_root, mock_repo, "check_projections.py")
    assert res.returncode != 0
    assert "disabled without a decision-log entry" in res.stderr


def test_valid_traceability_passes(run_script: RunScript, project_root: Path, mock_repo: Path):
    res = run_script(project_root, mock_repo, "check_traceability.py")
    assert res.returncode == 0


def test_missing_requirement_fails(run_script: RunScript, project_root: Path, mock_repo: Path):
    req_file = mock_repo / "docs" / "reqs.md"
    req_file.parent.mkdir(parents=True, exist_ok=True)
    req_file.write_text("R-123")

    src = mock_repo / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "test.py").write_text("# covers REQ-NOTHING")

    res = run_script(
        project_root, mock_repo, "check_traceability.py", ["--req-files", "docs/reqs.md", "--src-dir", "src"]
    )
    assert res.returncode != 0
    assert "missing implementation and/or test citation" in res.stderr


def test_validate_specs_default_and_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.shared import validate_specs

    # Test default args (specs_dir is None)
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    (specs_dir / "SPEC_TEMPLATE.md").write_text("# Template", encoding="utf-8")
    (specs_dir / "valid_spec.md").write_text(
        "## Requirements\n- MUST R-01 foo\n## Acceptance criteria\nDone.\n", encoding="utf-8"
    )

    res = validate_specs.main(specs_dir)
    assert res == 0


def test_validate_specs_unreadable_file_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.shared import validate_specs

    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    spec = specs_dir / "broken.md"
    spec.write_text("dummy", encoding="utf-8")

    def mock_read_text(self, *args, **kwargs):
        raise OSError("Permission denied reading spec")

    monkeypatch.setattr(Path, "read_text", mock_read_text)
    res = validate_specs.main(specs_dir)
    assert res == 1


def test_validate_specs_run_script(run_script: RunScript, project_root: Path, mock_repo: Path) -> None:
    res = run_script(project_root, mock_repo, "validate_specs.py")
    assert res.returncode == 0
