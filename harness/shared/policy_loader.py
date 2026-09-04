"""Single source of truth for operational values in governance-policy.json.

This module resolves: explicit argument > policy file > built-in default.
Environment-variable overrides are deliberately NOT read here — they are the
caller's layer where one exists (nemotron_bridge reads NEMOTRON_TIMEOUT_MS /
NEMOTRON_MAX_RETRIES before falling back to these policy values, completing
the full arg > env > policy > builtin chain for those knobs; orchestrator
limits define no env override). Fail-closed semantics match
coverage_gate.load_thresholds: an *absent* policy file is the adopter path
and yields built-in defaults; a *present but malformed* policy raises,
because silently falling back would let a corrupted policy weaken a gate or
a runtime limit.

Spec: docs/specs/policy-single-source.md.
"""

from __future__ import annotations

import json
import logging
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

POLICY_PATH = Path(__file__).resolve().parent / "governance-policy.json"

logger = logging.getLogger(__name__)


class OrchestratorLimits(TypedDict):
    """The `orchestrator` block, typed so an unknown key is a static error.

    Every threshold in the system resolves through this module, and the
    accessors used to return a bare ``dict`` -- so ``limits["max_iteration"]``
    was a runtime ``KeyError`` in whatever code path happened to reach it
    first. DEC-032 fixed one instance of exactly that shape by hand, in
    ``_session_hooks``. A ``TypedDict`` is a plain ``dict`` at runtime, so no
    caller changes and adopters reading the block dynamically are unaffected;
    what changes is that ``python -m mypy`` now reports the typo (R-GT-5).
    """

    max_iterations: int
    api_timeout_sec: int
    tool_timeout_sec: int
    max_command_bytes: int
    max_healing_retries: int
    max_output_bytes: int


class NemotronDefaults(TypedDict):
    """The `nemotron` block. See :class:`OrchestratorLimits` for the rationale."""

    temperature: float
    top_p: float
    max_tokens: int
    timeout_ms: int
    max_retries: int


class LangGraphDefaults(TypedDict):
    """The `langgraph` block. See :class:`OrchestratorLimits` for the rationale."""

    recursion_limit: int
    max_concurrency: int
    plan_divergence_threshold: float


class CoverageThresholds(TypedDict):
    """The `coverage` block. See :class:`OrchestratorLimits` for the rationale."""

    lines: int
    branches: int


def _log_resolution(block: str, values: Mapping[str, object], policy_path: Path | None) -> None:
    """Record what a policy block resolved to, and which file it came from.

    Nothing recorded which policy a run actually read, so under
    ``LOG_LEVEL=DEBUG`` the question "which thresholds is this run enforcing,
    and from where" had no answer -- while every gate in the repository depends
    on the answer. ``ExecutionLoop`` already logs its own resolution this way;
    this is the same pattern applied at the source (R-GT-4).

    Guarded on ``isEnabledFor`` so the formatting cost is not paid on the
    default path, and emitted at DEBUG so nothing changes for existing callers.
    """
    if not logger.isEnabledFor(logging.DEBUG):
        return
    resolved = policy_path or POLICY_PATH
    origin = resolved if resolved.exists() else f"{resolved} (absent; built-in defaults)"
    logger.debug(
        "policy %s resolved from %s: %s",
        block,
        origin,
        ", ".join(f"{key}={value!r}" for key, value in sorted(values.items())),
    )


class PolicyError(ValueError):
    """A policy file exists but cannot be used. Never swallowed."""


