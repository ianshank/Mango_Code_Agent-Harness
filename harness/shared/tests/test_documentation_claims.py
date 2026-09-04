"""Claims the documentation makes about the tree, each checked against the tree.

`test_documentation_truth.py` pins paths, versions, models and diagrams. The
2026 standards audit (M26 and the Low list) found a further set of sentences
that were simply false and had no gate: `harness/CONTRACT.md` said the CI
examples carry `PIN_FULL_COMMIT_SHA` when only the control-plane example does;
`harness/node/Agent.md` claimed React/Vite/WebSocket scope over a stack whose
manifest declares none of them; `CONTRIBUTING.md` said `make pre-pr` must pass
before a push and, five lines later, that two of its gates may be uninstallable;
`harness/README.md` indexed two of the reports under `docs/reports/`; and a
report sat loose at the `docs/` root after the plan to move it was closed.

Each fix here gains a check, in this module rather than the truth file, which
sits near the `limits.test_size_budget_lines` budget. The checks read the prose
and the artefact it describes and compare them; none re-states the claim.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

import pytest

from harness.shared.tests._ci_gate_helpers import _make_targets
from harness.shared.tests._helpers import REPO
from harness.shared.tests._workflow_paths import WORKFLOW

pytestmark = pytest.mark.governance

CONTRACT = REPO / "harness" / "CONTRACT.md"
CONTRIBUTING = REPO / "CONTRIBUTING.md"
README = REPO / "README.md"
HARNESS_README = REPO / "harness" / "README.md"
MAKEFILE = REPO / "Makefile"
DOCS = REPO / "docs"
REPORTS = DOCS / "reports"
NODE_STACK = REPO / "harness" / "node"
NODE_PERSONA = NODE_STACK / "Agent.md"

PLACEHOLDER = "PIN_FULL_COMMIT_SHA"


# --- The placeholder is exactly where CONTRACT.md says it is ---------------------


def tracked_yaml_files(root: Path) -> list[Path]:
    """Every tracked ``*.yml`` / ``*.yaml``, workflows and examples alike."""
    listing = subprocess.run(
        ["git", "ls-files", "--", "*.yml", "*.yaml", "**/*.yml", "**/*.yaml"],
        cwd=str(root), capture_output=True, text=True, timeout=60, check=True,
    ).stdout.splitlines()
    return [root / line for line in listing if line.strip()]


def files_with_placeholder(paths: Iterable[Path], root: Path) -> set[str]:
    """Repo-relative paths among ``paths`` whose text contains the placeholder."""
    return {
        path.relative_to(root).as_posix()
        for path in paths
        if path.is_file() and PLACEHOLDER in path.read_text(encoding="utf-8")
    }


def contract_placeholder_files(text: str) -> set[str]:
    """The workflow files the CONTRACT paragraph about the placeholder names.

    Only concrete repo-relative paths count: the paragraph also says which
    workflows do *not* carry the placeholder, by glob (``harness/*/...``) and by
    bare name (``ci.yml``), and neither of those is a file it claims holds one.
    """
    for paragraph in re.split(r"\n\s*\n", text):
        if PLACEHOLDER in paragraph:
            named = re.findall(r"`([^`\s]+\.ya?ml)`", paragraph)
            return {path for path in named if "/" in path and "*" not in path}
    return set()


class TestPlaceholderLivesWhereContractSaysItDoes:
    """CONTRACT.md read "CI examples intentionally contain `PIN_FULL_COMMIT_SHA`"
    after DEC-045 had SHA-pinned every `uses:` in every real workflow; only
    `required-workflow.example.yml` still carried it. A reader taking the
    sentence at face value would go looking for placeholders in workflows that
    have none, or -- worse -- expect one and not notice a real pin missing."""

    def test_the_scan_finds_yaml_files(self) -> None:
        """Guards the discovery: an empty listing would make the equality below vacuous."""
        found = tracked_yaml_files(REPO)
        assert len(found) >= 4, f"tracked YAML discovery returned only {found}"

    def test_the_contract_names_the_placeholder_file(self) -> None:
        named = contract_placeholder_files(CONTRACT.read_text(encoding="utf-8"))
        assert named, "CONTRACT.md no longer names a workflow file in its placeholder paragraph"
        for rel in named:
            assert (REPO / rel).is_file(), f"CONTRACT.md names {rel}, which does not exist"

    def test_the_placeholder_appears_in_exactly_the_named_files(self) -> None:
        named = contract_placeholder_files(CONTRACT.read_text(encoding="utf-8"))
        actual = files_with_placeholder(tracked_yaml_files(REPO), REPO)
        assert actual == named, (
            f"CONTRACT.md says {PLACEHOLDER} lives in {sorted(named)}; the tracked YAML "
            f"that carries it is {sorted(actual)}. Reword the paragraph or fix the files -- "
            "a placeholder in a real workflow is an unpinned action, and one missing from the "
            "example is an adopter blocker that no longer blocks."
        )

    def test_a_placeholder_left_in_a_workflow_is_reported(self, tmp_path: Path) -> None:
        """The negative case: exactly the offending file, nothing else."""
        offender = tmp_path / ".github" / "workflows" / "ci.yml"
        offender.parent.mkdir(parents=True)
        offender.write_text(f"uses: actions/checkout@{PLACEHOLDER}\n", encoding="utf-8")
        clean = tmp_path / "clean.yml"
        clean.write_text("uses: actions/checkout@" + "a" * 40 + " # v4.0.0\n", encoding="utf-8")
        assert files_with_placeholder([offender, clean], tmp_path) == {".github/workflows/ci.yml"}


# --- A persona's scope names technologies its stack actually has -----------------
#
# Convention: a persona declares its scope on one line beginning `**Scope:**`.
# Every backticked name on that line is either a path, checked to exist under
# the stack directory, or a technology, checked against the stack's
# `package.json` dependency names and the module specifiers its `src/` imports.
# The helper is generic over a stack directory; only `harness/node/Agent.md` is
# held to it today, because it is the one that was wrong.

SCOPE_LINE = re.compile(r"^\*\*Scope:\*\*(.*)$", re.M)
IMPORT_SPECIFIER = re.compile(r"""from\s+['"]([^'"]+)['"]""")


def scope_names(persona_text: str) -> list[str]:
    match = SCOPE_LINE.search(persona_text)
    return re.findall(r"`([^`]+)`", match.group(1)) if match else []


def stack_technologies(stack: Path) -> set[str]:
    """Names a claim on the scope line may use: dependencies and imported modules.

    A scoped package contributes its parts as well as itself, so
    ``@vitest/coverage-v8`` supports a claim of ``vitest``; an import such as
    ``node:fs`` supports ``node``. Relative imports are the stack's own files
    and support nothing.
    """
    names: set[str] = set()
    manifest = json.loads((stack / "package.json").read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        for dependency in manifest.get(section, {}):
            names.add(dependency)
            names.update(dependency.lstrip("@").split("/"))
    for source in sorted((stack / "src").rglob("*.ts")):
        for specifier in IMPORT_SPECIFIER.findall(source.read_text(encoding="utf-8")):
            if specifier.startswith("."):
                continue
            names.add(specifier)
            names.add(specifier.split(":", 1)[0])
            names.add(specifier.lstrip("@").split("/", 1)[0])
    return {name.lower() for name in names}


def unsupported_scope_names(persona: Path, stack: Path) -> list[str]:
    """Scope names the stack does not bear out, in the order they are claimed."""
    supported = stack_technologies(stack)
    unsupported: list[str] = []
    for name in scope_names(persona.read_text(encoding="utf-8")):
        is_path = "/" in name or name.startswith(".")
        if is_path and not (stack / name).exists():
            unsupported.append(name)
        elif not is_path and name.lower() not in supported:
            unsupported.append(name)
    return unsupported


class TestPersonaScopeIsBackedByTheStack:
    """`harness/node/Agent.md` told the Node Bridge it owned "React/Vite
    frontends, and any external WebSockets/Node.js bridges". The manifest has
    never declared react, vite or a WebSocket library, and `src/` is a Nemotron
    client plus a governance anchor. An agent adopting that persona would look
    for components that do not exist and write tests "for components"."""

    def test_the_scope_line_is_found_and_substantive(self) -> None:
        """Guards the parse: with no scope line every claim below passes vacuously."""
        names = scope_names(NODE_PERSONA.read_text(encoding="utf-8"))
        assert len(names) >= 3, f"harness/node/Agent.md has no parseable **Scope:** line ({names})"

    def test_the_stack_declares_technologies(self) -> None:
        assert {"typescript", "vitest"} <= stack_technologies(NODE_STACK)

    def test_every_scope_claim_is_supported(self) -> None:
        unsupported = unsupported_scope_names(NODE_PERSONA, NODE_STACK)
        assert not unsupported, (
            f"harness/node/Agent.md claims scope over {unsupported}, which harness/node neither "
            "declares in package.json nor imports under src/ (or, for a path, does not contain). "
            "A persona's scope is a promise about the code; keep it to what is there."
        )

    def test_a_claim_the_stack_lacks_is_reported(self, tmp_path: Path) -> None:
        """The negative case, both kinds: an absent technology and an absent path."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "index.ts").write_text("import { readFileSync } from 'node:fs';\n", encoding="utf-8")
        (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"vitest": "1.0.0"}}), encoding="utf-8")
        persona = tmp_path / "Agent.md"
        persona.write_text("# P\n\n**Scope:** `vitest`, `node`, `react`, `src/`, `src/web/`.\n", encoding="utf-8")
        assert unsupported_scope_names(persona, tmp_path) == ["react", "src/web/"]


# --- CONTRIBUTING's gate statement is the Makefile's and the workflow's ---------


def pre_pr_prerequisites(makefile_text: str) -> set[str]:
    match = re.search(r"^pre-pr:\s*([^#\n]*)", makefile_text, re.M)
    return set(match.group(1).split()) if match else set()


def job_display_names(workflow_text: str) -> set[str]:
    """Job-level ``name:`` values: four-space indent, no list dash (steps are deeper)."""
    return set(re.findall(r"^    name:\s*(\S[^\n]*?)\s*$", workflow_text, re.M))


class TestContributingGateStatementIsTrue:
    """CONTRIBUTING.md line 37 said `make pre-pr` "must pass before you push"
    and lines 42-45 conceded the Go tools it needs may not be installable. Both
    cannot be the rule. The reconciled statement -- pre-pr is the bar, `make ci`
    plus linked `dependency-audit` / `secret-scan` job runs is the fallback --
    is checked here against the recipe and the workflow it describes."""

    BAR_TARGETS = ("ci", "review", "lint-cold", "audit", "secrets")
    FALLBACK_JOBS = ("dependency-audit", "secret-scan")

    def test_pre_pr_runs_every_gate_contributing_attributes_to_it(self) -> None:
        text = CONTRIBUTING.read_text(encoding="utf-8")
        prerequisites = pre_pr_prerequisites(MAKEFILE.read_text(encoding="utf-8"))
        assert prerequisites, "the Makefile's pre-pr rule was not found"
        for target in self.BAR_TARGETS:
            assert f"`{target}`" in text, f"CONTRIBUTING.md no longer attributes `{target}` to pre-pr"
            assert target in prerequisites, f"CONTRIBUTING.md says pre-pr runs `{target}`; the recipe does not"

    def test_the_fallback_names_jobs_the_workflow_shows(self) -> None:
        text = CONTRIBUTING.read_text(encoding="utf-8")
        shown = job_display_names(WORKFLOW.read_text(encoding="utf-8"))
        assert shown, "no job-level name: found in the workflow; the parser needs updating"
        for job in self.FALLBACK_JOBS:
            assert f"`{job}`" in text, f"CONTRIBUTING.md no longer names the `{job}` job as the fallback evidence"
            assert job in shown, f"CONTRIBUTING.md points at a `{job}` job the workflow does not show"

    def test_the_install_targets_it_names_exist(self) -> None:
        defined = _make_targets(MAKEFILE.read_text(encoding="utf-8"))
        text = CONTRIBUTING.read_text(encoding="utf-8")
        for target in ("audit-install", "secrets-install", "ci", "lint-cold"):
            assert f"`make {target}`" in text, f"CONTRIBUTING.md no longer tells the reader to run `make {target}`"
            assert target in defined, f"CONTRIBUTING.md names `make {target}`, which the Makefile does not define"

    def test_the_bar_and_the_concession_are_one_statement(self) -> None:
        """The contradiction: an unconditional "must pass before you push" beside a
        paragraph conceding it may not be runnable. The concession stays -- it is
        true -- so the unconditional sentence must not come back."""
        text = CONTRIBUTING.read_text(encoding="utf-8")
        assert "must pass before you push" not in text
        assert "the documented\nfallback" in text or "the documented fallback" in text


# --- README's Node setup and the docs tree --------------------------------------


class TestReadmeNodeSetupUsesCorepack:
    """`harness/node/package.json` pins `packageManager: pnpm@…`, which is what
    `corepack enable` reads; the README's setup went straight to `pnpm install`
    with no word on where pnpm comes from."""

    def test_corepack_enable_precedes_the_first_pnpm_install(self) -> None:
        text = README.read_text(encoding="utf-8")
        assert "corepack enable" in text, "README no longer mentions `corepack enable`"
        assert text.index("corepack enable") < text.index("pnpm install"), (
            "README mentions corepack only after it has already told the reader to run pnpm install"
        )

    def test_the_manifest_pins_what_corepack_activates(self) -> None:
        manifest = json.loads((NODE_STACK / "package.json").read_text(encoding="utf-8"))
        assert str(manifest.get("packageManager", "")).startswith("pnpm@"), (
            "package.json no longer pins packageManager to pnpm, so `corepack enable` would activate nothing"
        )


class TestDocsRootHoldsOnlyDirectories:
    """R-CQ-30's last open item: `docs/SDLC_HYGIENE_AND_GAP_ANALYSIS.md` was the
    one loose file at the `docs/` root. It is a report and lives with the others."""

    def test_no_loose_file_at_the_docs_root(self) -> None:
        loose = sorted(p.name for p in DOCS.iterdir() if p.is_file())
        assert not loose, f"files at the docs/ root: {loose}. Reports go under docs/reports/, specs under docs/specs/."

    def test_the_moved_report_is_under_reports(self) -> None:
        assert (REPORTS / "SDLC_HYGIENE_AND_GAP_ANALYSIS.md").is_file()


def indexed_reports(harness_readme_text: str) -> set[str]:
    """The report names `harness/README.md` lists after "Reports are under `docs/reports/`:"."""
    match = re.search(r"Reports are under `docs/reports/`:([^;\n]*)", harness_readme_text)
    return set(re.findall(r"`([^`\s]+\.md)`", match.group(1))) if match else set()


class TestEveryReportIsIndexed:
    """`harness/README.md` named two of the reports under `docs/reports/`; the
    directory held four, then five with the 2026 audit, which is the one a reader
    most needs to find."""

    def test_the_index_is_found(self) -> None:
        assert len(indexed_reports(HARNESS_README.read_text(encoding="utf-8"))) >= 2

    def test_the_index_matches_the_directory(self) -> None:
        indexed = indexed_reports(HARNESS_README.read_text(encoding="utf-8"))
        on_disk = {p.name for p in REPORTS.glob("*.md")}
        assert indexed == on_disk, (
            f"harness/README.md indexes {sorted(indexed)} but docs/reports/ holds {sorted(on_disk)}"
        )

    def test_the_current_audit_is_indexed(self) -> None:
        assert "2026-STANDARDS-AUDIT.md" in indexed_reports(HARNESS_README.read_text(encoding="utf-8"))
