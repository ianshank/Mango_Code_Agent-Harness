# Governance Decision Log

Format: `YYYY-MM-DD | ID | decision | owner`

2026-08-24 | DEC-000 | Template has no generated projections until an adopter configures mappings | template-maintainers
2026-08-26 | DEC-001 | Live smoke tests against remote NVIDIA NIM API are conditionally skipped when endpoints are rate-limited or unavailable | ai-maintainers
2026-08-27 | DEC-002 | protected_paths gains the agent control surface (CLAUDE.md, .claude/ and .mango/ hooks, skills, agent-policy, CONTRACT, pyproject, the policy publisher) and root-relative twins for the multi-stack layout; ~32% of historical commits would newly require the infra-reviewed label, accepted as the cost of gating what agents may change about their own permissions | governance-maintainers
2026-08-27 | DEC-003 | The five unbound .mango/hooks/ scripts stay dormant: .mango/settings.json is not the file Claude Code reads, so waking them would change tool-call behavior for every session on logic that has never executed; only the .claude/ SessionStart hook is live | governance-maintainers
2026-08-28 | DEC-004 | Unwired governance-policy keys are classified (DECLARED_NOT_YET_ENFORCED in test_policy_consistency.py) rather than deleted -- per-stack mirrors sit under root-of-trust and bundle digests, so removal is a rotation-sized change; the duplicated decision-ID grammar, agent_defaults limits, and gitleaks pin become cross-checked equalities; the stale unread harness/SHA256SUMS.txt manifest is deleted; Python coverage is enforced as two separate floors (lines and branches) by coverage_gate.py; build_policy_bundle.py joins digest-regen as the only regenerator of the bundle's top-level policy digests | governance-maintainers
