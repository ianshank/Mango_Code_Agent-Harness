# Peer-review remediation matrix — v2.0

> Moved from `harness/PEER-REVIEW-REMEDIATION.md` (tech-debt hardening plan R-TDH-24); file names in the evidence
> column are relative to `harness/`.

| Review finding | v2 remediation | Regression evidence |
|---|---|---|
| `make remotes` could pass by printing an allowlist | `remotes` enumerates every configured Git push URL and validates each through one shared normalizer | golden remote vectors; fixture `make remotes` |
| CI was incorrectly described as preventing prior exfiltration | authority model split into runtime Tool Broker/PDP + native pre-push versus CI conformance/evidence | `CONTRACT.md`; C4 diagrams |
| JUnit listener exception could not fail the run | listener only records TSV evidence; Gradle `verifyNoSkippedTests` performs the failing assertion | self-test checks no listener throw and verifier wiring |
| Node skip waiver was file-wide | Vitest JSON is evaluated after execution against exact file + full test-name waivers | exact-waiver self-test |
| Skip IDs could be fabricated | all waivers resolve to the decision log and expire; JUnit reason must cite the exact waiver decision | fabricated `DEC-999` negative test |
| JVM/Node skip semantics drifted | both use the byte-identical `verify_zero_skips.py`; JUnit waiver is exact unique-ID + display-name | shared-kernel byte-identity + exact-waiver tests |
| Mutable repository could weaken its own judge | independently deployable verifier pins policy, agent policy, Makefile, CI and security-critical implementation digests before project-local gates run | external verifier pass + tampered-Makefile deny test |
| Uninstantiated PreToolUse guard could fail open | security placeholders removed; malformed dangerous input and unmodeled shell/config forms return BLOCK | guard allow/deny/malformed tests |
| TypeScript config contained fake comment properties | valid `tsconfig.json`; comments moved out of compiler-option keys | tsconfig regression test + JSON parse |
| Vitest 4 coverage config used removed `coverage.all` | explicit `coverage.include` + per-file thresholds | Vitest config regression test |
| Gradle locking/verification was not actually active | `lockAllConfigurations()` + `LockMode.STRICT`; missing lockfile/wrapper/verification metadata are adoption/install blockers | JVM supply-chain self-test + adoption negative test |
| INV-5 covered only a subset of gates | shared policy declares the complete required target set; CI/meta-tests iterate that set | CI contract self-test |
| Remote canonicalization dropped ports/lowercased paths | default ports normalize away; significant ports remain; host is lowercase; path case is preserved | golden vector suite |
| Agent/sub-agent governance was missing | canonical policy + seven role contracts + bounded delegation, default deny, action-specific approval and evidence schema | agent policy/role tests + reference PDP tests |
| Human approval was too coarse | approval is attached to exact high-risk actions rather than the entire role | Tool Broker deny/approve/read test |
| Effective Git hooks path could diverge from `.git/hooks` | installer resolves Git's effective hooks path and refuses foreign-hook overwrite | custom `core.hooksPath` fixture test |
| Governed-path/initial-push handling was fragile | pre-push uses Git-provided URL, `ls-tree` on initial push, `diff` on updates, and loud governed-path warnings | shell/static checks + runtime remote fixtures |
| Strict spec validation could remain degraded forever | local structural fallback stays loud; CI sets `REQUIRE_STRICT_SPEC_VALIDATOR=1` and fails when strict tooling is absent | CI strict-mode self-test + strict-mode fixture tests |
| Governance skill/charter freshness differed by stack | one byte-identical validator checks charter version, review age and decision-log freshness | governance-doc validator on both stacks |
| Template artifacts/dependencies were ambiguous | adoption validator explicitly blocks unpinned actions, empty allowlist, missing external root, and missing stack lock/verification state | raw-template BLOCK + instantiated-fixture PASS |
| `guard-probe` could print BLOCK and still succeed | BLOCK now exits 2 | guard-probe regression + runtime fixture |
| Python reference was advertised but absent | v2 contract explicitly scopes this package to the supplied Node and JVM adapters; shared policy kernel is Python but no third stack is claimed | `README.md` / `CONTRACT.md` |
