"""Declared tooling configuration must still apply to something real.

Suppressions and allowlists are write-only in practice: nothing tells you when
one stops being needed, so they accumulate until nobody dares touch them.
Measured before this file was written, the ruff config carried three
per-file-ignore patterns that suppressed nothing at all -- including
``scratch/*.py``, for a gitignored directory that does not exist -- plus a
dozen individually unused codes inside patterns that were otherwise live.

Ruff has no unused-ignore check (``RUF100`` covers inline ``# noqa``, not
config-level per-file-ignores), so a one-time prune would simply rot again.
These tests make the prune stick.

``RUF100`` *is* enabled, and only because ``BLE`` is enabled alongside it.
On its own it flagged 20 inert directives, 13 of them the ``# noqa: BLE001``
comments documenting deliberate fail-closed boundaries -- so enabling it alone
would have invited deleting that reasoning. With ``BLE`` selected those become
live, the count drops to the genuinely dead directives, and ``RUF100`` keeps
every ``noqa`` in the tree load-bearing instead of threatening the ones that
matter. The pair is recorded in ``test_deferred_rigor.py::TestEnabledRulesStayEnabled``
so neither can be dropped without the other being reconsidered.

Marked ``slow``: each check shells out to ruff over the whole tree.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on the 3.9/3.10 matrix legs
    import tomli as tomllib

import pytest

from harness.shared.tests._helpers import REPO, ruff_json

pytestmark = pytest.mark.slow

PYPROJECT = REPO / "pyproject.toml"
GITLEAKS = REPO / ".gitleaks.toml"
ESLINT_CONFIG = REPO / "harness" / "node" / "eslint.config.js"
SHARED_POLICY = REPO / "harness" / "shared" / "governance-policy.json"


def _config() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _per_file_ignores() -> dict[str, list[str]]:
    ignores: dict[str, list[str]] = _config()["tool"]["ruff"]["lint"]["per-file-ignores"]
    return ignores


def _isolated_findings(codes: list[str]) -> list[tuple[str, str]]:
    """Findings ruff reports with the project config ignored.

    ``--isolated`` is the whole trick: running ruff normally applies the very
    per-file-ignores under test, so every pattern would look dead. Line length
    and target version are restated because isolation drops those too.
    """
    ruff_cfg = _config()["tool"]["ruff"]
    # ruff_json raises with ruff's stderr if the invocation itself fails. Without
    # that, an exit-2 error leaves stdout empty, parses to [], and every pattern
    # below reports as dead -- a tool failure dressed up as a config finding.
    rows = ruff_json([
        "check", ".", "--isolated", "--no-cache",
        "--line-length", str(ruff_cfg["line-length"]),
        "--target-version", ruff_cfg["target-version"],
        "--select", ",".join(codes),
    ])
    return [(Path(row["filename"]).resolve().relative_to(REPO.resolve()).as_posix(), row["code"]) for row in rows]


@pytest.fixture(scope="module")
def findings() -> list[tuple[str, str]]:
    codes = sorted({code for codes in _per_file_ignores().values() for code in codes})
    if not codes:
        return []
    return _isolated_findings(codes)


class TestPerFileIgnoresAreLive:
    def test_the_probe_finds_something(self, findings: list[tuple[str, str]]) -> None:
        """Guards the measurement: if the isolated run reported nothing, every
        pattern below would look dead and the suite would fail confusingly."""
        if not _per_file_ignores():
            pytest.skip("no per-file-ignores configured; nothing to probe")
        assert findings, "the isolated ruff run produced no findings; the probe is broken"

    @pytest.mark.parametrize("pattern", sorted(_per_file_ignores()))
    def test_pattern_matches_at_least_one_file(self, pattern: str) -> None:
        matched = [
            path for path in REPO.rglob("*.py")
            if "__pycache__" not in path.parts
            and fnmatch.fnmatch(path.relative_to(REPO).as_posix(), pattern)
        ]
        assert matched, (
            f"per-file-ignores pattern {pattern!r} matches no file. Delete it: a pattern "
            "for files that do not exist silently exempts whatever is added there later."
        )

    @pytest.mark.parametrize("pattern", sorted(_per_file_ignores()))
    def test_every_code_still_suppresses_something(
        self, pattern: str, findings: list[tuple[str, str]]
    ) -> None:
        declared = set(_per_file_ignores()[pattern])
        firing = {
            code for path, code in findings
            if code in declared and fnmatch.fnmatch(path, pattern)
        }
        assert declared == firing, (
            f"per-file-ignores[{pattern!r}] declares {sorted(declared - firing)} which suppress "
            "nothing. Remove them, or the config claims a rule is needed where it is not -- "
            "and the day it is genuinely needed, nobody can tell the difference."
        )


class TestGitleaksActuallyScans:
    """An allowlist over an empty ruleset is a scan that cannot fail.

    Passing `--config` to gitleaks **replaces** its built-in ruleset rather than
    extending it. All three configs in this repository declared only an
    `[allowlist]` and no `[[rules]]`, so `make secrets` and the `secret-scan` CI
    job reported "no leaks found" for every input: a planted `AKIA...` key
    scanned clean under the repo config and was found immediately under the
    defaults. INV-1 was published as enforced and detected nothing.

    The allowlist tests below are meaningful only while this one passes.
    """

    CONFIGS = (
        REPO / ".gitleaks.toml",
        REPO / "harness" / "node" / ".gitleaks.toml",
        REPO / "harness" / "jvm" / ".gitleaks.toml",
    )

    @pytest.mark.parametrize("config", CONFIGS, ids=lambda c: str(c.relative_to(REPO)))
    def test_the_config_declares_a_ruleset(self, config: Path) -> None:
        """Parsed, not grepped.

        The first draft of this test used `"[[rules]]" in text`, and the comment
        it sits next to contains that literal -- so the check matched its own
        prose and both mutants survived. Parsing also settles placement for free:
        an `[extend]` written after `[allowlist]` becomes `allowlist.extend`, a
        nested key gitleaks never reads, and `parsed.get("extend")` is then None.
        """
        parsed = tomllib.loads(config.read_text(encoding="utf-8"))
        extend = parsed.get("extend") or {}
        assert extend.get("useDefault") is True or parsed.get("rules"), (
            f"{config.relative_to(REPO)} declares neither `[[rules]]` nor a top-level "
            "`[extend] useDefault = true`. Passing it to --config replaces gitleaks' built-in "
            "ruleset with nothing, so the scan detects no secret in any file or any commit "
            "while still reporting success."
        )


class TestGitleaksAllowlistIsLive:
    """An allowlist entry that outlives its file is a widening blind spot: the
    path stays exempt, and whatever is created there later is exempt too."""

    def _paths(self) -> list[str]:
        """Parse the allowlist's `paths = [...]` block.

        The format is checked before splitting: an IndexError from a changed or
        malformed .gitleaks.toml would report as "the allowlist is empty",
        which points at the wrong problem entirely.
        """
        text = GITLEAKS.read_text(encoding="utf-8")
        assert "paths = [" in text, (
            f"{GITLEAKS.name} has no `paths = [` block; this parser needs updating "
            "for the new format before its verdict means anything"
        )
        remainder = text.split("paths = [", 1)[1]
        assert "]" in remainder, f"{GITLEAKS.name}'s paths block is not closed"
        block = remainder.split("]", 1)[0]
        return [line.strip().strip("',").replace("\\", "") for line in block.splitlines() if line.strip()]

    def test_the_allowlist_is_parsed(self) -> None:
        assert len(self._paths()) > 3, "failed to parse .gitleaks.toml paths"

    def test_every_literal_path_entry_still_exists(self) -> None:
        missing = [
            entry for entry in self._paths()
            # Skip genuine regexes (wildcards); only literal file paths are checkable.
            if ".*" not in entry and not (REPO / entry).exists()
        ]
        assert not missing, (
            f"gitleaks allowlist exempts paths that no longer exist: {missing}. Remove them, "
            "or a future file at the same path is scanned by nobody."
        )


class TestEslintMaxLinesIsPolicySourced:
    """The Node file-size gate must read the budget the Python gate reads.

    `validate_invariants.check_size_budget` takes `limits.size_budget_lines`
    from the governance policy; `eslint.config.js` enforces `max-lines` on the
    Node sources under R-TDH-23. Two gates over one number are only one gate if
    both read the same key: a literal restated in the ESLint config would drift
    the day the policy changed, and nothing would notice because the lint would
    still be green. These tests are textual, like the vitest.config.ts checks in
    `test_coverage_policy_enforcement.py`, because Node is only installed on the
    primary CI leg and this suite runs on every leg.
    """

    @staticmethod
    def _config() -> str:
        return ESLINT_CONFIG.read_text(encoding="utf-8")

    def _max_lines_options(self) -> str:
        """The options object of the `max-lines` rule, asserted to be at `error`.

        Anchoring on the `'error'` severity is deliberate: a rule demoted to
        `'warn'` still appears in the config but `--max-warnings=0` is the only
        thing making a warning fatal, and a later config edit could drop that.
        """
        match = re.search(r"'max-lines':\s*\[\s*'error'\s*,\s*\{(.*?)\}\s*,?\s*\]", self._config(), re.S)
        assert match is not None, (
            "eslint.config.js declares no `'max-lines': ['error', {...}]` rule; the Node file-size "
            "gate (R-TDH-23) is gone or has been demoted below error"
        )
        return match.group(1)

    def test_the_max_is_an_identifier_not_a_number(self) -> None:
        options = self._max_lines_options()
        bound = re.search(r"\bmax:\s*([A-Za-z_$][\w$]*)\b", options)
        assert bound is not None and not re.search(r"\bmax:\s*\d", options), (
            f"max-lines `max` is not bound to an identifier: {options.strip()!r}. It must be read from "
            "limits.size_budget_lines in the governance policy, never restated as a literal"
        )

    def test_the_config_reads_the_policy_key(self) -> None:
        config = self._config()
        assert "governance-policy.json" in config, "eslint.config.js no longer opens the governance policy"
        assert re.search(r"\blimits\b.*?\bsize_budget_lines\b", config, re.S), (
            "eslint.config.js does not read `limits.size_budget_lines`; the max-lines budget is sourced "
            "from somewhere other than the policy key validate_invariants.py enforces"
        )

    def test_the_policy_value_is_not_restated_as_a_literal(self) -> None:
        """A literal that happens to equal the policy today is tomorrow's drift."""
        budget = json.loads(SHARED_POLICY.read_text(encoding="utf-8"))["limits"]["size_budget_lines"]
        assert isinstance(budget, int), "the shipped policy's limits.size_budget_lines is not an integer"
        config = self._config()
        assert not re.search(rf"(?<![\w.]){budget}(?![\w.])", config), (
            f"eslint.config.js contains the literal {budget}, which is the current limits.size_budget_lines; "
            "the budget must come from the policy file so the two cannot diverge"
        )

    def test_there_is_no_fallback_for_a_missing_key(self) -> None:
        """`size_budget_lines ?? N` or `|| N` would relax the gate on exactly the input that should stop it."""
        config = self._config()
        fallback = re.search(r"size_budget_lines\b[^;\n]*?(\?\?|\|\|)\s*\d", config)
        assert fallback is None, (
            f"eslint.config.js falls back to a numeric default for size_budget_lines: {fallback.group(0)!r}. "
            "A malformed policy must fail the lint, not silently relax it"
        )
        assert re.search(r"throw new Error\((?:(?!\)\s*;).)*?size_budget_lines", config, re.S), (
            "eslint.config.js does not throw when limits.size_budget_lines is missing or not a number; "
            "the read must fail closed like vitest.config.ts and policy.ts do"
        )
        assert re.search(r"throw new Error\((?:(?!\)\s*;).)*?\"limits\"", config, re.S), (
            "eslint.config.js does not throw when the `limits` block is absent"
        )

    def test_every_line_counts_like_the_python_gate(self) -> None:
        """validate_invariants counts `len(text.splitlines())`; skipping blanks or comments would let the
        two gates disagree about the same file."""
        options = self._max_lines_options()
        for option in ("skipBlankLines", "skipComments"):
            assert re.search(rf"\b{option}:\s*false\b", options), (
                f"max-lines does not set `{option}: false`; the Node count would diverge from the Python gate"
            )

    def test_the_rule_applies_to_the_sources(self) -> None:
        block = re.search(
            r"files:\s*\[\s*'src/\*\*/\*\.ts'\s*\]\s*,\s*rules:\s*\{(?:(?!\bfiles:).)*?'max-lines'",
            self._config(),
            re.S,
        )
        assert block is not None, (
            "the max-lines rule is not scoped to `files: ['src/**/*.ts']`; a rule over no files enforces nothing"
        )
