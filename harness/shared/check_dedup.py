"""Drift gate: per-stack governance scripts must be thin delegators to the shared kernel.

Single source of truth: logic lives in `harness/shared/` (or `harness/shared/governance/`).
Each `harness/<stack>/scripts/<name>.py` that shadows a shared module must be a thin shim
that delegates to it, never a copy. Byte-identical copies drift silently the moment one
side is patched, which is the failure class this gate exists to prevent.

Two delegation styles are both accepted, so existing shims keep working:

* import re-export - ``from harness.shared[.governance].<name> import ...``
* runpy delegation - ``runpy.run_path(<shared>/<name>.py, ...)``

Nothing here is hard-coded: stacks, script names, and thresholds are all discovered from
the repository layout and `harness/shared/governance-policy.json`.

Exit codes: 0 = no drift, 1 = drift detected.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from harness.shared.json_logging import LOG_LEVEL_ENV_VAR, resolve_log_level
except ImportError:  # direct `python harness/shared/<gate>.py`: sys.path[0] is this dir
    from json_logging import LOG_LEVEL_ENV_VAR, resolve_log_level  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SHARED_RELPATH = Path("harness") / "shared"
POLICY_RELPATH = SHARED_RELPATH / "governance-policy.json"
STACKS_PARENT_RELPATH = Path("harness")
SCRIPTS_SUBDIR = "scripts"

# A delegating shim is small by construction. Overridable via policy or --max-shim-lines.
DEFAULT_MAX_SHIM_LINES = 40

# Shared subpackages searched (in order) for the canonical module behind a stack script.
SHARED_SEARCH_SUBDIRS = ("", "governance")


@dataclass
class DedupConfig:
    """Resolved configuration for the dedup gate."""

    repo_root: Path
    max_shim_lines: int = DEFAULT_MAX_SHIM_LINES
    exempt: frozenset[str] = frozenset()

    @property
    def shared_dir(self) -> Path:
        return self.repo_root / SHARED_RELPATH


@dataclass
class DedupReport:
    """Structured result so callers (CI, tests, agents) can consume findings."""

    checked: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "failures": self.failures,
            "skipped": self.skipped,
        }


def load_config(repo_root: Path, max_shim_lines: int | None = None) -> DedupConfig:
    """Build config from the governance policy, allowing an explicit override.

    Precedence: explicit argument > `MAX_SHIM_LINES` env > policy `dedup.max_shim_lines`
    > module default. A *missing* policy degrades to defaults (the adopter path); a
    policy that exists but cannot be parsed fails closed, because degrading there
    would silently relax the shim budget.
    """
    cfg = DedupConfig(repo_root=repo_root)
    policy_path = repo_root / POLICY_RELPATH
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        if not isinstance(policy, dict):
            raise TypeError(f"policy root must be a JSON object, got {type(policy).__name__}")
        dedup = policy.get("dedup", {}) or {}
        if isinstance(dedup.get("max_shim_lines"), int):
            cfg.max_shim_lines = int(dedup["max_shim_lines"])
        exempt = dedup.get("exempt") or []
        if isinstance(exempt, list):
            cfg.exempt = frozenset(str(x) for x in exempt)
        logger.debug("Loaded dedup config from %s: %s", policy_path, dedup)
    except FileNotFoundError:
        logger.debug("No governance policy at %s; using defaults", policy_path)
    except OSError as e:
        # Present but unreadable (permissions, I/O) is not the adopter path either.
        logger.error("[FAIL] Could not read governance policy %s: %s", policy_path, e)
        raise SystemExit(1) from e
    except (ValueError, TypeError) as e:
        # Absent policy -> defaults (adopter path). Present but unparseable ->
        # corruption, and degrading to defaults would silently relax the shim
        # budget. Governance fails closed, as load_protected_patterns does.
        logger.error("[FAIL] Malformed governance policy %s: %s", policy_path, e)
        raise SystemExit(1) from e

    env_override = os.environ.get("MAX_SHIM_LINES")
    if env_override:
        try:
            cfg.max_shim_lines = int(env_override)
        except ValueError:
            logger.warning("Ignoring non-integer MAX_SHIM_LINES=%r", env_override)

    if max_shim_lines is not None:
        cfg.max_shim_lines = max_shim_lines
    return cfg


def discover_stacks(repo_root: Path) -> list[str]:
    """Return stack names (e.g. node, jvm) that have a scripts/ directory."""
    parent = repo_root / STACKS_PARENT_RELPATH
    if not parent.is_dir():
        return []
    stacks = sorted(
        d.name
        for d in parent.iterdir()
        if d.is_dir() and d.name != "shared" and (d / SCRIPTS_SUBDIR).is_dir()
    )
    logger.debug("Discovered stacks: %s", stacks)
    return stacks


def find_shared_module(shared_dir: Path, name: str) -> Path | None:
    """Locate the canonical shared module for a stack script name, if any."""
    for sub in SHARED_SEARCH_SUBDIRS:
        candidate = (shared_dir / sub / f"{name}.py") if sub else (shared_dir / f"{name}.py")
        if candidate.is_file():
            return candidate
    return None


def classify_shim(text: str, shared_module: Path | None = None) -> str | None:
    """Return the delegation style used by a shim, or None if it delegates in no known way.

    Uses AST parsing to confirm the delegation actually imports or calls runpy on the
    expected shared module.
    """
    try:
        tree = ast.parse(text)
    except Exception:
        return None

    target_stem = shared_module.stem if shared_module is not None else None

    # Check for AST-level imports
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("harness.shared"):
                if target_stem is None or target_stem in node.module:
                    return "import"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("harness.shared"):
                    if target_stem is None or target_stem in alias.name:
                        return "import"
        elif isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Attribute) and node.func.attr == "run_path":
                func_name = "runpy.run_path"
            elif isinstance(node.func, ast.Name) and node.func.id == "run_path":
                func_name = "run_path"
            if func_name and node.args:
                try:
                    arg_str = ast.unparse(node.args[0])
                except Exception:
                    arg_str = ""
                if "shared" in arg_str.lower() or "_shared" in arg_str.lower():
                    if target_stem is None or target_stem in arg_str:
                        return "runpy"

    return None


def check_script(script: Path, shared_module: Path, cfg: DedupConfig) -> str | None:
    """Validate one stack script against its shared counterpart.

    Returns a human-readable failure reason, or None when the script is a valid shim.
    """
    rel = script.relative_to(cfg.repo_root).as_posix()
    try:
        text = script.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - unreadable file is itself a failure
        return f"{rel}: could not read ({e})"

    shared_rel = shared_module.relative_to(cfg.repo_root).as_posix()
    style = classify_shim(text, shared_module=shared_module)
    if style is None:
        # Distinguish the two failure modes so the remediation message is actionable.
        # Note: being byte-identical to the shared file is only drift when neither file
        # delegates; two identical shims pointing at the same canonical module are fine.
        try:
            if script.read_bytes() == shared_module.read_bytes():
                return (
                    f"{rel}: byte-identical copy of {shared_rel} - replace with a delegating shim "
                    f"(import from harness.shared or runpy.run_path)"
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("Could not compare bytes for %s: %s", rel, e)
        return (
            f"{rel}: not a delegating shim - must re-export from harness.shared "
            f"or call runpy.run_path on {shared_rel}"
        )

    line_count = len(text.splitlines())
    if line_count > cfg.max_shim_lines:
        return (
            f"{rel}: {line_count} lines exceeds the {cfg.max_shim_lines}-line shim budget "
            f"({style} delegation) - logic belongs in {shared_rel}"
        )

    logger.debug("%s OK (%s delegation, %d lines)", rel, style, line_count)
    return None


def run(cfg: DedupConfig) -> DedupReport:
    """Check every stack script that shadows a shared module."""
    report = DedupReport()
    for stack in discover_stacks(cfg.repo_root):
        scripts_dir = cfg.repo_root / STACKS_PARENT_RELPATH / stack / SCRIPTS_SUBDIR
        for script in sorted(scripts_dir.glob("*.py")):
            rel = script.relative_to(cfg.repo_root).as_posix()
            if script.name in cfg.exempt or rel in cfg.exempt:
                logger.debug("Exempt by policy: %s", rel)
                report.skipped.append(rel)
                continue
            shared_module = find_shared_module(cfg.shared_dir, script.stem)
            if shared_module is None:
                # Stack-only helper with no shared counterpart: nothing to deduplicate.
                report.skipped.append(rel)
                continue
            report.checked.append(rel)
            failure = check_script(script, shared_module, cfg)
            if failure:
                report.failures.append(failure)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT, help="repository root")
    parser.add_argument(
        "--max-shim-lines",
        type=int,
        default=None,
        help="maximum lines a delegating shim may have (overrides policy/env)",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report on stdout")
    parser.add_argument("--log-level", default=os.environ.get(LOG_LEVEL_ENV_VAR, "INFO"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # resolve_log_level degrades an unusable level to the default; passing the raw
    # string to basicConfig raised ValueError, turning LOG_LEVEL=BOGUS into a red gate.
    logging.basicConfig(level=resolve_log_level(str(args.log_level)), format="%(levelname)s: %(message)s")

    repo_root = args.repo_root.resolve()
    cfg = load_config(repo_root, max_shim_lines=args.max_shim_lines)
    logger.info(
        "Checking per-stack governance scripts delegate to %s (shim budget: %d lines)",
        cfg.shared_dir.relative_to(repo_root).as_posix(),
        cfg.max_shim_lines,
    )

    report = run(cfg)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))

    for failure in report.failures:
        logger.error("[FAIL] %s", failure)

    if report.ok:
        logger.info(
            "[PASS] %d per-stack script(s) delegate to the shared kernel; %d skipped (no shared counterpart).",
            len(report.checked),
            len(report.skipped),
        )
        return 0
    logger.error("[FAIL] %d of %d per-stack script(s) drifted from the shared kernel.",
                 len(report.failures), len(report.checked))
    return 1


if __name__ == "__main__":
    sys.exit(main())
