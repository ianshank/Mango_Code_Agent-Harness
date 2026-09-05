"""Contracts the root Makefile must keep, beyond "the targets exist".

`test_ci_gate_coverage.py` already proves every policy-declared gate is
reachable from `make ci` and that its recipe still does something. This file
covers the contracts added alongside the regression/AQA tier, and the class of
drift where two composite targets are supposed to stay in step and quietly
stop being.

Kept separate from `test_ci_gate_coverage.py` (which is a protected path) so
these checks can evolve without a label round-trip.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from harness.shared.tests._helpers import REPO

MAKEFILE = REPO / "Makefile"
NODE_MAKEFILE = REPO / "harness" / "node" / "Makefile"
JVM_MAKEFILE = REPO / "harness" / "jvm" / "Makefile"
REQUIREMENTS_DEV = REPO / "requirements-dev.txt"
REGRESSION_DIR = REPO / "harness" / "shared" / "tests" / "regression"

pytestmark = pytest.mark.governance


def _text() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


#: The shell flags every Makefile in this repository runs its recipes under.
#: `-e` stops a recipe line at its first failing command, `-u` makes an unset
#: variable an error, and `pipefail` reports the failure of any pipeline stage.
FAIL_CLOSED_SHELLFLAGS = "-eu -o pipefail -c"


def shellflags(makefile_text: str) -> str | None:
    """The `.SHELLFLAGS` a Makefile declares, or None when it runs on make's default."""
    match = re.search(r"^\.SHELLFLAGS\s*:?=\s*(.+?)\s*$", makefile_text, re.M)
    return match.group(1) if match else None


def gopath_resolved_tools(makefile_text: str) -> set[str]:
    """Tool variables a Makefile re-resolves through PATH and then GOPATH/bin.

    The shape is a `:=` reassignment whose value asks `command -v` first and
    falls back to `$(GO_BIN_DIR)/<tool>`; a Makefile that only ever says
    `TOOL ?= tool` leaves a `go install`-ed binary invisible to its own guard.
    """
    return {
        match.group(1)
        for match in re.finditer(
            r"^([A-Z_]+)\s*:=\s*\$\(shell command -v \$\(\1\).*\$\(GO_BIN_DIR\)/\$\(\1\)", makefile_text, re.M
        )
    }


def _targets() -> dict[str, str]:
    """Map target name -> its recipe body (the indented lines beneath it)."""
    targets: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in _text().splitlines():
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):", line)
        if match:
            if current:
                targets[current] = "\n".join(lines)
            current, lines = match.group(1), []
        elif current and (line.startswith(("\t", "    "))):
            lines.append(line)
        elif current and not line.strip():
            continue
        elif current:
            targets[current] = "\n".join(lines)
            current, lines = None, []
    if current:
        targets[current] = "\n".join(lines)
    return targets


def _prerequisites(target: str) -> list[str]:
    match = re.search(rf"^{re.escape(target)}:\s*([^\n#]*)", _text(), re.M)
    return match.group(1).split() if match else []


class TestRegressionTierIsWired:
    def test_the_tier_exists_and_is_populated(self) -> None:
        """Guards every check below: an empty tier would satisfy them all."""
        modules = sorted(REGRESSION_DIR.glob("test_*.py"))
        assert modules, "the regression tier has no test modules"

    def test_make_test_regression_targets_the_tier(self) -> None:
        recipe = _targets().get("test-regression", "")
        assert "regression" in recipe, "make test-regression does not run the regression directory"
        assert "not live" in recipe, "make test-regression would run the live suites"

    def test_the_tier_is_reachable_from_make_ci(self) -> None:
        """The dedicated target is a convenience. What must not drift is that
        `make ci` still executes these tests -- it does so through
        `test-python`, whose path argument has to keep containing the tier."""
        recipe = _targets().get("test-python", "")
        assert "$(SHARED_TESTS)" in recipe, (
            "test-python no longer runs the shared tests directory, so the regression tier is not covered by `make ci`"
        )
        relative = REGRESSION_DIR.relative_to(REPO / "harness" / "shared" / "tests")
        assert relative.parts, "the tier moved outside the directory test-python runs"

    def test_coverage_run_also_covers_the_tier(self) -> None:
        assert "$(SHARED_TESTS)" in _targets().get("coverage-python", "")


