# Security Policy

## Reporting a vulnerability

Please report suspected security issues privately via GitHub's
[private vulnerability reporting](https://github.com/ianshank/Mango_Code_Agent-Harness/security/advisories/new)
for this repository, rather than opening a public issue. Include:

- The affected file(s)/gate(s) and, if applicable, the invariant involved (see `harness/CONTRACT.md`).
- Steps to reproduce, ideally against a clean clone.
- The impact you believe it has (e.g. a fail-closed gate that fails open, a
  protected-path bypass, a credential leak in logs or errors).

You should receive an acknowledgement within a few business days.

## What's in scope

This repository is a governance/agent-harness kernel, not an end-user
application — the highest-value reports are usually about the governance
kernel itself:

- A gate in `harness/shared/`, `harness/shared/governance/`, or
  `harness/control-plane/` that fails **open** instead of closed (silently
  weakening a policy on malformed/missing input rather than raising or
  denying) — see `harness/CONTRACT.md`'s invariant list for what each gate
  is supposed to guarantee.
- A way to bypass `protected_paths` enforcement, the secret scan (INV-1), or
  the write/command policy enforced by `ExecutionBroker`/`write_policy.py`.
- A credential or secret that reaches logs, error messages, or a committed
  file (`harness/shared/debug_dump.py` and `validate_invariants.py`'s
  `check_hardcoded_secrets` exist specifically to prevent this class).

## What the runtime governance does and does not guarantee

The execution path an agent's `run_command` takes (`ExecutionBroker` →
`ProcessBackend`, `harness/shared/governance/broker.py`) **contains but does
not isolate**. It grades the command against an allowlist, checks the acting
role holds the graded action, applies the write policy to every path the
command would create, pins the working directory, bounds the runtime, caps the
output and strips credentials from the child environment. It confines neither
the filesystem nor the network: a process it starts can still read and write
any file the harness's own user can, and can still open sockets (DEC-010,
INV-13 in `harness/CONTRACT.md`).

The direct doors are shut: `read_file .env`, `write_file Makefile`,
`write_file GNUmakefile`, `curl`, `make -f <other file>` and `pnpm exec
<arbitrary program>` are all refused for every role. **The indirect door is
open and known.** Executing a workspace script (`python3 forge.py`, `pytest`)
is a permitted action, and the script it runs is not governed: it can read the
on-disk `.env`, write any protected file, install a git hook, and reach the
network. What the harness now guarantees is narrower than prevention — the
verdict cannot be forged that way. `VerificationRunner` records the digest of
every `protected_paths` file before the first agent turn and refuses to grade
(`BLOCKED`, `enforcement_tampered`, naming the file) if any of them changed,
appeared or vanished since; the set is checked again after the verification
command exits, so a background process that rewrites a file between the check
and `make` reading it is caught if the change persists. A rewrite that is
restored before the second check (swap-and-restore inside the run) is not —
that needs an immutable snapshot or OS isolation of the backend, and is a
known, accepted residual until then. That is detection after the fact, not
containment of the script. OS isolation of the process backend (container/namespace, with
`.git`, `.mango`, `.env` and the enforcement files masked or read-only, and no
network) is the fix, and is a later capability profile that this repository's
CI runners cannot yet exercise. Reports that widen the indirect door beyond
what this paragraph already states — a way to forge the verdict *despite* the
digest check, or to reach a credential through a door listed above as shut —
are the ones to file.

## Existing automated scanning

This repository already runs `gitleaks` (working tree, plus the commit history
of the current branch — `--log-opts="HEAD"`, DEC-014; other refs are not
scanned) and `pip-audit`/`osv-scanner` (dependency vulnerabilities) on every
PR — see `.github/workflows/python-package.yml`. A report that reproduces
something these gates should have caught, but didn't, is especially useful: it
usually points at a real gap in the gate itself (see
`harness/node/.governance/decision-log.md` for examples of exactly this class
of finding, e.g. DEC-014).

## Supported versions

This project does not currently maintain multiple released branches; security
fixes land on `main`.
