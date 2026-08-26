# Delta for Code Execution

## ADDED Requirements

### Requirement: Default-deny execution capabilities
The execution broker MUST deny network, host filesystem, subprocess, credential, and device access unless an explicitly versioned capability profile permits them.

#### Scenario: Candidate requests network access
- GIVEN a candidate executed under the `unit-test` profile
- WHEN it attempts outbound network access
- THEN the broker MUST deny the request
- AND return a normalized sandbox violation

### Requirement: No host-process fallback
The execution broker MUST NOT fall back to direct host execution when its preferred sandbox backend is unavailable.

#### Scenario: Sandbox backend unavailable
- GIVEN the configured sandbox backend cannot start
- WHEN a candidate requires execution
- THEN the broker MUST return `BLOCKED`
- AND MUST NOT execute the candidate on the host