class TestCompositeTargetsStayInStep:
    def test_pre_pr_still_runs_ci_review_and_the_cold_typecheck(self) -> None:
        assert _prerequisites("pre-pr") == ["ci", "review", "lint-cold", "audit", "secrets"]

    def test_ci_and_ci_python_differ_only_by_the_node_gates(self) -> None:
        """A gate added to `ci` and forgotten in `ci-python` silently stops
        enforcing on the secondary matrix legs, with no signal anywhere.

        `ci-python` arrives with the open gate-hardening PR; until it exists
        there is nothing to compare, so this asserts the invariant the moment
        the target appears rather than failing before it does.
        """
        ci_python = _prerequisites("ci-python")
        assert ci_python, "ci-python has no prerequisites; the comparison below would be vacuous"
        difference = set(_prerequisites("ci")) - set(ci_python)
        assert difference == {"lint-node", "test-node", "verify-zero-skips"}, (
            f"ci and ci-python differ by {sorted(difference)}; the only legitimate difference "
            "is the Node-dependent gates, which run once on the primary leg"
        )

    def test_node_deps_is_a_shared_target_using_the_lockfile(self) -> None:
        """One install recipe, so CI, the session hook and a local run cannot
        drift into installing different things."""
        recipe = _targets().get("node-deps", "")
        assert recipe, "make node-deps does not exist"
        assert "--frozen-lockfile" in recipe, (
            "node-deps must install from the lockfile; a resolving install makes CI non-reproducible"
        )


class TestMakefileSelfConsistency:
    def test_every_phony_declaration_names_a_real_target(self) -> None:
        declared = set(re.findall(r"^\.PHONY:\s*(.+)$", _text(), re.M))
        names = {name for line in declared for name in line.split()}
        defined = set(_targets())
        assert not names - defined, f".PHONY names targets that do not exist: {sorted(names - defined)}"

    def test_test_governance_selects_by_marker_not_by_filename(self) -> None:
        """A hardcoded file list goes stale the moment a governance module is added,
        and reports "governance is green" while skipping most of the suite. It named
        three modules while 23 carried the marker."""
        recipe = _targets().get("test-governance", "")
        assert "-m" in recipe and "governance" in recipe, recipe
        assert ".py" not in recipe, (
            "test-governance names individual files; select by marker so a new governance "
            "module is picked up without editing the Makefile"
        )

    def test_every_target_is_documented(self) -> None:
        """`make help` parses `## ` comments; an undocumented target is
        invisible to anyone who did not write it."""
        undocumented = [name for name in _targets() if not re.search(rf"^{re.escape(name)}:[^\n]*##", _text(), re.M)]
        assert not undocumented, f"targets missing a `## ` description: {undocumented}"

    def test_review_names_every_skill_claude_md_mandates(self) -> None:
        """CLAUDE.md calls three review skills non-negotiable; `make review`
        printed only two of them, so following the printed checklist skipped
        one of the mandated steps."""
        recipe = _targets().get("review", "")
        for skill in ("openspec-peer-review", "repo-invariant-review", "validation-runner"):
            assert skill in recipe, f"make review does not name the mandated '{skill}' skill"


