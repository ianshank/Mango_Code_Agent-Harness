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
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parent / "governance-policy.json"


class PolicyError(ValueError):
    """A policy file exists but cannot be used. Never swallowed."""


def load_policy(policy_path: Path | None = None) -> dict:
    """Return the parsed policy, or {} when no policy file exists (adopter path).

    A present-but-unparseable policy raises PolicyError (fail-closed).
    """
    path = POLICY_PATH if policy_path is None else policy_path
    if not path.is_file():
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
