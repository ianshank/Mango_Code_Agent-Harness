#!/usr/bin/env python3
"""Fail a run when skipped/todo tests are not individually governed.

Vitest exemptions are keyed by exact source file + full test name. JUnit
exemptions are keyed by exact JUnit Platform unique ID + display name. Every
waiver must cite a live governance decision and carries owner/reason/expiry.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

# Fallback decision-ID grammar for the adopter path (no policy file). The
# authoritative copy is governance-policy.json `decision_id_pattern`; the
# lockstep test in test_policy_consistency.py pins this literal to it.
FALLBACK_ID_PATTERN = r"\b(DEC-[0-9]+|RB-[0-9]+[a-z]?|G-[A-Z]+|S[0-9]+\.[0-9]+)\b"
_POLICY_PATH = Path(__file__).resolve().parent.parent / "governance-policy.json"


def _decision_id_regex() -> re.Pattern[str]:
    """Decision-ID grammar from the policy, converted from the anchored
    ``^(...)$`` form to the ``\\b(...)\\b`` search form. No policy file is the
    adopter path (fallback literal); a present-but-malformed policy fails
    closed. Standalone stdlib by design — no harness imports."""
    if not _POLICY_PATH.is_file():
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
        raise SystemExit(f"zero-skip: cannot read waiver registry: {e}") from e
    out: list[dict] = []
    today = dt.date.today()
    for w in data.get("waivers", []):
        common = ("framework", "decision_id", "reason", "owner", "expires")
        if any(not w.get(k) for k in common):
            raise SystemExit("zero-skip: malformed waiver entry")
        if w["framework"] not in ("vitest", "junit"):
            raise SystemExit(f"zero-skip: unsupported waiver framework {w['framework']!r}")
        if w["framework"] == "vitest" and any(not w.get(k) for k in ("file", "test")):
            raise SystemExit("zero-skip: Vitest waiver requires exact file and test")
        if w["framework"] == "junit" and any(not w.get(k) for k in ("unique_id", "test")):
            raise SystemExit("zero-skip: JUnit waiver requires exact unique_id and test")
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
    approved = {(w["unique_id"], w["test"]): w for w in registry if w["framework"] == "junit"}
    bad: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            bad.append(line)
            continue
        unique_id, display, reason = parts
        waiver = approved.get((unique_id, display))
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