class TestDeadCodeAndSkipGatesAreWired:
    """tech-debt-hardening-plan R-TDH-17 / R-TDH-19: the gates exist as Make
    targets and sit on the paths CI actually runs."""

    def test_lint_python_runs_vulture_against_the_whitelist(self) -> None:
        recipe = _targets().get("lint-python", "")
        assert "vulture" in recipe and "vulture_whitelist.py" in recipe, "lint-python must run the dead-code gate"
        assert "--min-confidence" in recipe, "the confidence floor must be explicit, not vulture's default"

    def test_lint_python_runs_ruff_format_check(self) -> None:
        """NS-33 / audit H11: formatting is a gate, not a local habit.

        `ruff check` alone does not enforce the formatter that replaced E/W
        layout rules; without `format --check` on this target, CI's
        `make ci-python` would stay green while the tree drifts.
        """
        recipe = _targets().get("lint-python", "")
        assert "format --check" in recipe, (
            "lint-python must run `ruff format --check` so formatting is gated "
            "the same way `ruff check` already is (NS-33)"
        )

    def test_python_zero_skip_gate_is_a_direct_prerequisite_of_both_pipelines(self) -> None:
        assert "verify-zero-skips-python" in _prerequisites("ci")
        assert "verify-zero-skips-python" in _prerequisites("ci-python")

    def test_python_zero_skip_gate_reads_the_suite_local_registry(self) -> None:
        recipe = _targets().get("verify-zero-skips-python", "")
        assert "--junit-events" in recipe
        assert "skip-waivers.json" in recipe and ".governance/skip-waivers.json" not in recipe, (
            "the Python registry lives beside the suite; the root .governance/ is dormant (DEC-005)"
        )

    def test_lock_freshness_gate_is_a_direct_prerequisite_of_both_pipelines(self) -> None:
        """The lock is only a supply-chain control while something runs it.

        `verify-zero-skips-python` and the `CP_TESTS` wiring are both pinned as
        pipeline prerequisites; `lock-check` was not, so it could be dropped from
        `ci` with the whole suite green and an unlocked dependency set would ship
        unnoticed (R-TDH-9).
        """
        for pipeline in ("ci", "ci-python"):
            assert "lock-check" in _prerequisites(pipeline), (
                f"`make {pipeline}` no longer runs lock-check; a stale requirements-lock.txt "
                "would reach CI with every other gate green"
            )

    def test_lock_freshness_gate_actually_recompiles_and_compares(self) -> None:
        """Reachability is not enforcement: the recipe must still do the work."""
        recipe = _targets().get("lock-check", "")
        assert recipe, "Makefile has no lock-check recipe"
        # The tool is invoked through $(UV), like every other pinned tool in this
        # Makefile (DEC-013); accept either spelling so a variable rename is not
        # a false failure, but require the compile step itself.
        assert re.search(r"(?:\$\(UV\)|uv)\s+pip compile", recipe), "lock-check no longer recompiles the lock"
        assert "diff" in recipe, "lock-check no longer compares the recompiled lock against the committed one"


class TestControlPlaneTestsAreRun:
    """R-TDH-26 / AC-26: harness/control-plane/tests is a separate directory, so
    dropping it from a recipe would silently un-run every control-plane test
    while `make test-python` stayed green. Both recipes must name it through the
    same variable, and the variable must point at the real directory."""

    def test_the_variable_points_at_the_colocated_directory(self) -> None:
        match = re.search(r"^CP_TESTS\s*:=\s*(\S+)\s*$", _text(), re.M)
        assert match, "Makefile defines no CP_TESTS variable"
        assert (REPO / match.group(1)).is_dir(), f"CP_TESTS={match.group(1)} is not a directory"
        assert match.group(1) == "harness/control-plane/tests"

    @pytest.mark.parametrize("target", ["test-python", "coverage-python"])
    def test_both_python_runners_collect_it(self, target: str) -> None:
        recipe = _targets().get(target, "")
        assert recipe, f"Makefile has no {target} recipe"
        assert "$(CP_TESTS)/" in recipe, f"{target} no longer runs $(CP_TESTS); the control-plane tests would not run"


