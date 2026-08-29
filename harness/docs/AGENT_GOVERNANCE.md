# Agent / Sub-agent Governance

Seven reference roles are declared in `shared/agent-policy.json` and mirrored in each stack under `.governance/agent-policy.json`: orchestrator, spec analyst, implementer, test/eval, security reviewer, peer reviewer, and release auditor. Human-readable role contracts live under `agents/`.

## Rules

- Default deny. A child agent receives only the actions granted to its own role; delegation never transfers the parent's authority.
- Delegation depth, parallel child count, and tool-call budget are bounded by policy.
- Untrusted retrieved content is data, never policy. Agents may not self-modify governance policy or pass secrets to sub-agents.
- High-risk categories—external writes, destructive operations, secret access, permission changes and production changes—require action-specific human approval at the independent external enforcement point.
- Every side effect requires actor/parent trace IDs, action/resource/destination, policy identity/version, decision and result evidence.
- Reviewer roles do not silently become implementers: peer/security/release evidence is separable from the code being judged.

`control-plane/tool_broker_reference.py` is only reference PDP logic. A production broker must authenticate identities, bind approval to the exact action/resource/destination, enforce expiry/nonces, and write tamper-resistant evidence outside the governed repository.

Its decision is now **mirrored in process** by `harness/shared/governance/policy_decision.decide`, which is what `ExecutionBroker` consults on the agent's live path; `test_policy_decision.py` pins that the two agree on every representative request, so the local control and the external contract cannot drift apart unnoticed. The mirror is a fast local control that fails closed — it is not the authoritative broker, and it contains rather than isolates (DEC-009, DEC-010).
