import fnmatch
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def main() -> None:
    logger.info("Running Repo Invariants Check...")
    failed = False

    workspace_dir = Path(__file__).resolve().parent.parent.parent

    # Load protected paths from governance policy
    gov_policy_path = workspace_dir / "harness" / "shared" / "governance-policy.json"
    try:
        policy = json.loads(gov_policy_path.read_text(encoding="utf-8"))
        protected_patterns = policy.get("protected_paths", [".github/**"])
    except Exception as e:
        logger.error(f"Could not load governance policy: {e}")
        sys.exit(1)

    # 1. Protected Paths check
    try:
        staged = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only"], text=True, cwd=workspace_dir
        ).splitlines()
        unstaged = subprocess.check_output(["git", "diff", "--name-only"], text=True, cwd=workspace_dir).splitlines()
        modified_files = set(staged + unstaged)

        base_ref = os.environ.get("GITHUB_BASE_REF")
        if base_ref:
            pr_diff = subprocess.check_output(
                ["git", "diff", f"origin/{base_ref}...HEAD", "--name-only"], text=True, cwd=workspace_dir
            ).splitlines()
            modified_files.update(pr_diff)

        policy_modifications = []
        for mf in modified_files:
            for pattern in protected_patterns:
                # Use fnmatch for glob pattern matching
                if fnmatch.fnmatch(mf, pattern):
                    policy_modifications.append(mf)
                    break

        if policy_modifications and os.environ.get("ALLOW_GITHUB_CHANGES") != "1":
            logger.error(
                "Protected Paths: Unauthorized modifications to protected paths "
                f"detected: {policy_modifications}"
            )
            failed = True
        else:
            logger.info("Protected Paths: No unauthorized modifications to protected systems.")
    except Exception as e:
        logger.error(f"Protected Paths: Could not run git diff: {e}")
        failed = True

    # 2. Hardcoded Secrets check
    # Let's search the workspace for "API_KEY = " or similar patterns (naively).

    # Simple naive scan
    secret_patterns = [
        "OPENAI_API_KEY =",
        "ANTHROPIC_API_KEY =",
        "NVIDIA_API_KEY =",
        "API_SERVER_KEY =",
    ]
    for py_file in workspace_dir.rglob("*.py"):
        if ".venv" in py_file.parts or ".mypy_cache" in py_file.parts or ".pytest_cache" in py_file.parts:
            continue
        if py_file.name == "validate_invariants.py":
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            if any(secret in content for secret in secret_patterns):
                logger.error(f"Hardcoded secret found in {py_file}")
                failed = True
        except Exception:
            pass

    if not failed:
        logger.info("Secrets: No hardcoded API keys detected.")

    # 3. Size budget / Coverage check
    size_budget_failed = False
    max_size = 500
    for py_file in workspace_dir.rglob("*.py"):
        if ".venv" in py_file.parts or ".mypy_cache" in py_file.parts or ".pytest_cache" in py_file.parts:
            continue
        if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
            continue
        try:
            lines = py_file.read_text(encoding="utf-8").splitlines()
            if len(lines) > max_size:
                logger.error(f"Size Budget: File {py_file.name} exceeds {max_size} lines ({len(lines)} lines).")
                failed = True
                size_budget_failed = True
        except Exception:
            pass

    if not size_budget_failed:
        logger.info(f"Size Budget: All files under {max_size} lines.")

    if failed:
        logger.error("Repo Invariants Check FAILED.")
        sys.exit(1)
    else:
        logger.info("Repo Invariants Check PASSED.")
        sys.exit(0)


if __name__ == "__main__":
    main()