def policy_file_is_absent(path: Path) -> bool:
    """True when nothing exists at ``path`` -- the adopter path.

    Raises PolicyError for anything else: a directory, a dangling symlink, a
    FIFO, a device node, a path whose parent component is not a directory, an
    unreadable parent, a symlink loop.

    Deliberately probes with ``stat``/``lstat`` rather than the ``Path``
    predicates. ``is_file()``, ``exists()`` and ``is_symlink()`` all swallow
    OSError and answer False, so each of them reports "absent" for a policy
    that is present and merely inaccessible -- a parent directory without
    execute permission, or a path component that turned out to be a file. The
    predicates cannot express the question; only the errno can.

    That distinction is the whole point of this function. "This adopter has not
    adopted the policy yet" is supported and yields built-in defaults. "The
    policy that governs this run cannot be read" must stop the run. Collapse
    them and a bad volume mount or a half-extracted archive drops every
    threshold to its default while every gate still reports success.
    """
    try:
        info = path.stat()
    except FileNotFoundError:
        # Either nothing is here at all, or a symlink whose target is gone --
        # stat() follows the link and cannot tell them apart. lstat() does not
        # follow it, so it answers the question stat() just lost.
        try:
            path.lstat()
        except FileNotFoundError:
            return True
        except OSError as exc:
            raise PolicyError(f"governance policy path {path} is not readable: {exc}") from exc
        raise PolicyError(
            f"governance policy path {path} is a symlink whose target does not exist; "
            "refusing to fall back to built-in defaults"
        ) from None
    except OSError as exc:
        raise PolicyError(f"governance policy path {path} is not readable: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise PolicyError(
            f"governance policy path {path} exists but is not a regular file; "
            "refusing to fall back to built-in defaults"
        )
    return False