class TestLintNodeWiring:
    """R-GT-1: the Node lint tier runs in `ci`, and only there.

    DEC-013 deferred this wiring behind a `typescript` / `typescript-eslint`
    incompatibility. Measured against the installed workspace on 2026-09-03 that
    blocker is gone -- ESLint and Knip both pass -- and the real one was
    Prettier reformatting a digest-pinned file (see
    `TestPrettierLeavesPinnedArtefactsAlone` in `test_lint_config_liveness.py`).
    With both resolved the tier is wired, which also brings R-TDH-23's
    policy-sourced ESLint `max-lines` rule into a CI job for the first time: it
    was enforced nowhere before.

    The asymmetry is the point. `ci-python` is what the secondary matrix legs
    run, and those legs install no pnpm, so making `lint-node` a prerequisite of
    the shared `lint` target -- or of `ci-python` -- turns three green legs red.
    """

    def test_lint_node_is_a_direct_prerequisite_of_ci(self) -> None:
        assert "lint-node" in _prerequisites("ci"), (
            "`make ci` no longer runs lint-node; ESLint, Prettier and Knip would run in no CI "
            "job, taking R-TDH-23's policy-sourced max-lines rule with them"
        )

    @pytest.mark.parametrize("target", ["ci-python", "lint"])
    def test_the_pnpm_free_targets_do_not_require_it(self, target: str) -> None:
        """The secondary matrix legs install no Node toolchain."""
        assert "lint-node" not in _prerequisites(target), (
            f"`{target}` requires lint-node, but the matrix legs that run it install no pnpm; "
            "every secondary leg would fail on a missing binary"
        )

    def test_the_recipe_still_runs_all_three_node_gates(self) -> None:
        """Reachability is not enforcement (the `lock-check` lesson)."""
        recipe = _targets().get("lint-node", "")
        assert recipe, "Makefile has no lint-node recipe"
        for tool in ("eslint", "prettier", "knip"):
            assert tool in recipe, f"lint-node no longer runs {tool}"


class TestRecipesRunUnderFailClosedShellFlags:
    """Both stack Makefiles set `.SHELLFLAGS := -eu -o pipefail -c`; the root
    one did not (2026 standards audit, Low). Under make's default `sh -c`, a
    recipe like `grep ... | awk ...` reports awk's exit status whatever grep
    did, and an unset `$$var` silently expands to nothing.
    """

    @pytest.mark.parametrize("path", [MAKEFILE, NODE_MAKEFILE, JVM_MAKEFILE], ids=lambda p: str(p.relative_to(REPO)))
    def test_every_makefile_declares_the_same_flags(self, path: Path) -> None:
        assert shellflags(path.read_text(encoding="utf-8")) == FAIL_CLOSED_SHELLFLAGS, (
            f"{path.relative_to(REPO)} does not run recipes under `{FAIL_CLOSED_SHELLFLAGS}`; "
            "a failed left-hand side of a pipe or an unset variable would pass silently"
        )

    def test_a_makefile_without_the_declaration_is_reported(self) -> None:
        """Without this the reader could pass on any text by returning the constant."""
        assert shellflags("SHELL := /bin/bash\nall:\n\techo hi\n") is None
        assert shellflags(".SHELLFLAGS := -c\n") == "-c"


