# Tasks: MG-E0 OSS License

## Milestone 1 — License file and packaging metadata  [TODO]

- [ ] 1. Add root `LICENSE` (MIT, Copyright (c) 2026 Ian Cruickshank).
- [ ] 2. Set `[project].license = "MIT"` in `pyproject.toml` (SPDX string).
- [ ] 3. Confirm no second license text or conflicting SPDX elsewhere in packaging metadata.

- **Gate:** Files present on the change branch; `LICENSE` text is MIT; `pyproject.toml` license field equals `MIT`.

## Milestone 2 — OpenSpec package  [TODO]

- [ ] 4. Keep `openspec/changes/mg-e0-oss-license/{proposal,design,tasks}.md` and `specs/oss-license/spec.md` aligned with Critic Gate A (MIT only; E0 hygiene only).
- [ ] 5. Keep package green under existing OpenSpec / validate CI if present; do not invent a separate local-only validate path.

- **Gate:** OpenSpec validate (or repo equivalent) green on the PR; no E1–E4 scope creep in this change.

## Milestone 3 — Post-merge honesty check  [TODO — after merge]

- [ ] 6. Verify GitHub `license.spdx_id` is `MIT` (or LICENSE still present if API lag).
- [ ] 7. Archive this change per repo OpenSpec archive practice once Implementer/Conductor clear.

- **Gate:** Public license non-null; change archived or tick complete on Conductor signal.
