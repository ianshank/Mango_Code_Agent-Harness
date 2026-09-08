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

from harness.shared.policy_defaults import (
    EXECUTION_ROUTING_STATES as EXECUTION_ROUTING_STATES,
)
from harness.shared.policy_defaults import agent_defaults as agent_defaults
from harness.shared.policy_defaults import agent_memory_defaults as agent_memory_defaults
from harness.shared.policy_defaults import coverage_defaults as coverage_defaults
from harness.shared.policy_defaults import coverage_optional_extras as coverage_optional_extras
from harness.shared.policy_defaults import evidence_defaults as evidence_defaults
from harness.shared.policy_defaults import execution_routing as execution_routing
from harness.shared.policy_defaults import gate_floors as gate_floors
from harness.shared.policy_defaults import langgraph_defaults as langgraph_defaults
from harness.shared.policy_defaults import lats_defaults as lats_defaults
from harness.shared.policy_defaults import max_tool_calls_per_task as max_tool_calls_per_task
from harness.shared.policy_defaults import nemotron_defaults as nemotron_defaults
from harness.shared.policy_defaults import orchestrator_defaults as orchestrator_defaults
from harness.shared.policy_io import POLICY_PATH as POLICY_PATH
from harness.shared.policy_io import AgentMemoryLimits as AgentMemoryLimits
from harness.shared.policy_io import CoverageThresholds as CoverageThresholds
from harness.shared.policy_io import GateFloors as GateFloors
from harness.shared.policy_io import LangGraphDefaults as LangGraphDefaults
from harness.shared.policy_io import NemotronDefaults as NemotronDefaults
from harness.shared.policy_io import OrchestratorLimits as OrchestratorLimits
from harness.shared.policy_io import PolicyError as PolicyError
from harness.shared.policy_io import _log_resolution as _log_resolution
from harness.shared.policy_io import _Section as _Section
from harness.shared.policy_io import _section as _section
from harness.shared.policy_io import load_policy as load_policy
from harness.shared.policy_io import policy_file_is_absent as policy_file_is_absent
from harness.shared.policy_io import resolve_policy_path as resolve_policy_path

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
