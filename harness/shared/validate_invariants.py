"""Repository invariant checks: protected paths, hardcoded secrets, and file size budget.

These checks are intentionally deterministic and dependency-free so they can run as a
git pre-push hook, a CI gate, or an orchestrator pre-flight (`.mango/hooks/pre-nemotron-run.sh`).

Output goes through the stdlib `logging` module so callers can route or silence it; the
CLI entrypoint configures a plain `LEVEL: message` format on stderr. Set `LOG_LEVEL=DEBUG`
for per-file tracing of the secret and size-budget scans.

Exit codes: 0 = all invariants satisfied, 1 = one or more invariants violated.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_POLICY_PATH = DEFAULT_WORKSPACE_DIR / "harness" / "shared" / "governance-policy.json"
SIZE_BUDGET_LINES = 500
SECRET_PATTERNS = ("OPENAI_API_KEY =", "ANTHROPIC_API_KEY =", "NVIDIA_API_KEY =", "API_SERVER_KEY =")

# Skip directories that are not first-party source under governance.
SKIP_DIR_PARTS = frozenset({".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules", ".git"})


def size_budget_lines(policy_path: Path | None = None) -> int:
    """Resolve the per-file line budget from policy, allowing `MAX_FILE_LINES` to override.

    Fails closed on a *malformed* policy: an absent policy is the adopter path and
    legitimately falls back to the built-in budget, but one that exists and cannot
    be parsed is corruption, and silently substituting the default would relax the
    gate on exactly the input that should stop it.
    """
    override = os.environ.get("MAX_FILE_LINES")
    if override:
        try:
            return int(override)
        except ValueError:
            logger.warning("Ignoring non-integer MAX_FILE_LINES=%r; using policy default", override)
    policy_path = policy_path or DEFAULT_POLICY_PATH
    try:
        raw = policy_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # A policy that is simply absent is the adopter path; defaults apply.
        logger.debug("No governance policy at %s; using the built-in size budget", policy_path)
        return SIZE_BUDGET_LINES
    except OSError as e:
        logger.error("[FAIL] Could not read governance policy %s: %s", policy_path, e)
        sys.exit(1)
    try:
        policy = json.loads(raw)
        limits = policy.get("limits", {})
        budget = limits.get("size_budget_lines", policy.get("size_budget_lines", SIZE_BUDGET_LINES))
        return int(budget)
    except (ValueError, TypeError) as e:
        # A policy that exists but cannot be parsed is corruption, not an adopter
        # default. Returning the built-in budget here let a malformed policy
        # silently relax the gate -- the same fail-open inversion COV_MIN had.
        logger.error("[FAIL] Malformed governance policy %s: %s", policy_path, e)
        sys.exit(1)


def is_protected(path: str, protected_patterns: list[str]) -> bool:
    """Return True if a repo-root-relative path matches any protected pattern.

    Patterns are matched with `fnmatch`, which is anchored to the whole string and
    lets `*` cross `/`. A pattern written for a layout the repository does not have
    therefore matches nothing at all, silently. This predicate is the single place
    that semantic is defined, so the liveness suite measures the real matcher.
    """
    return any(fnmatch.fnmatch(path, pattern) for pattern in protected_patterns)


def load_protected_patterns(policy_path: Path) -> list[str]:
    """Load protected path patterns from the governance policy JSON.

    Governance fails closed: an unreadable policy exits non-zero rather than
    silently checking nothing.
    """
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        patterns = list(policy.get("protected_paths", [".github/**"]))
        logger.debug("Loaded %d protected path patterns from %s", len(patterns), policy_path)
        return patterns
    except Exception as e:  # noqa: BLE001 - governance must fail closed with a reason
        logger.error("[FAIL] Could not load governance policy from %s: %s", policy_path, e)
        sys.exit(1)


def git_modified_files(workspace_dir: Path) -> set[str]:
    """Return the set of files modified (staged + unstaged + untracked + PR diff)."""
    modified: set[str] = set()
    base_ref = os.environ.get("GITHUB_BASE_REF")
    # `core.quotePath=false` is load-bearing, not cosmetic: with git's default the
    # output for a non-ASCII path is C-escaped and wrapped in double quotes
    # (`"harness/shared/validate_caf\303\251.py"`), and the leading quote defeats
    # every anchored fnmatch pattern -- a protected file would pass the gate.
    git = ["git", "-c", "core.quotePath=false"]
    commands = [
        [*git, "diff", "--cached", "--name-only"],
        [*git, "diff", "--name-only"],
        # Untracked files are not listed by `git diff`; include them so a newly-created
        # file in a protected path is caught before it is staged (fail-closed).
        [*git, "ls-files", "--others", "--exclude-standard"],
    ]
    if base_ref:
        commands.append([*git, "diff", f"origin/{base_ref}...HEAD", "--name-only"])
    for cmd in commands:
        try:
            out = subprocess.check_output(cmd, text=True, cwd=workspace_dir)
            found = [line for line in out.splitlines() if line.strip()]
            logger.debug("%s -> %d path(s)", " ".join(cmd), len(found))
            modified.update(found)
        except Exception as e:  # noqa: BLE001 - inability to inspect git state is fatal
            logger.error("[FAIL] Could not run %s: %s", " ".join(cmd), e)
            raise
    return modified


def check_protected_paths(workspace_dir: Path, protected_patterns: list[str]) -> bool:
    """Return True if no modified file matches a protected path (or changes are attested)."""
    modified_files = git_modified_files(workspace_dir)
    # Deduplicate while preserving discovery order for a stable, readable failure message.
    ordered: list[str] = []
    seen: set[str] = set()
    for mf in sorted(modified_files):
        if is_protected(mf, protected_patterns) and mf not in seen:
            seen.add(mf)
            ordered.append(mf)
    if ordered and os.environ.get("ALLOW_GITHUB_CHANGES") != "1":
        logger.error(
            "[FAIL] Protected Paths: Unauthorized modifications to protected paths detected: %s", ordered
        )
        return False
    if ordered:
        logger.warning(
            "Protected Paths: %d change(s) permitted by ALLOW_GITHUB_CHANGES attestation: %s",
            len(ordered),
            ordered,
        )
    logger.info("[PASS] Protected Paths: No unauthorized modifications to protected systems.")
    return True


def _first_party_py_files(workspace_dir: Path):
    """Yield first-party Python files, skipping vendored and cache directories."""
    for py_file in workspace_dir.rglob("*.py"):
        if SKIP_DIR_PARTS & set(py_file.parts):
            continue
        yield py_file


def check_hardcoded_secrets(workspace_dir: Path) -> bool:
    """Return False if a first-party .py file assigns a known secret literal."""
    failed = False
    for py_file in _first_party_py_files(workspace_dir):
        # This module names the patterns it searches for, so exclude it from its own scan.
        if py_file.name == "validate_invariants.py":
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            if any(p in content for p in SECRET_PATTERNS):
                logger.error("[FAIL] Hardcoded secret found in %s", py_file)
                failed = True
        except Exception as e:  # noqa: BLE001 - unreadable file must not abort the scan
            logger.debug("Skipping unreadable file %s: %s", py_file, e)
    if not failed:
        logger.info("[PASS] Secrets: No hardcoded API keys detected.")
    return not failed


def check_size_budget(workspace_dir: Path, budget: int | None = None, policy_path: Path | None = None) -> bool:
    """Return False if any first-party non-test .py file exceeds the line budget."""
    resolved_policy = policy_path or (workspace_dir / "harness" / "shared" / "governance-policy.json")
    budget = size_budget_lines(resolved_policy) if budget is None else budget
    failed = False
    for py_file in _first_party_py_files(workspace_dir):
        if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
            continue
        try:
            line_count = len(py_file.read_text(encoding="utf-8").splitlines())
            if line_count > budget:
                logger.error(
                    "[FAIL] Size Budget: File %s exceeds %d lines (%d lines).", py_file.name, budget, line_count
                )
                failed = True
        except Exception as e:  # noqa: BLE001 - unreadable file must not abort the scan
            logger.debug("Skipping unreadable file %s: %s", py_file, e)
    if not failed:
        logger.info("[PASS] Size Budget: All files under %d lines.", budget)
    return not failed


def main(workspace_dir: Path | None = None, policy_path: Path | None = None) -> int:
    """Run all repo invariant checks. Returns process exit code (0 = pass)."""
    logger.info("Running Repo Invariants Check...")
    workspace_dir = workspace_dir or DEFAULT_WORKSPACE_DIR
    policy_path = policy_path or (workspace_dir / "harness" / "shared" / "governance-policy.json")
    logger.debug("workspace_dir=%s policy_path=%s", workspace_dir, policy_path)

    protected_patterns = load_protected_patterns(policy_path)

    results = [
        check_protected_paths(workspace_dir, protected_patterns),
        check_hardcoded_secrets(workspace_dir),
        check_size_budget(workspace_dir, policy_path=policy_path),
    ]

    if all(results):
        logger.info("Repo Invariants Check PASSED.")
        return 0
    logger.error("Repo Invariants Check FAILED.")
    return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s: %(message)s",
    )
    sys.exit(main())
