---
description: The schema every docs/decisions/DEC-*.md must satisfy, and the index regeneration a new record requires.
paths:
  - "docs/decisions/**/*.md"
---

# Adding a decision record

`docs/decisions/` is the governance decision log and the source of truth for
the identifiers the rest of the repository cites. `harness/shared/decision_records.py`
validates every file; `make validate` runs it.

## Schema

Frontmatter, all keys required and non-empty:

```yaml
---
id: DEC-070
title: "one line, quoted"
status: accepted
date: 2026-09-19
supersedes: []
superseded_by: null
owners: ["governance-maintainers"]
---
```

- `status` is one of `accepted`, `superseded`, `deprecated`, `proposed`.
- `supersedes` is a list whose entries match `DEC-\d+`.
- **The filename must equal the id**: `DEC-070.md` for `id: DEC-070`.
- Three headings are required, in this order: `## Context`, `## Decision`,
  `## Consequences`.

## The step that is easy to miss

`docs/decisions/index.md`, `docs/decisions/index.json` and
`harness/node/.governance/decision-log.md` are **generated**. Adding a record
without regenerating them fails `make validate` with `decision index drift`:

```
make decision-index          # regenerate
make decision-index-check    # verify, no writes
```

`harness/node/.governance/decision-log.md` is a protected path, so a new
decision record drags a protected-path change into the diff. That needs
`ALLOW_GITHUB_CHANGES=1`, the `infra-reviewed` label and an attestation row —
plan for it rather than discovering it in CI.

## Why there is no AGENTS.md here

`docs/` refuses loose files at its root and its subdirectories carry their own
content contracts, so a per-directory document would have to satisfy a gate
written for something else. This rule file does the same job (DEC-070).