class TestGoInstalledToolsAreFoundWhereGoPutThem:
    """`make secrets` failed closed right after a successful `make secrets-install`.

    `go install` writes to `$(go env GOPATH)/bin`, which is not on PATH by
    default, and the recipe's `command -v` guard never looked there -- CI only
    passed because the workflow prefixed PATH by hand (2026 standards audit,
    §2). The Makefiles now resolve each Go-installed tool through PATH and then
    GOPATH/bin; the probes below drive the real Makefile with a fake `go` so the
    resolution is exercised, not just read.
    """

    @pytest.mark.parametrize(
        ("path", "tools"),
        [
            pytest.param(MAKEFILE, {"GITLEAKS"}, id="root"),
            pytest.param(NODE_MAKEFILE, {"GITLEAKS", "OSV"}, id="node"),
            pytest.param(JVM_MAKEFILE, {"GITLEAKS", "OSV"}, id="jvm"),
        ],
    )
    def test_every_go_installed_tool_is_resolved(self, path: Path, tools: set[str]) -> None:
        text = path.read_text(encoding="utf-8")
        assert "go env GOPATH" in text, f"{path.relative_to(REPO)} never asks go where it installs binaries"
        assert gopath_resolved_tools(text) >= tools, (
            f"{path.relative_to(REPO)} resolves {sorted(gopath_resolved_tools(text))}, not {sorted(tools)}; "
            "the guard for an unresolved tool fails closed right after its own install target"
        )

    def test_a_makefile_that_only_defaults_the_name_is_reported(self) -> None:
        assert gopath_resolved_tools("GITLEAKS ?= gitleaks\nsecrets:\n\t$(GITLEAKS) dir .\n") == set()

    @staticmethod
    def _fake_toolchain(tmp_path: Path, *, install_gitleaks: bool) -> tuple[Path, dict[str, str]]:
        """A PATH holding a fake `go` (whose GOPATH is under tmp_path) and no gitleaks."""
        gopath = tmp_path / "gopath"
        (gopath / "bin").mkdir(parents=True)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake_go = bin_dir / "go"
        fake_go.write_text(f'#!/bin/sh\n[ "$1 $2" = "env GOPATH" ] && echo "{gopath}"\n', encoding="utf-8")
        fake_go.chmod(fake_go.stat().st_mode | stat.S_IXUSR)
        if install_gitleaks:
            stub = gopath / "bin" / "gitleaks"
            stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        env = dict(os.environ)
        # Only the fake toolchain and the system directories: a gitleaks on the
        # developer's PATH would otherwise satisfy `command -v` and prove nothing.
        env["PATH"] = os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"])
        return gopath, env

    @staticmethod
    def _make(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["make", "-C", str(REPO), "--no-print-directory", *args, f"PYTHON={sys.executable}"],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    def test_a_gitleaks_in_gopath_bin_is_what_the_secrets_gate_runs(self, tmp_path: Path) -> None:
        """`make -n` still resolves `$(shell ...)` at parse time, so the dry run
        shows which binary the recipe would execute without scanning anything."""
        gopath, env = self._fake_toolchain(tmp_path, install_gitleaks=True)
        result = self._make("-n", "secrets", env=env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"{gopath}/bin/gitleaks dir ." in result.stdout, (
            f"the secrets gate did not resolve gitleaks from GOPATH/bin:\n{result.stdout}{result.stderr}"
        )

    def test_a_gitleaks_found_nowhere_still_fails_closed(self, tmp_path: Path) -> None:
        """The fallback must not turn an absent tool into an absent scan (INV-1)."""
        _, env = self._fake_toolchain(tmp_path, install_gitleaks=False)
        result = self._make("secrets", env=env)
        assert result.returncode != 0
        assert "gitleaks missing; failing closed" in result.stdout + result.stderr


class TestPythonRunnersShuffleUnderAPrintedSeed:
    """Audit H8: no order randomisation existed, so an order coupling could
    only be found by luck (the root conftest records one that was). Both
    runners now load pytest-randomly by name, so the run header prints the seed
    and a missing plugin is an ImportError rather than a quietly ordered suite.
    """

    @pytest.mark.parametrize("target", ["test-python", "coverage-python"])
    def test_the_runner_shuffles_and_parallelises(self, target: str) -> None:
        recipe = _targets().get(target, "")
        assert "$(PYTEST_RUN_FLAGS)" in recipe, f"{target} no longer passes the order/parallel flags"

    def test_the_run_flags_compose_both_plugins(self) -> None:
        """Order randomisation and parallelism are separate variables so either
        can be switched off on the command line without editing the recipe."""
        text = _text()
        order = re.search(r"^PYTEST_ORDER_FLAGS\s*\?=\s*(.+?)\s*$", text, re.M)
        parallel = re.search(r"^PYTEST_PARALLEL_FLAGS\s*\?=\s*(.+?)\s*$", text, re.M)
        composed = re.search(r"^PYTEST_RUN_FLAGS\s*:=\s*(.+?)\s*$", text, re.M)
        assert order is not None and "-p randomly" in order.group(1), "PYTEST_ORDER_FLAGS does not load pytest-randomly"
        assert parallel is not None and "-n auto" in parallel.group(1), "PYTEST_PARALLEL_FLAGS does not run under xdist"
        assert composed is not None and {"$(PYTEST_ORDER_FLAGS)", "$(PYTEST_PARALLEL_FLAGS)"} <= set(
            composed.group(1).split()
        ), "PYTEST_RUN_FLAGS does not compose both variables"

    def test_the_plugins_are_pinned_where_the_lock_compiles_from(self) -> None:
        """`-p randomly` on a leg without the plugin is an ImportError, and `-n`
        without xdist is a usage error; the pins keep both off every interpreter
        in the matrix."""
        text = REQUIREMENTS_DEV.read_text(encoding="utf-8")
        assert re.search(r"^pytest-randomly==", text, re.M), "requirements-dev.txt pins no pytest-randomly"
        assert re.search(r"^pytest-xdist==", text, re.M), "requirements-dev.txt pins no pytest-xdist"


class TestTheGraderCannotBeShadowedFromTheWorkspace:
    """`python -m pytest` puts the current directory first on `sys.path`, so a
    `pytest.py` written into the workspace -- not a protected path -- was the
    pytest the verification recipe ran, and a failing suite graded VERIFIED
    with no digested file changed (Copilot review on PR #86). The regression
    in `regression/test_verdict_forgery_regression.py` proves the two recipe
    shapes; these pin the real Makefile to the safe one.
    """

    def test_the_python_runner_cannot_import_a_shadow_module_from_the_workspace(self) -> None:
        text = _text()
        runner = re.search(r"^PYTEST\s*\?=\s*(.+?)\s*$", text, re.M)
        assert runner is not None, "PYTEST is no longer defined in the Makefile"
        flags = runner.group(1).split()
        assert "-I" in flags and "-m" in flags and "pytest" in flags, (
            f"PYTEST is {runner.group(1)!r}; the interpreter must run in isolated mode (-I) "
            "so the workspace is not on its import path when pytest is imported"
        )
        assert flags.index("-I") < flags.index("-m"), "-I must precede -m, or it is an argument to pytest"

    def test_the_xdist_workers_cannot_import_a_shadow_module_either(self) -> None:
        """execnet starts each worker with `python -u -c ...`, which begins with
        the current directory on its path whatever the parent's flags; the
        exported variable is what guards it (Python 3.11 and later)."""
        assert re.search(r"^export PYTHONSAFEPATH\s*:=\s*1\s*$", _text(), re.M), (
            "the Makefile no longer exports PYTHONSAFEPATH=1 to every recipe"
        )


class TestAuditToolIsInstalledFromTheHashedLock:
    """Audit M15: `pip-audit` was installed by name, unhashed, into the job that
    scans everything else for tampering. The pin now lives in requirements-dev.txt
    (so it is in the lock) and the install target installs the lock.
    """

    def test_requirements_dev_pins_pip_audit(self) -> None:
        assert re.search(r"^pip-audit==\d", REQUIREMENTS_DEV.read_text(encoding="utf-8"), re.M)

    def test_the_install_target_installs_the_lock_with_hashes(self) -> None:
        recipe = _targets().get("audit-install-python", "")
        assert "--require-hashes -r $(LOCK_FILE)" in recipe, "audit-install-python no longer installs the hashed lock"
        assert not re.search(r"pip install .*pip-audit", recipe), (
            "audit-install-python installs pip-audit by name, which bypasses the lock's hashes"
        )

    def test_the_makefile_reads_the_pin_rather_than_restating_it(self) -> None:
        """One declaration. The Makefile's PIP_AUDIT_VERSION must be derived from
        requirements-dev.txt, and evaluating it must give the pin that file holds."""
        definition = re.search(r"^PIP_AUDIT_VERSION\s*:?=\s*(.+?)\s*$", _text(), re.M)
        assert definition is not None, "Makefile defines no PIP_AUDIT_VERSION"
        assert "requirements-dev.txt" in definition.group(1) and not re.search(r"\d\.\d", definition.group(1)), (
            f"PIP_AUDIT_VERSION is {definition.group(1)!r}: a literal here is a second copy of the pin"
        )
        pinned = re.search(r"^pip-audit==([^\s;]+)", REQUIREMENTS_DEV.read_text(encoding="utf-8"), re.M)
        assert pinned is not None
        result = subprocess.run(
            [
                "make",
                "-C",
                str(REPO),
                "--no-print-directory",
                "--eval",
                "print-pip-audit-version:\n\t@echo $(PIP_AUDIT_VERSION)",
                "print-pip-audit-version",
                f"PYTHON={sys.executable}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == pinned.group(1)

    def test_the_scan_invokes_the_tool_through_the_interpreter(self) -> None:
        """DEC-013: a bare `pip-audit` on PATH can be a different version than the lock's."""
        recipe = _targets().get("audit-python", "")
        assert "$(PIP_AUDIT)" in recipe
        assert re.search(r"^PIP_AUDIT\s*\?=\s*\$\(PYTHON\) -m pip_audit", _text(), re.M)
