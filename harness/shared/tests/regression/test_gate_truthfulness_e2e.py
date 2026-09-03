"""End-to-end reproductions for the gate-truthfulness batch (DEC-038 .. DEC-041).

Every gate this branch added already has unit tests that run the real thing --
real git repositories, `runpy` of the scripts. What none of them exercised is the
*wiring*: the `make` recipes a contributor types, and the shell block the
workflow runs. No test in the repository invoked `make` as a subprocess before
this module, so the `$(if $(BASE_REF),...)` conditional, the `FILE=` usage guard
and the `command -v` fail-closed guard had zero coverage, and each defect below
lived in exactly that unexercised layer.

Defects covered:
1. The attestation check failed every PR touching nothing protected (5261568,
   Copilot review). `_check()` demanded a table from an empty derived set. The
   unit tests now cover it; this reproduces it through `make attestation-check`,
   the path CI takes, so the fix cannot regress in the recipe.
2. A failed description fetch was reported as a missing table (DEC-040). The
   workflow's `run:` block sets `set -euo pipefail` for this reason, and the
   claim was asserted textually in `test_workflow_contracts.py` -- never
   executed. This runs the workflow's own shell, extracted from the YAML rather
   than copied, with `curl` stubbed to fail.
3. `make secrets-allowlist-check` must fail closed without gitleaks (INV-1,
   DEC-035). Asserted in prose since the target was written; here it runs.
4. `BASE_REF` must reach the script. The `$(if ...)` form is easy to break in a
   way that silently drops the flag; a nonexistent ref proves it arrived.

These run through `make` against *this* repository, because the Makefile lives
here and its recipes address `harness/shared/...` relatively. The base ref used
is the branch's own name, so the derived protected set is empty on a clean
tree -- the "ordinary PR" case that defect 1 is about.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

WORKFLOW = REPO / ".github" / "workflows" / "python-package.yml"
ATTESTATION_STEP = "Verify the protected-path attestation table"


def _env(extra_path: Path | None = None) -> dict[str, str]:
    """A PATH where bare `python` is this interpreter, so `make`'s `PYTHON ?= python` finds it.

    The workflow's shell also calls bare `python` for the JSON extraction; on the
    runner that is the setup-python interpreter, here it must not be whatever
    `/usr/local/bin/python` happens to be.
    """
    env = dict(os.environ)
    parts = [str(Path(sys.executable).parent)]
    if extra_path is not None:
        parts.insert(0, str(extra_path))
    env["PATH"] = os.pathsep.join(parts + [env.get("PATH", "")])
    # A caller's override must not leak in and change which base the tests diff against.
    env.pop("GITHUB_BASE_REF", None)
    return env


def _make(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "-C", str(REPO), "--no-print-directory", *args, f"PYTHON={sys.executable}"],
        capture_output=True,
        text=True,
        env=env or _env(),
    )


def _own_branch() -> str:
    """This branch's name: `origin/<name>...HEAD` is an empty diff on a clean tree."""
    return subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO, encoding="utf-8"
    ).strip()


@pytest.fixture(scope="module")
def base_ref() -> str:
    """Skipping is not an option (INV-2), so the premise is asserted instead.

    An empty derived set is what makes the "ordinary PR" cases below meaningful.
    A modified *protected* file in the working tree would put a row in the set
    and turn those cases into a different test; say so rather than fail obscurely.
    """
    branch = _own_branch()
    listed = _make("attestation", f"BASE_REF={branch}")
    assert listed.returncode == 0, listed.stderr
    # Rows are the only thing the recipe prints to stdout (`@` silences the
    # command echo); the `[PASS]` line for an empty set goes to stderr via logging.
    rows = [line for line in listed.stdout.splitlines() if line.startswith("|")]
    assert not rows, (
        "these cases need an empty protected set; the working tree has modified protected "
        f"files:\n{listed.stdout}"
    )
    return branch


class TestMakeAttestationTargets:
    def test_check_without_a_file_prints_usage_and_fails(self) -> None:
        res = _make("attestation-check")
        assert res.returncode != 0
        assert "usage: make attestation-check FILE=" in res.stdout + res.stderr

    def test_an_ordinary_pr_passes_the_check_with_no_table(self, base_ref: str, tmp_path: Path) -> None:
        """Defect 1, through the recipe CI runs rather than the function the unit tests call."""
        body = tmp_path / "body.md"
        body.write_text("## Summary\n\nTouches nothing protected.\n", encoding="utf-8")
        res = _make("attestation-check", f"FILE={body}", f"BASE_REF={base_ref}")
        assert res.returncode == 0, res.stdout + res.stderr
        assert "no attestation is required" in res.stdout + res.stderr

    def test_over_attestation_on_an_ordinary_pr_still_fails(self, base_ref: str, tmp_path: Path) -> None:
        """Relaxing the empty case must not have made a table for nothing acceptable."""
        body = tmp_path / "body.md"
        body.write_text(
            "## Protected-path attestation\n\n| File | Change | Why |\n|---|---|---|\n| `Makefile` | x | y |\n",
            encoding="utf-8",
        )
        res = _make("attestation-check", f"FILE={body}", f"BASE_REF={base_ref}")
        assert res.returncode != 0
        assert "names no protected path" in res.stdout + res.stderr

    def test_base_ref_reaches_the_script(self) -> None:
        """Defect 4: a nonexistent ref must surface as a git error, proving the flag was passed.

        If the `$(if $(BASE_REF),...)` conditional silently dropped the flag, the
        script would fall back to the remote's default and this would *succeed*.
        """
        res = _make("attestation", "BASE_REF=no-such-ref-for-this-test")
        assert res.returncode != 0
        assert "no-such-ref-for-this-test" in res.stdout + res.stderr


