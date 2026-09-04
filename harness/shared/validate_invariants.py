"""Repository invariant checks: protected paths, hardcoded secrets, and file size budgets.

These checks are intentionally deterministic and free of third-party dependencies so
they can run as a CI gate (`make validate`), a skill step
(`.mango/skills/repo-invariant-review`), or an orchestrator pre-flight; sibling
modules in `harness/shared/` are the only non-stdlib imports.

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
# Adopter defaults, used only when no governance policy exists at all. In this
# repository the numbers come from `limits.*` in governance-policy.json.
SIZE_BUDGET_LINES = 500
TEST_SIZE_BUDGET_LINES = 700
SIZE_BUDGET_ENV = "MAX_FILE_LINES"
TEST_SIZE_BUDGET_ENV = "MAX_TEST_FILE_LINES"
SECRET_PATTERNS = ("OPENAI_API_KEY =", "ANTHROPIC_API_KEY =", "NVIDIA_API_KEY =", "API_SERVER_KEY =")

# Skip directories that are not first-party source under governance.
SKIP_DIR_PARTS = frozenset({".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules", ".git"})


def _policy_limit(key: str, default: int, policy_path: Path | None, env_var: str) -> int:
    """Resolve `limits.<key>` from policy; `env_var` may only *tighten* it.

    Fails closed three ways, and the second and third are R-CQ-8:

    An absent policy is the adopter path and legitimately falls back to the
    built-in budget. One that exists and cannot be parsed is corruption, and
    silently substituting the default would relax the gate on exactly the input
    that should stop it.

    A *present* policy missing `limits` or missing this key is the same failure
    wearing a valid-JSON costume: the file a reviewer was pointed at no longer
    states the budget, while the gate goes on reporting PASS against a number
    that exists only in this source file. `policy.ts:58-69` has always thrown
    for it. Now so does this.

    And the environment override can only lower the budget, never raise it.
    `MAX_FILE_LINES=9999` used to be returned verbatim, so any caller that could
    set an environment variable could switch the size gate off while it still
    printed `[PASS] Size Budget` -- a gate whose own report is indistinguishable
    from a real pass is worse than no gate. Tightening stays useful (a stricter
    local run, a bisect) and cannot weaken what the policy says.
    """
    policy_path = policy_path or DEFAULT_POLICY_PATH
    try:
        raw = policy_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # A policy that is simply absent is the adopter path; defaults apply.
        logger.debug("No governance policy at %s; using the built-in %s", policy_path, key)
        budget = default
    except OSError as e:
        logger.error("[FAIL] Could not read governance policy %s: %s", policy_path, e)
        sys.exit(1)
    else:
        try:
            policy = json.loads(raw)
            if not isinstance(policy, dict):
                raise TypeError(f"policy root must be a JSON object, got {type(policy).__name__}")
            limits = policy.get("limits")
            if not isinstance(limits, dict) or key not in limits:
                raise TypeError(
                    f"present policy does not state limits.{key}; refusing to substitute the "
                    f"built-in {default}, which would let this gate pass against a budget the "
                    "policy no longer declares"
                )
            budget = int(limits[key])
        except (ValueError, TypeError) as e:
            # A policy that exists but cannot be parsed is corruption, not an adopter
            # default. Returning the built-in budget here let a malformed policy
            # silently relax the gate -- the same fail-open inversion COV_MIN had.
            logger.error("[FAIL] Malformed governance policy %s: %s", policy_path, e)
            sys.exit(1)

    override = os.environ.get(env_var)
    if not override:
        return budget
    try:
        requested = int(override)
    except ValueError:
        logger.warning("Ignoring non-integer %s=%r; using policy default", env_var, override)
        return budget
    if requested >= budget:
        logger.warning(
            "Ignoring %s=%d: an override may only tighten %s (policy says %d)",
            env_var, requested, key, budget,
        )
        return budget
    logger.info("%s=%d tightens %s from the policy's %d", env_var, requested, key, budget)
    return requested


def size_budget_lines(policy_path: Path | None = None) -> int:
    """Per-file line budget for source modules (`limits.size_budget_lines`; `MAX_FILE_LINES` overrides)."""
    return _policy_limit("size_budget_lines", SIZE_BUDGET_LINES, policy_path, SIZE_BUDGET_ENV)


def test_size_budget_lines(policy_path: Path | None = None) -> int:
    """Per-file line budget for test modules (`limits.test_size_budget_lines`; `MAX_TEST_FILE_LINES` overrides).

    Tests were exempt from the source budget and the exemption grew a 923-line
    module (tech-debt-hardening-plan R-TDH-22). They get their own, larger budget
    rather than the source one because tabular cases legitimately run long.
    """
    return _policy_limit("test_size_budget_lines", TEST_SIZE_BUDGET_LINES, policy_path, TEST_SIZE_BUDGET_ENV)


def _is_test_module(py_file: Path) -> bool:
    return py_file.name.startswith("test_") or py_file.name.endswith("_test.py")


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
        # No default. The old `.get("protected_paths", [".github/**"])` meant a
        # policy that lost the key kept protecting one directory and reported
        # `[PASS] Protected Paths` for every other file in the set -- the
        # enforcement layer, the agent control surface and the runtime gates all
        # silently unprotected, with a green check over it (R-CQ-8).
        if "protected_paths" not in policy:
            raise KeyError(
                "policy states no protected_paths; refusing to fall back to a one-pattern "
                "default that would report PASS while protecting almost nothing"
            )
        patterns = list(policy["protected_paths"])
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
            out = subprocess.check_output(cmd, encoding="utf-8", cwd=workspace_dir)
            found = [line for line in out.splitlines() if line.strip()]
            logger.debug("%s -> %d path(s)", " ".join(cmd), len(found))
            modified.update(found)
        # Inability to inspect git state is fatal: re-raised below, which is
        # also why BLE001 does not fire here.
        except Exception as e:
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
    for root, dirs, files in os.walk(workspace_dir):
        # Prune skipped directories in-place so os.walk doesn't traverse them
        dirs[:] = [d for d in dirs if d not in SKIP_DIR_PARTS]

        for file in files:
            if file.endswith(".py"):
                yield Path(root) / file


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


def _check_line_budget(workspace_dir: Path, budget: int, label: str, tests: bool) -> bool:
    """Shared scan for the two budgets: `tests` selects test modules or everything else.

    On success the closest file and its remaining headroom are reported, which
    turns a cliff into a gauge. The budget previously said nothing at all until
    it failed, so the first signal a contributor got was a red gate mid-PR:
    `test_verify_zero_skips.py` sat at 684 of 700 — sixteen lines, in the suite
    for the invariant most likely to gain a test — and nothing surfaced that.
    The line is INFO and cannot change the verdict; it reports the measurement
    the check already performs rather than introducing a second threshold to
    keep in step with the first.
    """
    failed = False
    closest: tuple[int, str] | None = None
    for py_file in _first_party_py_files(workspace_dir):
        if _is_test_module(py_file) != tests:
            continue
        try:
            line_count = len(py_file.read_text(encoding="utf-8").splitlines())
            if line_count > budget:
                logger.error("[FAIL] %s: File %s exceeds %d lines (%d lines).", label, py_file.name, budget, line_count)
                failed = True
            elif closest is None or line_count > closest[0]:
                closest = (line_count, py_file.name)
        except Exception as e:  # noqa: BLE001 - unreadable file must not abort the scan
            logger.debug("Skipping unreadable file %s: %s", py_file, e)
    if not failed:
        logger.info("[PASS] %s: All %s under %d lines.", label, "test modules" if tests else "files", budget)
        if closest is not None:
            logger.info(
                "%s: closest is %s at %d lines (%d to spare).", label, closest[1], closest[0], budget - closest[0]
            )
    return not failed


def check_size_budget(workspace_dir: Path, budget: int | None = None, policy_path: Path | None = None) -> bool:
    """Return False if any first-party non-test .py file exceeds the line budget."""
    resolved_policy = policy_path or (workspace_dir / "harness" / "shared" / "governance-policy.json")
    budget = size_budget_lines(resolved_policy) if budget is None else budget
    return _check_line_budget(workspace_dir, budget, "Size Budget", tests=False)


def check_test_size_budget(workspace_dir: Path, budget: int | None = None, policy_path: Path | None = None) -> bool:
    """Return False if any first-party test module exceeds `limits.test_size_budget_lines` (R-TDH-22)."""
    resolved_policy = policy_path or (workspace_dir / "harness" / "shared" / "governance-policy.json")
    budget = test_size_budget_lines(resolved_policy) if budget is None else budget
    return _check_line_budget(workspace_dir, budget, "Test Size Budget", tests=True)


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
        check_test_size_budget(workspace_dir, policy_path=policy_path),
    ]

    if all(results):
        logger.info("Repo Invariants Check PASSED.")
        return 0
    logger.error("Repo Invariants Check FAILED.")
    return 1


if __name__ == "__main__":
    try:
        from harness.shared.json_logging import resolve_log_level
    except ImportError:  # direct `python harness/shared/validate_invariants.py`
        from json_logging import resolve_log_level  # type: ignore[no-redef]
    # resolve_log_level degrades an unusable level to the default; passing the raw
    # env string to basicConfig raised ValueError, turning LOG_LEVEL=BOGUS into a
    # red gate -- misconfigured verbosity must never fail a governance gate.
    logging.basicConfig(
        level=resolve_log_level(),
        format="%(levelname)s: %(message)s",
    )
    sys.exit(main())
