# Delta for Neuro-Symbolic Synthesis

## ADDED Requirements

### Requirement: Bounded synthesis search
The runtime MAY use LATS only with explicit limits for depth, branching factor, inference count, wall-clock duration, and monetary/token budget.

#### Scenario: Search budget exhaustion
- GIVEN a search reaches its inference budget without a verified candidate
- WHEN the runtime evaluates the next expansion
- THEN it MUST stop
- AND return `FAILED` with the best evidence-backed candidate summary

### Requirement: Structured critique feedback
Failed policy, parser, compiler, test, and sandbox outcomes MUST be normalized into a versioned critique schema before another repair attempt is made.

#### Scenario: Compiler failure
- GIVEN a candidate produces a syntax error
- WHEN the compiler rejects the candidate
- THEN the runtime records error type, location, normalized message, and evidence ID
- AND supplies only the redacted structured critique to the next attempt
