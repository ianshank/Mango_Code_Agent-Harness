"""Tests for the gitleaks allowlist liveness gate (gate-truthfulness R-GT-10).

The gate itself shells out to gitleaks, which the unit suite does not have. So
the scan is stubbed and everything around it -- parsing, the keep declarations,
the fail-closed paths -- is exercised directly. The end-to-end behaviour is
covered where the tool exists, by `make secrets-allowlist-check` in the
`secret-scan` job.

Nothing here is skipped when gitleaks is absent: a skip would reintroduce the
exact "gate reports nothing and looks green" shape this gate was written for.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from harness.shared.governance import check_secret_allowlist as gate

pytestmark = pytest.mark.governance

CONFIG = """title = "Test policy"

[extend]
useDefault = true

[allowlist]
# keep: kept/fixture\\.py -- plants secret-shaped values on purpose
description = "test"
paths = [
  '''live/one\\.py''',
  '''kept/fixture\\.py''',
  '''dead/nothing\\.py'''
]
"""


#: A config whose FIRST `paths = [` and first `# keep:` both belong to a rule's
#: own allowlist, not to the top-level one. Both parsers must ignore them.
CONFIG_WITH_RULE_ALLOWLIST = r"""title = "Test policy"

[extend]
useDefault = true

[[rules]]
id = "custom-rule"

[rules.allowlist]
# keep: decoy/other\.py -- planted inside a rule's own allowlist
paths = [
  '''decoy/other\.py'''
]

[allowlist]
paths = [
  '''live/one\.py'''
]
"""


def _findings(*paths: str) -> list[dict]:
    return [{"File": path, "RuleID": "generic-api-key"} for path in paths]


class TestParsing:
    def test_every_triple_quoted_entry_is_recovered(self) -> None:
        assert gate.allowlist_paths(CONFIG) == [
            r"live/one\.py",
            r"kept/fixture\.py",
            r"dead/nothing\.py",
        ]

    def test_a_config_without_an_allowlist_yields_no_entries(self) -> None:
        assert gate.allowlist_paths("[extend]\nuseDefault = true\n") == []

    def test_paths_in_another_table_are_not_read_as_allowlist_entries(self) -> None:
        """Raised by review: an unscoped search takes the FIRST `paths = [`.

        A gitleaks config may legitimately carry `paths` elsewhere -- a
        `[[rules]]` entry's own `[rules.allowlist]` is the obvious case. Reading
        that array instead reports the wrong entries entirely: it would claim
        the allowlist exempts the decoy and miss the real entry, so a dead entry
        goes unreported and a live one is called dead. `declared_keeps` was
        already scoped to the block; this sibling was not.
        """
        assert gate.allowlist_paths(CONFIG_WITH_RULE_ALLOWLIST) == [r"live/one\.py"], (
            "the parser read a `paths` array from a table that is not the allowlist"
        )

    def test_a_keep_in_another_tables_allowlist_grants_nothing(self) -> None:
        """The same scoping, for the other parser that reads the block."""
        assert gate.declared_keeps(CONFIG_WITH_RULE_ALLOWLIST) == {}

    def test_keep_declarations_carry_their_reason(self) -> None:
        keeps = gate.declared_keeps(CONFIG)
        assert keeps == {r"kept/fixture\.py": "plants secret-shaped values on purpose"}

    def test_a_keep_outside_the_allowlist_block_grants_nothing(self) -> None:
        """Found by review of this module: the first version scanned the whole
        file, so a `# keep:` line in a header comment, in prose after the block,
        or in a commented-out rule exempted an entry -- a control an unreviewed
        edit elsewhere could widen, which is the shape this gate exists to close.
        """
        smuggled = (
            "# keep: dead/nothing\\.py -- planted outside the allowlist\n"
            "[extend]\nuseDefault = true\n\n"
            "[allowlist]\npaths = [\n  '''dead/nothing\\.py'''\n]\n"
        )
        assert gate.declared_keeps(smuggled) == {}
        assert gate.unearned_entries(
            [r"dead/nothing\.py"], _findings("live/one.py"), gate.declared_keeps(smuggled)
        ) == [r"dead/nothing\.py"], "a keep outside the allowlist block still exempted an entry"

    def test_a_keep_after_the_block_also_grants_nothing(self) -> None:
        trailing = CONFIG + "\n[other]\n# keep: dead/nothing\\.py -- planted after the block\n"
        assert r"dead/nothing\.py" not in gate.declared_keeps(trailing)

    def test_the_allowlist_block_is_removed_but_the_ruleset_is_not(self) -> None:
        """Removing `[extend] useDefault` would make every entry look unearned."""
        stripped = gate.config_without_allowlist(CONFIG)
        assert "[allowlist]" not in stripped
        assert "paths = [" not in stripped
        assert "useDefault = true" in stripped

    def test_a_trailing_section_after_the_allowlist_survives(self) -> None:
        text = CONFIG + '\n[other]\nkeep = "me"\n'
        stripped = gate.config_without_allowlist(text)
        assert "[allowlist]" not in stripped
        assert '[other]' in stripped and 'keep = "me"' in stripped


class TestUnearnedEntries:
    def test_an_entry_matching_a_finding_is_live(self) -> None:
        entries = [r"live/one\.py"]
        assert gate.unearned_entries(entries, _findings("live/one.py"), {}) == []

    def test_an_entry_matching_nothing_is_reported(self) -> None:
        entries = [r"dead/nothing\.py"]
        assert gate.unearned_entries(entries, _findings("live/one.py"), {}) == [r"dead/nothing\.py"]

    def test_a_declared_keep_is_exempt(self) -> None:
        entries = [r"kept/fixture\.py"]
        keeps = {r"kept/fixture\.py": "a reason"}
        assert gate.unearned_entries(entries, _findings("live/one.py"), keeps) == []

    def test_a_malformed_entry_fails_closed_rather_than_being_skipped(self) -> None:
        with pytest.raises(SystemExit):
            gate.unearned_entries(["([unclosed"], _findings("x.py"), {})


class TestMainFailsClosed:
    def _config(self, tmp_path: Path, text: str = CONFIG) -> Path:
        path = tmp_path / ".gitleaks.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_an_unreadable_config_is_a_failure(self, tmp_path: Path, caplog) -> None:
        with caplog.at_level(logging.ERROR):
            assert gate.main(["--config", str(tmp_path / "absent.toml")]) == 1
        assert "could not read" in caplog.text

    def test_a_missing_gitleaks_is_a_failure_not_a_pass(self, tmp_path: Path, caplog) -> None:
        """The tool's absence must never read as "nothing to report"."""
        config = self._config(tmp_path)
        with caplog.at_level(logging.ERROR):
            assert gate.main(["--config", str(config), "--gitleaks", "definitely-not-a-real-binary"]) == 1
        assert "fails closed" in caplog.text

    def test_a_config_with_no_entries_passes_trivially(self, tmp_path: Path) -> None:
        config = self._config(tmp_path, "[extend]\nuseDefault = true\n")
        assert gate.main(["--config", str(config)]) == 0

    def test_zero_findings_is_a_failure(self, tmp_path: Path, monkeypatch, caplog) -> None:
        """Indistinguishable from a ruleset that is not running -- so never a pass."""
        config = self._config(tmp_path)
        monkeypatch.setattr(gate.shutil, "which", lambda _name: "/usr/bin/true")
        monkeypatch.setattr(gate, "scan_findings", lambda *_a, **_k: [])
        with caplog.at_level(logging.ERROR):
            assert gate.main(["--config", str(config)]) == 1
        assert "zero findings" in caplog.text

    def test_an_unearned_entry_is_reported_by_name(self, tmp_path: Path, monkeypatch, caplog) -> None:
        config = self._config(tmp_path)
        monkeypatch.setattr(gate.shutil, "which", lambda _name: "/usr/bin/true")
        monkeypatch.setattr(gate, "scan_findings", lambda *_a, **_k: _findings("live/one.py"))
        with caplog.at_level(logging.ERROR):
            assert gate.main(["--config", str(config)]) == 1
        assert r"dead/nothing\.py" in caplog.text

    def test_all_entries_earning_their_place_passes(self, tmp_path: Path, monkeypatch) -> None:
        config = self._config(tmp_path)
        monkeypatch.setattr(gate.shutil, "which", lambda _name: "/usr/bin/true")
        monkeypatch.setattr(
            gate, "scan_findings", lambda *_a, **_k: _findings("live/one.py", "dead/nothing.py")
        )
        assert gate.main(["--config", str(config)]) == 0


