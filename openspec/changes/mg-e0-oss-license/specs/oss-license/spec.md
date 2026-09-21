# Capability: OSS License

## ADDED Requirements

### Requirement: Public SPDX license

The repository SHALL publish a single SPDX-identified open-source license that GitHub and packaging metadata both recognize.

#### Scenario: Root LICENSE is MIT

- **WHEN** a consumer clones the default branch
- **THEN** a root file named `LICENSE` exists
- **AND** its text is the MIT License
- **AND** the copyright line names Ian Cruickshank with year 2026

#### Scenario: Packaging metadata matches LICENSE

- **WHEN** `pyproject.toml` is read
- **THEN** `[project].license` equals the SPDX id `MIT`
- **AND** it does not declare a second conflicting SPDX id

#### Scenario: No dual-license in E0

- **WHEN** this change is active
- **THEN** the repository does not claim Apache-2.0 or dual MIT/Apache in E0 artifacts
- **AND** any patent-grant license change is a separate OpenSpec change

### Requirement: Hygiene scope fence

E0 SHALL NOT alter execution backends, broker defaults, or safety classifiers.

#### Scenario: ProcessBackend default unchanged

- **WHEN** this change lands
- **THEN** the broker default backend selection is unmodified by E0 files
- **AND** no SWE-ReX / OpenSandbox / Stagehand / mini-swe-agent adapter code is introduced under this change id