def load_policy(policy_path: Path | None = None) -> dict:
    """Return the parsed policy, or {} when no policy file exists (adopter path).

    A present-but-unparseable policy raises PolicyError (fail-closed), and so
    does a policy path that exists without being a regular file.
    """
    path = POLICY_PATH if policy_path is None else policy_path
    if policy_file_is_absent(path):
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicyError(f"unreadable governance policy at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError(f"governance policy at {path} is not a JSON object")
    return data


def _section(name: str, policy_path: Path | None = None) -> dict:
    section = load_policy(policy_path).get(name, {})
    if not isinstance(section, dict):
        raise PolicyError(f"policy section {name!r} is not an object")
    return section


def _int_value(section: dict, key: str, default: int, section_name: str) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolicyError(f"policy {section_name}.{key} must be an integer, got {value!r}")
    return int(value)


def _float_value(section: dict, key: str, default: float, section_name: str) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyError(f"policy {section_name}.{key} must be a number, got {value!r}")
    return float(value)


def orchestrator_defaults(policy_path: Path | None = None) -> OrchestratorLimits:
    """Operational limits for MangoMASOrchestrator; policy `orchestrator` block."""
    section = _section("orchestrator", policy_path)
    resolved: OrchestratorLimits = {
        "max_iterations": _int_value(section, "max_iterations", 10, "orchestrator"),
        "api_timeout_sec": _int_value(section, "api_timeout_sec", 300, "orchestrator"),
        "tool_timeout_sec": _int_value(section, "tool_timeout_sec", 30, "orchestrator"),
        "max_command_bytes": _int_value(section, "max_command_bytes", 8192, "orchestrator"),
        "max_healing_retries": _int_value(section, "max_healing_retries", 3, "orchestrator"),
        # Captured-output ceiling for the process backend (a containment control:
        # an unbounded capture becomes a prompt, a signal-sink entry and an HTTP
        # body). Was an unlinked 64 KiB literal in process_backend.py
        # (tech-debt-hardening-plan R-TDH-16).
        "max_output_bytes": _int_value(section, "max_output_bytes", 65536, "orchestrator"),
    }
    _log_resolution("orchestrator", resolved, policy_path)
    return resolved


def nemotron_defaults(policy_path: Path | None = None) -> NemotronDefaults:
    """Request defaults for the Nemotron bridge; policy `nemotron` block."""
    section = _section("nemotron", policy_path)
    resolved: NemotronDefaults = {
        "temperature": _float_value(section, "temperature", 0.2, "nemotron"),
        # Was a literal 0.7 in the Node client and absent from the Python
        # payload entirely -- the two stacks sampled differently against the
        # same endpoint. One key, both readers (NEXT_STEPS.md NS-16).
        "top_p": _float_value(section, "top_p", 0.7, "nemotron"),
        "max_tokens": _int_value(section, "max_tokens", 4096, "nemotron"),
        "timeout_ms": _int_value(section, "timeout_ms", 30000, "nemotron"),
        "max_retries": _int_value(section, "max_retries", 0, "nemotron"),
    }
    _log_resolution("nemotron", resolved, policy_path)
    return resolved


def max_tool_calls_per_task(policy_path: Path | None = None) -> int:
    """Cumulative tool-call budget per agent task; policy `agent_defaults` block."""
    resolved = _int_value(
        _section("agent_defaults", policy_path), "max_tool_calls_per_task", 100, "agent_defaults"
    )
    _log_resolution("agent_defaults", {"max_tool_calls_per_task": resolved}, policy_path)
    return resolved


def langgraph_defaults(policy_path: Path | None = None) -> LangGraphDefaults:
    """LangGraph orchestration-graph tuning; policy `langgraph` block."""
    section = _section("langgraph", policy_path)
    resolved: LangGraphDefaults = {
        "recursion_limit": _int_value(section, "recursion_limit", 50, "langgraph"),
        "max_concurrency": _int_value(section, "max_concurrency", 3, "langgraph"),
        "plan_divergence_threshold": _float_value(
            section, "plan_divergence_threshold", 0.35, "langgraph"
        ),
    }
    _log_resolution("langgraph", resolved, policy_path)
    return resolved


def coverage_defaults(policy_path: Path | None = None) -> CoverageThresholds:
    """Coverage gate thresholds consumed outside coverage_gate.py; policy `coverage` block.

    coverage_gate.py itself deliberately does not import this (policy-single-source.md's
    standalone-stdlib decision); this accessor is for other callers, such as GraphPolicy,
    that already depend on harness.shared and would otherwise read the section unvalidated.
    """
    section = _section("coverage", policy_path)
    resolved: CoverageThresholds = {
        "lines": _int_value(section, "lines", 90, "coverage"),
        "branches": _int_value(section, "branches", 80, "coverage"),
    }
    _log_resolution("coverage", resolved, policy_path)
    return resolved


def coverage_optional_extras(policy_path: Path | None = None) -> dict[str, dict]:
    """Optional extras whose tests a CI leg may deselect; policy `coverage.optional_extras`.

    Each entry maps an extra's name to ``import_name`` (what a leg lacking the
    extra cannot import), ``deselect_env`` (the variable that leg sets to "1";
    conftest.py deselects the extra's marked tests on it and coverage_gate.py
    waives the per-file floor for the extra's modules on it) and
    ``path_prefixes`` (those modules). One key, three readers (DEC-028).
    Absent block: {}. Malformed block: PolicyError.
    """
    extras = _section("coverage", policy_path).get("optional_extras", {})
    if not isinstance(extras, dict):
        raise PolicyError("policy coverage.optional_extras must be an object keyed by extra name")
    result: dict[str, dict] = {}
    for name, spec in extras.items():
        if not isinstance(spec, dict):
            raise PolicyError(f"policy coverage.optional_extras[{name!r}] must be an object")
        import_name, deselect_env, prefixes = (
            spec.get("import_name"), spec.get("deselect_env"), spec.get("path_prefixes")
        )
        if not isinstance(import_name, str) or not import_name or not isinstance(deselect_env, str) or not deselect_env:
            raise PolicyError(
                f"policy coverage.optional_extras[{name!r}] import_name and deselect_env must be non-empty strings"
            )
        if not isinstance(prefixes, list) or not prefixes or any(not isinstance(p, str) or not p for p in prefixes):
            raise PolicyError(
                f"policy coverage.optional_extras[{name!r}].path_prefixes must be a non-empty list of strings"
            )
        result[name] = {"import_name": import_name, "deselect_env": deselect_env, "path_prefixes": tuple(prefixes)}
    return result


def agent_defaults(policy_path: Path | None = None) -> dict:
    """Agent delegation/parallelism limits; policy `agent_defaults` block.

    Returns only the integer tuning values other modules construct from; the
    non-numeric keys in this section (approval/evidence lists, the
    deny_unclassified_side_effects flag) are read directly by validate_policy.py
    and test_policy_consistency.py and have no numeric-default shape for
    _int_value/_float_value to validate.
    """
    section = _section("agent_defaults", policy_path)
    return {
        "max_delegation_depth": _int_value(section, "max_delegation_depth", 2, "agent_defaults"),
        "max_parallel_subagents": _int_value(section, "max_parallel_subagents", 6, "agent_defaults"),
    }


def lats_defaults(policy_path: Path | None = None) -> dict:
    """LATS/MCTS search tuning; policy `lats` block."""
    section = _section("lats", policy_path)
    return {
        "max_budget": _int_value(section, "max_budget", 10, "lats"),
        "exploration_weight": _float_value(section, "exploration_weight", 1.414, "lats"),
    }
