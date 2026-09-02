## Summary

<!-- What does this change do, and why? Link the spec under docs/specs/ for
     non-trivial changes (see CLAUDE.md: "For non-trivial changes, do not
     implement without one"). -->

## Validation

<!-- What did you run, and what did it report? `make pre-pr` is the full
     local gate (ci + review + cold mypy + audit + secrets). Paste the
     relevant PASS/FAIL lines, not just "all green". A verification claim
     is not evidence; the pasted output and the check runs on the pushed
     head are (CONTRIBUTING.md, DEC-024). -->

- [ ] `make ci` and `make lint-cold` tails pasted below (pinned tools: `python -m ruff` / `python -m mypy`)
- [ ] `secret-scan` and `dependency-audit` job runs linked (or `make audit` / `make secrets` tails pasted)
- [ ] For spec-driven work: acceptance criteria in `docs/specs/<name>.md` map to the checks above

```text
(paste the tails here)
```

## Protected-path attestation

<!-- Only include this section if `validate_invariants.py` / `make validate`
     reports this PR touches a protected path (see governance-policy.json's
     protected_paths). If none of your changed files match, delete this
     section entirely — an attestation for an unprotected change is noise.

     Run the `protected-path-attestation` skill to generate this table
     accurately (one row per protected file: what changed, why it's safe).
     Do not copy a previous PR's table — enumerate fresh against this diff. -->

| File | Change | Why it is safe |
|---|---|---|
| | | |

Once this table is complete and accurate, ask a maintainer to apply the
`infra-reviewed` label — that's what sets `ALLOW_GITHUB_CHANGES=1` in CI for
this PR. Applying the label to unblock a red check without an honest table
above defeats the invariant it exists to enforce.

## Backward compatibility

<!-- Does this change anything a caller could be relying on today (a
     function's default, a CLI flag, a schema, an exported name)? State it
     even if the answer is "no" — every spec in docs/specs/ carries this
     section for a reason. -->
