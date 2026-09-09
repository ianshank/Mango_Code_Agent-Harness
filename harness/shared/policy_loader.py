"""Single source of truth for operational values in governance-policy.json.

This module is the public facade: IO helpers live in ``policy_io`` and typed
accessors in ``policy_defaults``. Callers keep importing this module.

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

try:
    from harness.shared import policy_defaults as _defaults
    from harness.shared import policy_io as _io
except ImportError:  # `python harness/shared/check_py_compat.py` (sys.path[0] is this dir)
    import policy_defaults as _defaults  # type: ignore[no-redef]
    import policy_io as _io  # type: ignore[no-redef]

EXECUTION_ROUTING_STATES = _defaults.EXECUTION_ROUTING_STATES
agent_defaults = _defaults.agent_defaults
agent_memory_defaults = _defaults.agent_memory_defaults
coverage_defaults = _defaults.coverage_defaults
coverage_optional_extras = _defaults.coverage_optional_extras
evidence_defaults = _defaults.evidence_defaults
execution_routing = _defaults.execution_routing
gate_floors = _defaults.gate_floors
langgraph_defaults = _defaults.langgraph_defaults
lats_defaults = _defaults.lats_defaults
max_tool_calls_per_task = _defaults.max_tool_calls_per_task
nemotron_defaults = _defaults.nemotron_defaults
orchestrator_defaults = _defaults.orchestrator_defaults
POLICY_PATH = _io.POLICY_PATH
AgentMemoryLimits = _io.AgentMemoryLimits
CoverageThresholds = _io.CoverageThresholds
GateFloors = _io.GateFloors
LangGraphDefaults = _io.LangGraphDefaults
NemotronDefaults = _io.NemotronDefaults
OrchestratorLimits = _io.OrchestratorLimits
PolicyError = _io.PolicyError
_log_resolution = _io._log_resolution
_Section = _io._Section
_section = _io._section
load_policy = _io.load_policy
policy_file_is_absent = _io.policy_file_is_absent
resolve_policy_path = _io.resolve_policy_path

__all__ = [
    "POLICY_PATH",
    "AgentMemoryLimits",
    "CoverageThresholds",
    "EXECUTION_ROUTING_STATES",
    "GateFloors",
    "LangGraphDefaults",
    "NemotronDefaults",
    "OrchestratorLimits",
    "PolicyError",
    "agent_defaults",
    "agent_memory_defaults",
    "coverage_defaults",
    "coverage_optional_extras",
    "evidence_defaults",
    "execution_routing",
    "gate_floors",
    "langgraph_defaults",
    "lats_defaults",
    "load_policy",
    "max_tool_calls_per_task",
    "nemotron_defaults",
    "orchestrator_defaults",
    "policy_file_is_absent",
    "resolve_policy_path",
]