class TestScanFindings:
    """The subprocess boundary, driven with a stub binary rather than gitleaks."""

    def _stub(self, tmp_path: Path, body: str) -> str:
        script = tmp_path / "fake-gitleaks"
        script.write_text(body, encoding="utf-8")
        script.chmod(0o755)
        return str(script)

    def test_a_report_that_is_never_written_fails(self, tmp_path: Path, caplog) -> None:
        stub = self._stub(tmp_path, "#!/bin/sh\nexit 3\n")
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit):
            gate.scan_findings(tmp_path, CONFIG, stub)
        assert "produced no report" in caplog.text

    def test_a_non_json_report_fails(self, tmp_path: Path, caplog) -> None:
        stub = self._stub(
            tmp_path,
            '#!/bin/sh\nwhile [ $# -gt 0 ]; do\n'
            '  if [ "$1" = "--report-path" ]; then printf "not json" > "$2"; fi\n'
            '  shift\ndone\nexit 0\n',
        )
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit):
            gate.scan_findings(tmp_path, CONFIG, stub)
        assert "not valid JSON" in caplog.text

    def test_a_report_that_is_not_a_list_fails(self, tmp_path: Path, caplog) -> None:
        stub = self._stub(
            tmp_path,
            '#!/bin/sh\nwhile [ $# -gt 0 ]; do\n'
            '  if [ "$1" = "--report-path" ]; then printf "{}" > "$2"; fi\n'
            '  shift\ndone\nexit 0\n',
        )
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit):
            gate.scan_findings(tmp_path, CONFIG, stub)
        assert "not a list" in caplog.text

    def test_findings_are_returned_verbatim(self, tmp_path: Path) -> None:
        payload = json.dumps(_findings("a.py"))
        stub = self._stub(
            tmp_path,
            "#!/bin/sh\nwhile [ $# -gt 0 ]; do\n"
            f'  if [ "$1" = "--report-path" ]; then printf \'{payload}\' > "$2"; fi\n'
            "  shift\ndone\nexit 0\n",
        )
        assert gate.scan_findings(tmp_path, CONFIG, stub) == _findings("a.py")


class TestTheShippedConfigIsCovered:
    """The real config must parse, and every keep must name a real entry."""

    def test_every_declared_keep_names_an_entry_that_exists(self) -> None:
        from harness.shared.tests._helpers import REPO

        text = (REPO / ".gitleaks.toml").read_text(encoding="utf-8")
        entries = set(gate.allowlist_paths(text))
        assert entries, "the shipped .gitleaks.toml allowlist did not parse"
        stale = sorted(set(gate.declared_keeps(text)) - entries)
        assert not stale, (
            f"`# keep:` declarations naming entries that are no longer in the allowlist: {stale}. "
            "A keep for a removed entry is a stale exemption waiting to be reused."
        )
