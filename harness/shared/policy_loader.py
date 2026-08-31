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
import stat
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parent / "governance-policy.json"


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


def orchestrator_defaults(policy_path: Path | None = None) -> dict:
    """Operational limits for MangoMASOrchestrator; policy `orchestrator` block."""
    section = _section("orchestrator", policy_path)
    return {
        "max_iterations": _int_value(section, "max_iterations", 10, "orchestrator"),
        "api_timeout_sec": _int_value(section, "api_timeout_sec", 300, "orchestrator"),
        "tool_timeout_sec": _int_value(section, "tool_timeout_sec", 30, "orchestrator"),
        "max_command_bytes": _int_value(section, "max_command_bytes", 8192, "orchestrator"),
    }


def nemotron_defaults(policy_path: Path | None = None) -> dict:
    """Request defaults for the Nemotron bridge; policy `nemotron` block."""
    section = _section("nemotron", policy_path)
    return {
        "temperature": _float_value(section, "temperature", 0.2, "nemotron"),
        "max_tokens": _int_value(section, "max_tokens", 4096, "nemotron"),
        "timeout_ms": _int_value(section, "timeout_ms", 30000, "nemotron"),
        "max_retries": _int_value(section, "max_retries", 0, "nemotron"),
    }


def max_tool_calls_per_task(policy_path: Path | None = None) -> int:
    """Cumulative tool-call budget per agent task; policy `agent_defaults` block."""
    return _int_value(_section("agent_defaults", policy_path), "max_tool_calls_per_task", 100, "agent_defaults")


def langgraph_defaults(policy_path: Path | None = None) -> dict:
    """LangGraph orchestration-graph tuning; policy `langgraph` block."""
    section = _section("langgraph", policy_path)
    return {
        "recursion_limit": _int_value(section, "recursion_limit", 50, "langgraph"),
        "max_concurrency": _int_value(section, "max_concurrency", 3, "langgraph"),
        "plan_divergence_threshold": _float_value(
            section, "plan_divergence_threshold", 0.35, "langgraph"
        ),
    }
