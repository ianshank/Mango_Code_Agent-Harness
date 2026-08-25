# Project Governance Charter

**Charter v2.0**

## Constraints

- **C-GOV-1 — Repository conformance:** repository conformance MUST be evaluated through the policy-defined named gate contract; the project repository is not its own root of trust.
- **R-GOV-2 — Execution authority:** unapproved external destinations and high-risk agent side effects MUST be denied at execution time by controls independent of a later CI result.

## Authority

The external Tool Broker / PDP and organization-required workflow/ruleset are independently administered. Project-local guards provide fast enforcement for modeled operations. Project CI produces authoritative conformance evidence for the evaluated commit but does not claim to prevent a network transfer that already occurred.
