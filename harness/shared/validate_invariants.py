"""Repository invariant checks: protected paths, hardcoded secrets, and file size budget.

These checks are intentionally deterministic and dependency-free so they can run as a
git pre-push hook, a CI gate, or an orchestrator pre-flight (`.mango/hooks/pre-nemotron-run.sh`).

Exit codes: 0 = all invariants satisfied, 1 = one or more invariants violated.
"""

import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_POLICY_PATH = DEFAULT_WORKSPACE_DIR / "harness" / "shared" / "governance-policy.json"
SIZE_BUDGET_LINES = 500

# Skip directories that are not first-party source under governance.
SKIP_DIR_PARTS = frozenset({".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules", ".git"})


def load_protected_patterns(policy_path: Path) -> list[str]:
    """Load protected path patterns from the governance policy JSON.

    Falls back to a conservative default if the policy file is missing or unreadable.
    """
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        return list(policy.get("protected_paths", [".github/**"]))
    except Exception as e:  # noqa: BLE001 - governance must fail closed with a reason
        print(f"[FAIL] Could not load governance policy from {policy_path}: {e}")
        sys.exit(1)


def git_modified_files(workspace_dir: Path) -> set[str]:
    """Return the set of files modified (staged + unstaged + PR diff) relative to workspace_dir."""
    modified: set[str] = set()
    base_ref = os.environ.get("GITHUB_BASE_REF")
    commands = [
        ["git", "diff", "--cached", "--name-only"],
        ["git", "diff", "--name-only"],
    ]
    if base_ref:
        commands.append(["git", "diff", f"origin/{base_ref}...HEAD", "--name-only"])
    for cmd in commands:
        try:
            out = subprocess.check_output(cmd, text=True, cwd=workspace_dir)
            modified.update(line for line in out.splitlines() if line.strip())
        except Exception as e:  # noqa: BLE001 - git may be absent; report but continue
            print(f"[WARN] Could not run {' '.join(cmd)}: {e}")
    return modified


def check_protected_paths(workspace_dir: Path, protected_patterns: list[str]) -> bool:
    """Return True if any modified file matches a protected path (and not explicitly allowed)."""
    modified_files = git_modified_files(workspace_dir)
    policy_modifications = [
        mf for mf in modified_files for pattern in protected_patterns if fnmatch.fnmatch(mf, pattern)
    ]
    # Deduplicate while preserving order.
    ordered: list[str] = []
    seen: set[str] = set()
    for x in policy_modifications:
        if x not in seen:
            seen.add(x)
            ordered.append(x)
    if ordered and os.environ.get("ALLOW_GITHUB_CHANGES") != "1":
        print(
            "[FAIL] Protected Paths: Unauthorized modifications to protected "
            f"paths detected: {ordered}"
        )
        return False
    print("[PASS] Protected Paths: No unauthorized modifications to protected systems.")
    return True


def check_hardcoded_secrets(workspace_dir: Path) -> bool:
    """Return False if a first-party .py file assigns a known secret literal."""
    secret_patterns = ("OPENAI_API_KEY =", "ANTHROPIC_API_KEY =", "NVIDIA_API_KEY =", "API_SERVER_KEY =")
    failed = False
    for py_file in workspace_dir.rglob("*.py"):
        if SKIP_DIR_PARTS & set(py_file.parts) or py_file.name == "validate_invariants.py":
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            if any(p in content for p in secret_patterns):
                print(f"[FAIL] Hardcoded secret found in {py_file}")
                failed = True
        except Exception:
            pass
    if not failed:
        print("[PASS] Secrets: No hardcoded API keys detected.")
    return not failed


def check_size_budget(workspace_dir: Path, budget: int = SIZE_BUDGET_LINES) -> bool:
    """Return False if any first-party non-test .py file exceeds the line budget."""
    failed = False
    for py_file in workspace_dir.rglob("*.py"):
        if SKIP_DIR_PARTS & set(py_file.parts):
            continue
        if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
            continue
        try:
            line_count = len(py_file.read_text(encoding="utf-8").splitlines())
            if line_count > budget:
                print(f"[FAIL] Size Budget: File {py_file.name} exceeds {budget} lines ({line_count} lines).")
                failed = True
        except Exception:
            pass
    if not failed:
        print("[PASS] Size Budget: All files under the line budget.")
    return not failed


def main(workspace_dir: Path | None = None, policy_path: Path | None = None) -> int:
    """Run all repo invariant checks. Returns process exit code (0 = pass)."""
    print("Running Repo Invariants Check...")
    workspace_dir = workspace_dir or DEFAULT_WORKSPACE_DIR
    policy_path = policy_path or (workspace_dir / "harness" / "shared" / "governance-policy.json")

    protected_patterns = load_protected_patterns(policy_path)

    results = [
        check_protected_paths(workspace_dir, protected_patterns),
        check_hardcoded_secrets(workspace_dir),
        check_size_budget(workspace_dir),
    ]

    if all(results):
        print("\nRepo Invariants Check PASSED.")
        return 0
    print("\nRepo Invariants Check FAILED.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
