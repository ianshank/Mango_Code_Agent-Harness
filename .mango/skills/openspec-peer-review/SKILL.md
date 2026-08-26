---
name: openspec-peer-review
description: >
  Objective peer review of an OpenSpec architecture proposal, assessing it from
  the perspectives of Architecture, SDLC, QA, and Product. Use this skill when
  validating a plan before proceeding to code execution.
validator_version: '2.0'
compatibility: python>=3.10
version: 1.0.0
---

# openspec-peer-review

This skill is designed to subject an architectural proposal to rigorous cross-functional review.
Instead of a single "looks good to me", it forces the agent to adopt multiple personas and
aggressively stress-test the design.

## 1. Personas Evaluated

- **Architect**: Are the system boundaries respected? Is the dependency graph acyclic?
- **SDLC / CI Lead**: Are the testing gates realistic? Can this be deployed safely?
- **QA Director**: How are edge cases handled? Is it deterministic?
- **Product Manager**: Does this actually solve the user's intent?

## 2. Usage

When formulating a plan, first feed the draft plan through this persona-review matrix.
Log any `knowledge_gap_log` findings if a persona identifies a critical missing piece of context.
Only proceed to execution once all personas sign off.
