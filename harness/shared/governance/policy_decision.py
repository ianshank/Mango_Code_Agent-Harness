"""The policy decision point, in process.

``ExecutionBroker`` shelled out to ``harness/control-plane/tool_broker_reference.py``
with ``sys.executable``, on the host, **before** ``check_command`` ran. Two
problems, both structural rather than incidental:

* the script sits inside the repository, which is the agent's workspace in the
  deployed path, so an agent could replace it with ``print("ALLOW")`` and every
  subsequent verdict was its own; and
* the call was guarded by ``if _PDP_PATH.exists() and _POLICY_PATH.exists():``,
  so a missing file skipped the verdict entirely rather than denying.

The decision itself is nine lines of set membership. Running it as a subprocess
bought nothing and cost a code-execution primitive, so it is evaluated here from
the parsed policy. ``tool_broker_reference.py`` remains as the reference
implementation an external broker mirrors, and ``test_policy_decision.py`` pins
that the two agree.

``harness/CONTRACT.md`` is unchanged on authority: the authoritative broker is
still external and administered outside this repository. This is the local
fast control, and it fails closed.

Spec: ``docs/specs/agent-containment.md`` (R-AC-11).
"""

from __future__ import annotations

import typing

ALLOW = "ALLOW"
DENY = "DENY"


class Decision(typing.NamedTuple):
    """A verdict and the reason for it. The reason reaches the refusal message and
    the evidence record, so an operator can tell a policy denial from a fault."""

    verdict: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.verdict == ALLOW


def decide(
    agent_id: str,
    action: str,
    policy: typing.Mapping[str, typing.Any],
    human_approved: bool = False,
) -> Decision:
    """Evaluate one request against the authority model.

    Mirrors ``tool_broker_reference.py`` exactly, including the order of its three
    denials, so the reference and the live path cannot diverge silently.
    """
    agents = policy.get("agents")
    if not isinstance(agents, list):
        return Decision(DENY, "the authority model declares no agents")

    roles = {a["id"]: a for a in agents if isinstance(a, dict) and "id" in a}
    role = roles.get(agent_id)
    if role is None:
        return Decision(DENY, f"unknown agent identity: {agent_id}")

    if action not in role.get("allowed_actions", []):
        return Decision(DENY, f"action {action!r} is not granted to {agent_id}")

    if action in role.get("human_approval_required_for", []) and not human_approved:
        return Decision(DENY, f"action {action!r} requires human approval")

    return Decision(ALLOW, f"{agent_id} may {action}")
