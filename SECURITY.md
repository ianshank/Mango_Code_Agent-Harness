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

## Existing automated scanning

This repository already runs `gitleaks` (working tree + full commit history)
and `pip-audit`/`osv-scanner` (dependency vulnerabilities) on every PR — see
`.github/workflows/python-package.yml`. A report that reproduces something
these gates should have caught, but didn't, is especially useful: it usually
points at a real gap in the gate itself (see `harness/node/.governance/decision-log.md`
for examples of exactly this class of finding, e.g. DEC-014).

## Supported versions

This project does not currently maintain multiple released branches; security
fixes land on `main`.
