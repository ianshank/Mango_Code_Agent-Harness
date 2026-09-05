## Summary
This pull request brings Windows and cross-platform test parity across the entire Python (3,797 passing tests) and Node (120 passing tests across 24 suites) test suites, establishes strict zero-skip waiver verification with schema validation (`make verify-skip-waivers`), resolves IDE module resolution (`pyrightconfig.json`), aligns documentation and C4 architecture truth to v2.4.0, and establishes reusable engineering skills (`skip-waiver-auditor`, `code-hygiene-scanner`).

## Key Changes
- **Windows Portability & Cross-Platform Parity:**
  - Hardened Starlette/AnyIO/asyncio loopback handling under `--disable-socket` on win32 (DEC-059).
  - Documented and approved GNU Make and platform socket exemptions in governance log (DEC-057, DEC-058).
  - Maintained canonical architecture in `harness/shared/langgraph/nodes.py` (470 lines, 0 IDE import errors).
- **Zero-Skip & Governance Hardening:**
  - Pure Python `verify-skip-waivers` target validates schema integrity of all 24 waivers in `skip-waivers.json`.
  - Added DEC-057 through DEC-059 to `harness/node/.governance/decision-log.md` and synced with `harness/node/agents/GOVERNANCE_SKILL.md`.
- **AQA & Regression Testing:**
  - Expanded `test_windows_portability_regression.py` (35 tests covering fnmatch anti-patterns, case sensitivity, make-guard audits, AST decision checks).
  - Added NS-21 and NS-17 rollback pin suites ensuring zero architecture regression.
- **Hygiene & Standards:**
  - 100% compliant with ruff check, ruff format, mypy strict, vulture dead-code detection, Python 3.9 AST compatibility.
  - Coverage gate: 99.00% lines (>= 90.00% floor), 97.82% branches (>= 80.00% floor), 80/80 files meeting floor with 0 waivers.

## Protected Path Attestation

| Protected path | Why this change touches it |
| --- | --- |
| `.mango/skills/agent-memory-manager/SKILL.md` | Documents NS-17 simplified baseline and rule 4 invariant |
| `Makefile` | Adds verify-skip-waivers target for cross-platform schema verification (DEC-058/DEC-059) |
| `harness/node/.governance/decision-log.md` | Records DEC-057, DEC-058, DEC-059 for Windows portability and GNU Make skip approvals |
| `harness/node/agents/GOVERNANCE_SKILL.md` | Syncs DEC-057, DEC-058, DEC-059 decision summaries per validate_governance_docs gate |
| `harness/shared/validate_invariants.py` | Restores canonical size budgets and secret scanning bounds |

## Verification
- `ruff check .`: 0 errors
- `ruff format --check .`: 388 files formatted
- `mypy`: 0 errors across 238 source files
- `pytest`: 3,797 passed, 129 skipped (100% accounted for in skip-waivers.json)
- `coverage_gate.py`: 99.00% lines, 97.82% branches
- `pnpm test`: 24/24 suites passed (120 passed, 3 skipped with zero-skip verified)
- `validate_invariants.py`: PASSED (0 hardcoded secrets, all files <= 500 lines, test modules <= 700 lines)
