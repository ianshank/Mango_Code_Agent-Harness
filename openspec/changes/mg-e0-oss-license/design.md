# Design: MG-E0 OSS License

## Decision

Ship a single SPDX license: **MIT**.

## Why MIT (Critic binding)

- Matches SWE-ReX upstream (primary MG-E1 adapter candidate).
- Apache-2.0 patent grant remains available as a later change if Ian requires it; dual-licensing is out of scope for E0.
- One SPDX id in OpenSpec and packaging metadata; no dual declaration.

## Placement

| Artifact | Role |
|---|---|
| `LICENSE` at repo root | Canonical human-readable grant GitHub detects |
| `pyproject.toml` `[project].license = "MIT"` | Packaging / PyPI honesty |
| OpenSpec `oss-license` capability | Board kill criteria and archive trail |

## Out of scope mechanics

- No runtime harness modules change.
- No evidence-schema or isolation capability changes.
- No README rewrite beyond a one-line License pointer if a License section is absent and a sibling doc already expects one (prefer leave README alone if silent).

## Failure modes

- GitHub still shows `license: null` after merge: confirm `LICENSE` filename and MIT header text match GitHub's detector; fix in follow-up commit on same PR.
- `pyproject` license diverges from `LICENSE`: treat as fail; tasks require them to match.
