#!/usr/bin/env python3
"""Every gitleaks allowlist entry must still suppress a real finding (INV-1).

`test_lint_config_liveness.TestGitleaksAllowlistIsLive` asserts that each
allowlist path still *exists*. Nothing asserted that each still *suppresses*
anything -- which is how the list reached 23 paths of which 18 blinded their
files for nothing, under a description calling it strict. A path there exempts
the whole file from every rule, so an entry that has stopped earning its place
is a permanent blind spot that grows quietly: whatever lands in that file later
is exempt too.

This cannot live in the unit suite. It needs gitleaks, the unit suite has no
gitleaks, and INV-2 forbids adding a skip for one -- so it runs in the
`secret-scan` job, where the tool is already installed, via
`make secrets-allowlist-check`.

Method: scan the tree with the allowlist's `paths` removed and nothing else
changed, then check that every entry matches at least one file gitleaks flagged.
Entries that are deliberately kept without a finding are declared in the config
itself, as a `# keep:` comment naming the entry, so the exemption and its reason
travel together rather than living in this script as a hard-coded list.

Exit codes: 0 = every entry earns its place, 1 = an unearned entry or an
unusable input. Absence of evidence is never a pass: a scan that produces no
findings at all fails, because it cannot distinguish "the allowlist is perfect"
from "the ruleset was not running", which is the exact defect the `[extend]
useDefault` line at the top of the config exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from harness.shared.json_logging import configure_gate_process_logging
except ImportError:  # direct `python harness/shared/governance/check_secret_allowlist.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from json_logging import configure_gate_process_logging  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_NAME = ".gitleaks.toml"

#: Marks an allowlist entry that is kept without a current finding, with the
#: reason on the same line. Declared in the config so the exemption is reviewed
#: with the entry it exempts, not in this file.
KEEP_MARKER = re.compile(r"#\s*keep:\s*(?P<entry>\S+)\s*--\s*(?P<reason>.+?)\s*$")


def allowlist_block(config_text: str) -> str:
    """Just the `[allowlist]` block, so a declaration outside it cannot count."""
    match = re.search(r"^\[allowlist\].*?(?=^\[|\Z)", config_text, re.M | re.S)
    return match.group(0) if match else ""


def allowlist_paths(config_text: str) -> list[str]:
    """The `paths = [...]` entries of the allowlist block, in declaration order.

    Scoped to the block for the same reason `declared_keeps` is: an unscoped
    search takes the *first* `paths = [` anywhere in the file. gitleaks configs
    legitimately carry `paths` in other tables -- a `[[rules]]` entry's own
    `[rules.allowlist]` is the obvious one -- and reading that array instead
    would either miss real entries or invent failures for entries that are not
    there. Raised by review of this module, which had already scoped
    `declared_keeps` and left its sibling above it unscoped.
    """
    block = re.search(r"^\s*paths\s*=\s*\[(.*?)\]", allowlist_block(config_text), re.M | re.S)
    if block is None:
        return []
    # Triple-quoted first: gitleaks configs use ''' for regexes so backslashes
    # need no escaping, and a single-quote pattern would split them mid-entry.
    return [
        next(group for group in match if group)
        for match in re.findall(r"'''(.*?)'''|\"([^\"]*)\"|'([^']*)'", block.group(1), re.S)
    ]


def declared_keeps(config_text: str) -> dict[str, str]:
    """Entries the allowlist block declares as deliberately kept, and why.

    Scoped to that block on purpose. Scanning the whole file let a `# keep:`
    line anywhere -- a header comment, prose after the block, a commented-out
    rule -- exempt an entry from this check. That is the same shape as the
    gates this module was written to close: a control that an unreviewed edit
    somewhere else can silently widen. A keep must sit beside the entry it
    exempts, where a reviewer reading the allowlist sees both.
    """
    keeps: dict[str, str] = {}
    for line in allowlist_block(config_text).splitlines():
        match = KEEP_MARKER.search(line)
        if match:
            keeps[match.group("entry")] = match.group("reason")
    return keeps


def config_without_allowlist(config_text: str) -> str:
    """The same config with the whole `[allowlist]` block removed.

    Emptying `paths = []` in place would be the smaller edit, but gitleaks
    refuses to load an allowlist that declares none of commits, paths, regexes
    or stopwords, so the block has to go entirely. Everything above it is
    preserved -- crucially `[extend] useDefault = true`, without which the scan
    runs no rules at all and every entry would look unearned for the wrong
    reason. That failure mode is caught separately: a scan yielding zero
    findings is treated as a failure, not a pass.
    """
    return re.sub(r"^\[allowlist\].*?(?=^\[|\Z)", "", config_text, count=1, flags=re.M | re.S)


def scan_findings(repo_root: Path, config_text: str, gitleaks: str) -> list[dict]:
    """Run gitleaks over the working tree with the allowlist paths removed."""
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / CONFIG_NAME
        config.write_text(config_without_allowlist(config_text), encoding="utf-8")
        report = Path(tmp) / "findings.json"
        result = subprocess.run(
            [
                gitleaks,
                "dir",
                str(repo_root),
                "--config",
                str(config),
                "--report-format",
                "json",
                "--report-path",
                str(report),
                "--no-banner",
                "--redact",
                "--exit-code",
                "0",
            ],
            capture_output=True,
            text=True,
        )
        if not report.exists():
            logger.error(
                "[FAIL] gitleaks produced no report (exit %s): %s",
                result.returncode,
                result.stderr.strip(),
            )
            raise SystemExit(1)
        try:
            findings = json.loads(report.read_text(encoding="utf-8") or "[]")
        except ValueError as exc:
            logger.error("[FAIL] gitleaks report is not valid JSON: %s", exc)
            raise SystemExit(1) from exc
    if not isinstance(findings, list):
        logger.error("[FAIL] gitleaks report is not a list of findings")
        raise SystemExit(1)
    return findings


def unearned_entries(entries: list[str], findings: list[dict], keeps: dict[str, str]) -> list[str]:
    """Allowlist entries matching no flagged file and not declared as kept."""
    flagged = {str(finding.get("File", "")) for finding in findings}
    unearned = []
    for entry in entries:
        if entry in keeps:
            logger.info("[KEEP] %s -- %s", entry, keeps[entry])
            continue
        try:
            pattern = re.compile(entry)
        except re.error as exc:
            logger.error("[FAIL] allowlist entry %r is not a valid regex: %s", entry, exc)
            raise SystemExit(1) from exc
        if any(pattern.search(path) for path in flagged):
            logger.info("[LIVE] %s", entry)
        else:
            unearned.append(entry)
    return unearned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--gitleaks", default="gitleaks")
    args = parser.parse_args(argv)

    config_path = args.config or args.repo_root / CONFIG_NAME
    try:
        config_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("[FAIL] could not read %s: %s", config_path, exc)
        return 1

    # Entries first: a config that exempts nothing needs no scan, and demanding
    # a tool the run will not use would fail an adopter who has no allowlist.
    entries = allowlist_paths(config_text)
    if not entries:
        logger.info("[PASS] %s declares no allowlist paths; nothing can be blinded", config_path)
        return 0

    gitleaks = shutil.which(args.gitleaks)
    if gitleaks is None:
        logger.error(
            "[FAIL] gitleaks is not on PATH; this check runs in the secret-scan job where it is "
            "installed, and fails closed rather than reporting a pass it cannot support"
        )
        return 1

    findings = scan_findings(args.repo_root, config_text, gitleaks)
    if not findings:
        logger.error(
            "[FAIL] scanning with the allowlist removed produced zero findings across the whole tree. "
            "Either every entry is unearned or the ruleset is not running -- the same shape as "
            "the config that scanned clean with no [[rules]] loaded. Refusing to report a pass."
        )
        return 1

    unearned = unearned_entries(entries, findings, declared_keeps(config_text))
    if unearned:
        logger.error(
            "[FAIL] %d allowlist entr(ies) suppress no finding and are not declared as kept: %s. "
            "Each exempts its whole file from every rule. Remove it, or declare it in %s with "
            "a `# keep: <entry> -- <reason>` line.",
            len(unearned),
            ", ".join(unearned),
            config_path.name,
        )
        return 1

    logger.info("[PASS] all %d allowlist entr(ies) still suppress a real finding", len(entries))
    return 0


if __name__ == "__main__":
    configure_gate_process_logging()
    sys.exit(main())
