#!/usr/bin/env python3
"""Fail a run when skipped/todo tests are not individually governed.

Vitest exemptions are keyed by exact source file + full test name. JUnit
exemptions are keyed by exact JUnit Platform unique ID + display name. Every
waiver must cite a live governance decision and carries owner/reason/expiry.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import re
import stat
from pathlib import Path

# Fallback decision-ID grammar for the adopter path (no policy file). The
# authoritative copy is governance-policy.json `decision_id_pattern`; the
# lockstep test in test_policy_consistency.py pins this literal to it.
FALLBACK_ID_PATTERN = r"\b(DEC-[0-9]+|RB-[0-9]+[a-z]?|G-[A-Z]+|S[0-9]+\.[0-9]+)\b"
_POLICY_PATH = Path(__file__).resolve().parent.parent / "governance-policy.json"


def _policy_is_absent(path: Path, prefix: str) -> bool:
    """True only when nothing exists at ``path`` -- the adopter path.

    Anything else exits: a directory, a dangling symlink, a FIFO, a parent
    component that is not a directory, an unreadable parent. Probes with
    stat/lstat rather than Path.is_file(), because is_file(), exists() and
    is_symlink() all swallow OSError and answer False -- so each of them
    reports "absent" for a policy that is present and merely inaccessible, and
    this gate would fall back to the built-in grammar for a broken deployment.

    Duplicated from policy_loader.policy_file_is_absent on purpose: this module
    is standalone stdlib by contract, because the adopter path copies it into
    stacks that have no harness package to import from.
    """
    try:
        info = path.stat()
    except FileNotFoundError:
        # stat() follows symlinks, so it cannot tell "nothing here" from "the
        # symlink target is gone". lstat() does not follow, and answers it.
        try:
            path.lstat()
        except FileNotFoundError:
            return True
        except OSError as exc:
            raise SystemExit(f"{prefix}: policy path {path} is not readable: {exc}") from exc
        raise SystemExit(
            f"{prefix}: policy path {path} is a symlink whose target does not exist; "
            "refusing to fall back to the built-in decision-ID grammar"
        ) from None
    except OSError as exc:
        raise SystemExit(f"{prefix}: policy path {path} is not readable: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise SystemExit(
            f"{prefix}: policy path {path} exists but is not a regular file; "
            "refusing to fall back to the built-in decision-ID grammar"
        )
    return False


def _decision_id_regex() -> re.Pattern[str]:
    """Decision-ID grammar from the policy, converted from the anchored
    ``^(...)$`` form to the ``\\b(...)\\b`` search form. No policy file is the
    adopter path (fallback literal); a present-but-malformed policy fails
    closed. Standalone stdlib by design — no harness imports."""
    if _policy_is_absent(_POLICY_PATH, "zero-skip"):
        return re.compile(FALLBACK_ID_PATTERN)
    try:
        pattern = json.loads(_POLICY_PATH.read_text(encoding="utf-8"))["decision_id_pattern"]
        body = re.fullmatch(r"\^\((.*)\)\$", pattern).group(1)  # type: ignore[union-attr]
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
        raise SystemExit(f"zero-skip: unusable decision_id_pattern in {_POLICY_PATH}: {exc}") from exc
    return re.compile(r"\b(" + body + r")\b")


ID_RE = _decision_id_regex()


def known_ids(path: str) -> set[str]:
    try:
        return set(ID_RE.findall(Path(path).read_text(encoding="utf-8")))
    except OSError:
        return set()


def waivers(path: str, ids: set[str]) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        # Fail closed: an unreadable waiver registry must stop the run, because
        # we cannot prove any skip is governed. `from e` keeps the underlying
        # cause attached (B904); BLE001 does not fire on a handler that raises.
        raise SystemExit(f"zero-skip: cannot read waiver registry: {e}") from e
    out: list[dict] = []
    # UTC, not the runner's local date: waiver `expires` values are calendar
    # dates, and dt.date.today() would expire a waiver a day early or late
    # depending on which timezone the CI runner happens to sit in.
    today = dt.datetime.now(dt.timezone.utc).date()
    for w in data.get("waivers", []):
        common = ("framework", "decision_id", "reason", "owner", "expires")
        if any(not w.get(k) for k in common):
            raise SystemExit("zero-skip: malformed waiver entry")
        if w["framework"] not in ("vitest", "junit"):
            raise SystemExit(f"zero-skip: unsupported waiver framework {w['framework']!r}")
        if w["framework"] == "vitest" and any(not w.get(k) for k in ("file", "test")):
            raise SystemExit("zero-skip: Vitest waiver requires exact file and test")
        if w["framework"] == "junit":
            # Exactly one addressing form: an exact unique_id, or a unique_id_glob
            # matched against the whole id (DEC-026; the langgraph condition spans
            # ~40 parametrised nodeids). Either way `test` is required, and a glob
            # row is only ever honoured when the skip reason carries the decision
            # id, which the exact form also requires -- so a glob widens the
            # address, never the approval.
            has_exact, has_glob = bool(w.get("unique_id")), bool(w.get("unique_id_glob"))
            if has_exact == has_glob or not w.get("test"):
                raise SystemExit("zero-skip: JUnit waiver requires test and exactly one of unique_id / unique_id_glob")
        if w["decision_id"] not in ids:
            raise SystemExit(f"zero-skip: waiver cites unknown decision {w['decision_id']}")
        try:
            expires = dt.date.fromisoformat(w["expires"])
        except ValueError:
            raise SystemExit(f"zero-skip: invalid expiry {w['expires']!r}") from None
        if expires < today:
            label = w.get("file") or w.get("unique_id") or "<unknown>"
            raise SystemExit(f"zero-skip: expired waiver for {label}::{w.get('test', '')}")
        if w["framework"] == "vitest":
            w = {**w, "file": w["file"].replace("\\", "/")}
        out.append(w)
    return out


def vitest(report: str, registry: list[dict]) -> None:
    data = json.loads(Path(report).read_text(encoding="utf-8"))
    approved = {(w["file"], w["test"]): w for w in registry if w["framework"] == "vitest"}
    bad: list[str] = []
    for tr in data.get("testResults", []):
        file = tr.get("name", "").replace("\\", "/")
        for a in tr.get("assertionResults", []):
            if a.get("status") in ("pending", "todo", "skipped", "disabled"):
                name = " > ".join([*a.get("ancestorTitles", []), a.get("title", "")]).strip(" >")
                matches = [w for (wf, wt), w in approved.items() if file.endswith(wf) and wt == name]
                if len(matches) != 1:
                    bad.append(f"{file}::{name}")
    if bad:
        raise SystemExit("zero-skip: unapproved Vitest skip(s):\n  - " + "\n  - ".join(bad))


def junit(events: str, registry: list[dict]) -> None:
    p = Path(events)
    if not p.exists():
        raise SystemExit(f"zero-skip: JUnit skip evidence missing: {events}")
    junit_rows = [w for w in registry if w["framework"] == "junit"]
    approved = {(w["unique_id"], w["test"]): w for w in junit_rows if w.get("unique_id")}
    globbed = [w for w in junit_rows if w.get("unique_id_glob")]
    bad: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            bad.append(line)
            continue
        unique_id, display, reason = parts
        waiver = approved.get((unique_id, display))
        if waiver is None:
            waiver = next(
                (
                    w
                    for w in globbed
                    if fnmatch.fnmatchcase(unique_id, w["unique_id_glob"]) and fnmatch.fnmatchcase(display, w["test"])
                ),
                None,
            )
        if waiver is None or waiver["decision_id"] not in ID_RE.findall(reason):
            bad.append(f"{display} [{unique_id}] — {reason or 'no reason'}")
    if bad:
        raise SystemExit("zero-skip: unapproved JUnit skip(s):\n  - " + "\n  - ".join(bad))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decision-log", default=".governance/decision-log.md")
    ap.add_argument("--waivers", default=".governance/skip-waivers.json")
    ap.add_argument("--vitest-json")
    ap.add_argument("--junit-events")
    ns = ap.parse_args()
    ids = known_ids(ns.decision_log)
    if not ids:
        raise SystemExit("zero-skip: decision log missing/unreadable or contains no IDs; refusing exemptions")
    registry = waivers(ns.waivers, ids)
    if not ns.vitest_json and not ns.junit_events:
        raise SystemExit("zero-skip: no test evidence supplied; refusing a vacuous pass")
    if ns.vitest_json:
        vitest(ns.vitest_json, registry)
    if ns.junit_events:
        junit(ns.junit_events, registry)
    print("zero-skip: passed")


if __name__ == "__main__":
    main()
