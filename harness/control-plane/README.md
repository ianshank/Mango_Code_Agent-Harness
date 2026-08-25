# Independent Governance Control Plane

These files are reference deployment artifacts. **Do not rely on the copy inside the governed project as the root of trust.** Publish the verifier, approved policy bundle and required workflow from an independently administered repository/service, pin that repository by commit, and require it through organization rulesets.

`verify_repository.py` compares the governed repository's policy and agent-policy SHA-256 values to the protected bundle before project-local conformance code runs. `tool_broker_reference.py` illustrates action-specific default-deny authorization; production implementations should additionally authenticate agent identity, bind approvals to exact resources/destinations, enforce expiry/nonces, and emit side-effect evidence.
