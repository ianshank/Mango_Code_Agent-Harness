"""Derive an active role's tool exposure from the declared authority model.

``harness/shared/agent-policy.json`` declares ``allowed_actions`` for each of the
seven canonical roles, and ``harness/control-plane/tool_broker_reference.py``
implements the check (``action not in role['allowed_actions']`` -> DENY). Nothing
on the live path consulted either: ``execute_agent`` passed no ``tools=``
argument for the reasoner or the verifier, so both received the full schema.

The consequence was that the **verifier** held ``write_file``. Every canonical
contract it maps to denies implementation changes -- ``peer-reviewer.md`` denies
"changing the implementation being judged", ``test-eval.md`` denies "product
implementation changes" -- so the role that judges the work could edit it, and
could write the hook that runs on the host at the end of its own turn.

This module closes that by deriving exposure from the policy rather than
restating it. Nothing here hard-codes which role gets which tool.

Spec: ``docs/specs/agent-containment.md`` (R-AC-8).
"""

from __future__ import annotations

import json
import typing
from pathlib import Path

#: Resolved next to this module so the authority model travels with the installed
#: harness rather than being read out of the tree the agent is working in.
DEFAULT_AGENT_POLICY_PATH = Path(__file__).resolve().parent / "agent-policy.json"

#: The 3-active -> 7-canonical mapping, authoritative in ``.mango/agents/README.md``
#: and until now expressed only as prose there. ``test_agent_harness_wiring.py``
#: pins the active set; this pins what each active role inherits.
ACTIVE_TO_CANONICAL: typing.Mapping[str, tuple[str, ...]] = {
    "planner": ("orchestrator", "spec-analyst"),
    "nemotron-reasoner": ("implementer",),
    "verifier": ("test-eval", "peer-reviewer", "security-reviewer", "release-auditor"),
}

#: The canonical role an active role *executes as* when the broker asks the
#: authority model for a verdict. The active roles are not themselves declared in
#: `agent-policy.json`, and adding them would be the agent's own governing policy
#: gaining an execution grant -- a change that also requires new canonical
#: contract files to satisfy the bidirectional role/contract equality gates.
#: Choosing the narrowest existing contract that still covers what the role must
#: do keeps execution authority no wider than the role's tool exposure, which
#: `test_execution_identity_is_no_wider_than_the_role` pins.
EXECUTION_IDENTITY: typing.Mapping[str, str] = {
    "planner": "orchestrator",
    "nemotron-reasoner": "implementer",
    "verifier": "test-eval",
}

#: The action each tool exercises. This is a reviewed decision rather than a
#: derivation -- the policy declares actions, the orchestrator declares tools, and
#: something has to join them -- so it is declared once, here, with the reason.
#: ``test_agent_authority.py`` pins that every declared tool appears exactly once,
#: so a tool added to the registry without an action cannot quietly default to
#: "available to everyone".
TOOL_REQUIRED_ACTION: typing.Mapping[str, str] = {
    # Writes a file into the workspace: the implementer action.
    "write_file": "write",
    # Runs a command. `test_execute` is the narrowest declared action that covers
    # running the repository's own gates, which is what the reasoner and verifier
    # personas are instructed to do.
    "run_command": "test_execute",
    # The meta-tools record what the agent could not determine. They are the
    # declared alternative to hallucinating, they touch only the memory store, and
    # every canonical role holds `read`, so every role keeps them.
    "knowledge_gap_log": "read",
    "hypothesis_register": "read",
}


def load_agent_policy(policy_path: Path | None = None) -> dict[str, typing.Any]:
    """Return the parsed authority model. A policy that cannot be read raises."""
    path = policy_path or DEFAULT_AGENT_POLICY_PATH
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"agent policy at {path} is not a JSON object")
    return parsed


def allowed_actions(active_role: str, policy_path: Path | None = None) -> frozenset[str]:
    """Actions ``active_role`` may take without a recorded human approval.

    The union across the canonical roles it maps to, minus each role's own
    ``human_approval_required_for``. The subtraction is the point: the
    ``release-auditor`` contract grants ``external_write`` and
    ``production_change`` *and* requires human approval for both, so a plain union
    would hand the verifier production authority on the strength of a role whose
    whole purpose is that a human signs first.
    """
    canonical = ACTIVE_TO_CANONICAL.get(active_role)
    if canonical is None:
        # An unknown role gets nothing. Defaulting to the full schema is how the
        # verifier came to hold `write_file` in the first place.
        return frozenset()

    policy = load_agent_policy(policy_path)
    by_id = {role["id"]: role for role in policy.get("agents", []) if isinstance(role, dict) and "id" in role}

    granted: set[str] = set()
    for role_id in canonical:
        role = by_id.get(role_id)
        if role is None:
            continue
        needs_approval = set(role.get("human_approval_required_for", []))
        granted |= set(role.get("allowed_actions", [])) - needs_approval
    return frozenset(granted)


def tools_for_role(
    active_role: str,
    tools: typing.Sequence[dict[str, typing.Any]],
    policy_path: Path | None = None,
) -> list[dict[str, typing.Any]]:
    """Filter ``tools`` to those ``active_role`` is permitted to exercise.

    A tool with no declared action is withheld, not granted: an unmapped tool is
    one nobody has decided about, and the safe reading of an undecided grant is
    "no".
    """
    permitted = allowed_actions(active_role, policy_path)
    kept = []
    for tool in tools:
        name = tool.get("function", {}).get("name", "")
        required = TOOL_REQUIRED_ACTION.get(name)
        if required is not None and required in permitted:
            kept.append(tool)
    return kept


def execution_identity(active_role: str) -> str:
    """The canonical role id the broker evaluates ``active_role`` against.

    An unknown active role resolves to a name no policy declares, so the decision
    point denies it as an unknown identity rather than defaulting to a permissive
    one.
    """
    return EXECUTION_IDENTITY.get(active_role, f"unmapped-active-role:{active_role}")
