"""What CI installs, and that nothing can substitute something else for it.

Split from `test_workflow_contracts.py` at 653/700 lines, along the concern
DEC-035 names: that module pins the *shape* of the workflows, this one pins the
*dependency set* those workflows install and the integrity of the file that
declares it. The two share `_workflow_paths.py` rather than a second copy of
the same constants.

R-TDH-9 established that CI installs from the committed lock. R-CQ-10 closes
the half that left open: the lock said which versions, and nothing said which
*artefacts*. A lock without hashes pins a version number, and a version number
is a name a registry resolves — so a compromised or replaced file published
under an existing pin installs without a diff here and without a warning there.
`--generate-hashes` writes the artefact digests; `--require-hashes` makes pip
refuse anything else.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harness.shared.tests._workflow_paths import (
    DRIFT_WORKFLOW,
    LOCK,
    LOCK_NAME,
    RANGE_FILES,
    UNSUPPORTED_LEG,
    WORKFLOW,
    distribution_names,
    lock_pins,
    pip_install_lines,
)

pytestmark = pytest.mark.governance

#: A pinned requirement line, with the trailing `\` that introduces its hashes.
#: Environment markers sit between the pin and the continuation, so the pattern
#: must not assume the line ends at the version.
PINNED_REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)==(?P<version>[^\s;\\]+)(?P<rest>.*)$")


def unhashed_requirements(lock_text: str) -> list[str]:
    """Every pinned requirement in the lock that no `--hash=` line follows.

    A requirement's hashes are continuation lines: the pin ends in ` \\` and the
    `--hash=` lines follow until one does not continue. A pin that ends without
    a continuation has no hashes at all, which is the case this reports.
    """
    lines = lock_text.splitlines()
    offenders = []
    for index, line in enumerate(lines):
        match = PINNED_REQUIREMENT.match(line)
        if match is None:
            continue
        if not line.rstrip().endswith("\\"):
            offenders.append(line.strip())
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if "--hash=" not in following:
            offenders.append(line.strip())
    return offenders


class TestDependenciesComeFromTheLock:
    """R-TDH-9: what CI installs is what the committed lock says, on every leg."""

    @pytest.mark.parametrize("path", [WORKFLOW, DRIFT_WORKFLOW], ids=lambda p: p.name)
    def test_every_requirements_install_reads_the_lock(self, path: Path) -> None:
        installs = [line for line in pip_install_lines(path.read_text(encoding="utf-8")) if " -r " in line]
        assert installs, f"{path.name} installs no requirements file at all"
        offenders = [line for line in installs if LOCK_NAME not in line]
        assert not offenders, (
            f"{path.name} installs from an unlocked requirements file: {offenders}. "
            f"Install from {LOCK_NAME} so an upstream release cannot change what CI runs."
        )

    @pytest.mark.parametrize("path", [WORKFLOW, DRIFT_WORKFLOW], ids=lambda p: p.name)
    def test_the_editable_install_does_not_resolve_dependencies(self, path: Path) -> None:
        editable = [line for line in pip_install_lines(path.read_text(encoding="utf-8")) if " -e " in line]
        assert editable, f"{path.name} never installs the project itself"
        assert all("--no-deps" in line for line in editable), (
            f"`pip install -e .` without --no-deps re-resolves the project's ranges and can "
            f"override the lock: {editable}"
        )

    @pytest.mark.parametrize("path", [WORKFLOW, DRIFT_WORKFLOW], ids=lambda p: p.name)
    def test_pip_cache_keys_follow_the_lock(self, path: Path) -> None:
        keys = re.findall(r"cache-dependency-path:\s*(\S+)", path.read_text(encoding="utf-8"))
        python_keys = [k for k in keys if k.startswith("requirements")]
        assert python_keys, f"{path.name} declares no pip cache key"
        assert set(python_keys) == {LOCK_NAME}, f"pip cache keyed on something other than the lock: {python_keys}"

    def test_the_lock_carries_langgraph_behind_a_marker(self) -> None:
        """The 3.9 leg must not receive langgraph; every other leg must."""
        text = LOCK.read_text(encoding="utf-8")
        entry = re.search(r"^langgraph==[^\s;]+ ; ([^\\]+)", text, re.M)
        assert entry, f"{LOCK_NAME} pins no langgraph; the StateGraph suites would skip everywhere again"
        assert re.search(r"python_full_version >= '3\.10'", entry.group(1)), (
            f"langgraph's marker in {LOCK_NAME} is {entry.group(1)!r}; it must exclude {UNSUPPORTED_LEG}"
        )

    def test_the_lock_does_not_carry_the_postgres_checkpointer(self) -> None:
        text = LOCK.read_text(encoding="utf-8")
        assert not re.search(r"^(psycopg|langgraph-checkpoint-postgres)==", text, re.M), (
            "the Postgres checkpointer is its own extra; nothing under harness/ imports it "
            "and pip-audit would scan a driver no gate exercises"
        )

    def test_the_lock_is_universal_not_interpreter_specific(self) -> None:
        text = LOCK.read_text(encoding="utf-8")
        assert "--universal" in text.splitlines()[1], (
            "the header must show the lock was compiled with --universal; a per-interpreter "
            "compile evaluates the markers away and cannot serve the 3.9/3.10/3.12 matrix"
        )


class TestTheLockPinsArtefactsNotJustVersions:
    """R-CQ-10: a version number is a name a registry resolves; a hash is not."""

    def test_the_header_shows_the_lock_was_compiled_with_hashes(self) -> None:
        """The four `make lock*` recipes all pass it; the header is what proves it ran."""
        assert "--generate-hashes" in LOCK.read_text(encoding="utf-8").splitlines()[1], (
            f"{LOCK_NAME}'s header does not show --generate-hashes; a lock recompiled without "
            "it would drop every hash and this file would still look pinned"
        )

    def test_every_pinned_requirement_carries_a_hash(self) -> None:
        offenders = unhashed_requirements(LOCK.read_text(encoding="utf-8"))
        assert not offenders, (
            f"{len(offenders)} requirement(s) in {LOCK_NAME} have no --hash= line: {offenders[:5]}. "
            "pip's --require-hashes mode rejects the whole file if any one is missing, so a single "
            "unhashed pin takes every CI leg down rather than quietly weakening one."
        )

    def test_the_lock_actually_contains_hashes(self) -> None:
        """Guards the reporter itself: it returns [] on a file with no pins at all."""
        assert LOCK.read_text(encoding="utf-8").count("--hash=sha256:") > 100

    @pytest.mark.parametrize(
        ("lock_body", "why"),
        [
            pytest.param(
                "pytest==9.0.3\n",
                "a pin with no continuation and no hashes",
                id="a-pin-with-no-hashes",
            ),
            pytest.param(
                "pytest==9.0.3 \\\n    # via nothing\n",
                "a pin whose continuation is a comment rather than a hash",
                id="a-continuation-that-is-not-a-hash",
            ),
            pytest.param(
                "pytest==9.0.3 ; python_version >= '3.10'\n",
                "a marked pin with no hashes",
                id="a-marked-pin-with-no-hashes",
            ),
            pytest.param(
                "pytest==9.0.3 \\\n    --hash=sha256:aaa\nruff==0.6.9\n",
                "one hashed pin and one unhashed one",
                id="one-of-two-unhashed",
            ),
        ],
    )
    def test_an_unhashed_requirement_is_reported(self, tmp_path: Path, lock_body: str, why: str) -> None:
        """Without these the hash check would pass on a lock with no requirements at all."""
        probe = tmp_path / "requirements-lock.txt"
        probe.write_text(f"# header\n# uv pip compile --universal --generate-hashes\n{lock_body}", encoding="utf-8")
        offenders = unhashed_requirements(probe.read_text(encoding="utf-8"))
        assert offenders, f"{why} must be reported"
        assert any("ruff" in o or "pytest" in o for o in offenders)

    def test_a_fully_hashed_probe_is_not_reported(self, tmp_path: Path) -> None:
        """The control: without it the four negatives above pass on a broken reporter."""
        probe = tmp_path / "requirements-lock.txt"
        probe.write_text(
            "# header\n# uv pip compile --universal --generate-hashes\n"
            "pytest==9.0.3 ; python_version >= '3.10' \\\n"
            "    --hash=sha256:aaa \\\n"
            "    --hash=sha256:bbb\n"
            "    # via -r requirements-dev.txt\n"
            "ruff==0.6.9 \\\n"
            "    --hash=sha256:ccc\n",
            encoding="utf-8",
        )
        assert unhashed_requirements(probe.read_text(encoding="utf-8")) == []


class TestInstallsRefuseAnArtefactTheLockDoesNotName:
    """A hashed lock buys nothing unless the install step is told to check it."""

    @pytest.mark.parametrize("path", [WORKFLOW, DRIFT_WORKFLOW], ids=lambda p: p.name)
    def test_every_lock_install_requires_hashes(self, path: Path) -> None:
        installs = [line for line in pip_install_lines(path.read_text(encoding="utf-8")) if LOCK_NAME in line]
        assert installs, f"{path.name} installs no requirements file at all"
        offenders = [line for line in installs if "--require-hashes" not in line]
        assert not offenders, (
            f"{path.name} installs the lock without --require-hashes: {offenders}. "
            "Without the flag pip reads the hashes and ignores them, so the lock's integrity "
            "is decoration and a substituted artefact installs silently."
        )

    def test_an_install_step_without_the_flag_is_a_finding(self, tmp_path: Path) -> None:
        """Without this the check would pass on a workflow that installs nothing."""
        probe = tmp_path / "probe.yml"
        probe.write_text(
            f"jobs:\n  one:\n    steps:\n      - run: |\n          python -m pip install -r {LOCK_NAME}\n",
            encoding="utf-8",
        )
        text = probe.read_text(encoding="utf-8")
        installs = [line for line in pip_install_lines(text) if LOCK_NAME in line]
        assert installs, "the probe must contain an install line for this case to mean anything"
        assert [line for line in installs if "--require-hashes" not in line]


class TestAuditingTheLockAloneIsNotAPartialAudit:
    """DEC-047: `audit-python` reads the lock, and that has to remain a superset.

    `--generate-hashes` forced the change: pip enters `--require-hashes` mode as
    soon as any input file carries a hash, then demands `==` on every
    requirement in every file, so passing `requirements.txt` (`fastapi>=0.110,<1.0`)
    alongside the hashed lock made pip-audit fail outright. Scanning the lock
    alone is broader anyway — it carries the transitive dependencies the range
    files never name — but "broader" is a claim, and this is the check.
    """

    def test_every_declared_distribution_is_pinned_in_the_lock(self) -> None:
        pinned = lock_pins(LOCK.read_text(encoding="utf-8"))
        for path in RANGE_FILES:
            declared = distribution_names(path.read_text(encoding="utf-8"))
            assert declared, f"{path.name} declares no distributions; the parser or the file is broken"
            missing = sorted(declared - pinned)
            assert not missing, (
                f"{path.name} names {missing}, which {LOCK_NAME} does not pin. `make audit-python` "
                "scans the lock alone, so anything the lock omits is scanned by nothing at all."
            )

    def test_the_lock_is_strictly_broader_than_what_the_range_files_name(self) -> None:
        """If it were merely equal, the transitive set would be going unscanned."""
        pinned = lock_pins(LOCK.read_text(encoding="utf-8"))
        declared: set[str] = set()
        for path in RANGE_FILES:
            declared |= distribution_names(path.read_text(encoding="utf-8"))
        assert len(pinned) > len(declared), (
            f"{LOCK_NAME} pins {len(pinned)} distributions against {len(declared)} named across "
            f"{[p.name for p in RANGE_FILES]}; a lock that adds no transitive dependencies is not a lock"
        )

    def test_a_distribution_missing_from_the_lock_is_a_finding(self, tmp_path: Path) -> None:
        """Without this the subsumption check could pass on an empty range file."""
        range_file = tmp_path / "requirements.txt"
        range_file.write_text("# comment\nfastapi>=0.110,<1.0\nnot-in-the-lock>=1.0\n", encoding="utf-8")
        declared = distribution_names(range_file.read_text(encoding="utf-8"))
        assert declared == {"fastapi", "not-in-the-lock"}
        assert sorted(declared - lock_pins(LOCK.read_text(encoding="utf-8"))) == ["not-in-the-lock"]

    def test_the_audit_target_scans_the_lock(self) -> None:
        """The Makefile is the thing that has to say it, not this docstring."""
        from harness.shared.tests._helpers import REPO

        makefile = (REPO / "Makefile").read_text(encoding="utf-8")
        recipe = makefile.split("audit-python:", 1)[1].split("\n.PHONY", 1)[0]
        assert f"pip-audit --requirement {LOCK_NAME}" in recipe, (
            "audit-python must scan the lock; a range file alongside it puts pip into "
            "--require-hashes mode and fails the whole scan"
        )