def _workflow_step_shell() -> str:
    """The attestation step's `run: |` block, read from the workflow rather than copied.

    Copying it would let the test and the workflow drift the way the skill and
    the tool did (DEC-038); reading it means a change to the step is tested as
    written.

    Extracted textually, not with PyYAML. PyYAML is not a declared dependency of
    this repository: the lock carries it only as a transitive of `langchain-core`
    and `uvicorn` (`requirements-lock.txt`, `# via`), neither of which a test of
    the workflow has any business relying on, and it ships no type stubs, so
    `mypy --check-untyped-defs` rejects the import outright. The block is a
    literal scalar: the lines after `run: |` indented deeper than the `run:`
    key, dedented by that key's indent plus two.
    """
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    name_index = [i for i, line in enumerate(lines) if line.strip() == f"- name: {ATTESTATION_STEP}"]
    assert len(name_index) == 1, f"expected one step named {ATTESTATION_STEP!r}, found {len(name_index)}"
    run_index = next(i for i in range(name_index[0], len(lines)) if lines[i].strip() == "run: |")
    key_indent = len(lines[run_index]) - len(lines[run_index].lstrip())
    body_indent = key_indent + 2
    body: list[str] = []
    for line in lines[run_index + 1 :]:
        if line.strip() == "":
            body.append("")
            continue
        if len(line) - len(line.lstrip()) < body_indent:
            break
        body.append(line[body_indent:])
    shell = "\n".join(body).rstrip("\n") + "\n"
    assert "make attestation-check" in shell, "the extracted block is not the attestation step's shell"
    return shell


def _stub_curl(bin_dir: Path, script: str) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "curl"
    stub.write_text("#!/usr/bin/env bash\n" + script, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def _run_step(tmp_path: Path, base_ref: str, curl_script: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    _stub_curl(bin_dir, curl_script)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    env = _env(extra_path=bin_dir)
    env.update(
        {
            "GH_TOKEN": "not-a-real-token",
            "PR_NUMBER": "76",
            "GITHUB_API_URL": "http://api.invalid",
            "GITHUB_REPOSITORY": "owner/repo",
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_BASE_REF": base_ref,
            "PYTHON": sys.executable,
        }
    )
    return subprocess.run(
        ["bash", "-c", _workflow_step_shell()],
        cwd=REPO,
        capture_output=True,
        text=True,
        env=env,
    )


class TestWorkflowAttestationStepShell:
    """The workflow's own shell, executed, with the network replaced by a stub `curl`."""

    def test_a_fetched_description_flows_through_to_the_check(self, tmp_path: Path, base_ref: str) -> None:
        """Happy path: curl's JSON -> the python extraction -> make -> pass for an ordinary PR."""
        curl = "printf '%s' '{\"body\": \"## Summary\\n\\nnothing protected here\\n\"}'\n"
        res = _run_step(tmp_path, base_ref, curl)
        assert res.returncode == 0, res.stdout + res.stderr
        assert "no attestation is required" in res.stdout + res.stderr

    def test_a_failed_fetch_is_not_reported_as_a_missing_table(self, tmp_path: Path, base_ref: str) -> None:
        """Defect 2. The step must stop at the fetch and say nothing about tables.

        Without `set -e`/`pipefail` the shell carries on past the failed curl:
        `pr.json` is empty, the `python` extraction fails and leaves `pr-body.md`
        empty too, and the check judges an empty body. On a protected-path PR
        that is reported as a *missing table* -- a true failure for a false
        reason (DEC-040). On an ordinary PR, which is what this fixture sets up,
        it is worse: an empty body against an empty derived set is a **PASS**,
        so a broken fetch would go green. Run with the mutation applied, this
        step exits 0 with no `[FAIL]` at all; the `returncode != 0` assertion is
        the one that kills it.
        """
        curl = "echo 'curl: (22) The requested URL returned error: 401' >&2\nexit 22\n"
        res = _run_step(tmp_path, base_ref, curl)
        assert res.returncode != 0
        combined = res.stdout + res.stderr
        assert "returned error: 401" in combined
        assert "[FAIL]" not in combined, "the attestation check ran on a body that was never fetched"
        assert "no attestation table" not in combined
        assert "no heading matching" not in combined


class TestSecretsAllowlistCheckFailsClosed:
    def test_missing_gitleaks_is_a_failure_not_a_pass(self) -> None:
        """Defect 3: INV-1 forbids converting an absent tool into a green gate."""
        res = _make("secrets-allowlist-check", "GITLEAKS=no-such-gitleaks-binary-for-this-test")
        assert res.returncode != 0
        assert "gitleaks missing; failing closed" in res.stdout + res.stderr
        assert "[PASS]" not in res.stdout + res.stderr
