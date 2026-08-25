# Governed agent roles

These role contracts mirror `shared/agent-policy.json`. They describe responsibilities and evidence obligations; executable authorization remains in the external Tool Broker / PDP. Delegation never transfers permissions from parent to child.

- `orchestrator.md` — plans and delegates only.
- `spec-analyst.md` — requirements and acceptance criteria.
- `implementer.md` — scoped code/config edits and local tests.
- `test-eval.md` — test/eval execution and evidence.
- `security-reviewer.md` — threat, dependency, secret and policy review.
- `peer-reviewer.md` — independent correctness/conformance review.
- `release-auditor.md` — release evidence; external write/production changes require human approval.
