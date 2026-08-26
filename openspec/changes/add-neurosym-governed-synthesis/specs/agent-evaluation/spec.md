# Delta for Agent Evaluation

## ADDED Requirements

### Requirement: Strategy ablation
The evaluation harness MUST run equivalent task suites against:
- a single-shot baseline;
- deterministic verification only;
- bounded search with repair.

#### Scenario: LATS rollout decision
- GIVEN a completed evaluation run on the approved benchmark suite
- WHEN bounded LATS does not exceed the configured quality-per-cost threshold
- THEN the deployment configuration MUST keep LATS disabled by default

### Requirement: Reproducible task evidence
Every benchmark result MUST include task version, model/provider identifiers, policy-bundle digest, execution backend version, and random seed where used.
