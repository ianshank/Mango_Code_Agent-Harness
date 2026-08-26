# Delta for Governance Control Plane

## ADDED Requirements

### Requirement: Policy-first candidate authorization
The control plane MUST issue a deterministic policy verdict before a synthesis candidate can be executed, scored, or marked verified.

#### Scenario: Policy denial prunes a candidate
- GIVEN a candidate whose AST violates a prohibited-import policy
- WHEN the control plane evaluates the candidate
- THEN it returns `DENY`
- AND the runtime MUST NOT execute the candidate
- AND the candidate score MUST be terminally ineligible

### Requirement: Evidence-bound verdicts
Every policy verdict MUST reference the policy-bundle digest, input digest, timestamp, and evidence identifier.

#### Scenario: Reviewer inspects a denial
- GIVEN a policy verdict with `DENY`
- WHEN a reviewer opens its evidence bundle
- THEN the reviewer can identify the exact policy bundle and candidate input used
