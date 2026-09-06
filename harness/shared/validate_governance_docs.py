#!/usr/bin/env python3
"""
Validation script: enforce governance documentation health.

Checks: charter version presence, governance skill freshness (staleness gate
from policy's ``skill_max_age_days``), decision-record schema/status, generated
index drift, and that the skill does not restate full decision bodies.
Exits non-zero with a structured failure list on any violation.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

try:
    import decision_records as dr
except ImportError:  # package import path (pytest)
    from harness.shared import decision_records as dr  # type: ignore


def main(workspace: Path = Path(".")) -> None:
    p = json.loads((workspace / ".governance/policy.json").read_text())
    charter = workspace / "docs/PROJECT-CHARTER.md"
    skill = workspace / p.get("governance_skill_path", "agents/GOVERNANCE_SKILL.md")
    fail: list[str] = []
    version = str(p.get("charter_version", ""))
    if not version:
        fail.append("policy has no charter_version")
    elif not charter.is_file() or f"Charter v{version}" not in charter.read_text():
        fail.append(f"charter is missing or does not declare Charter v{version}")
    decisions_dir = dr.find_decisions_dir(workspace)
    records: list[dr.DecisionRecord] = []
    if decisions_dir is None:
        fail.append("docs/decisions directory missing")
    else:
        try:
            records = dr.load_all(decisions_dir)
        except (OSError, ValueError) as exc:
            fail.append(f"docs/decisions unreadable: {exc}")
            records = []
        if not records:
            # Empty tree is allowed for adopter scaffolds; still require index files
            # when the directory exists so drift checks have a baseline.
            pass
        schema_fail: list[str] = []
        for record in records:
            schema_fail.extend(dr.validate_record(record))
        fail.extend(schema_fail)
        # Index drift only when every record is structurally valid.
        if not schema_fail:
            payload = dr.index_payload(records)
            expected = {
                decisions_dir / "index.json": dr.render_index_json(payload),
                decisions_dir / "index.md": dr.render_index_md(payload),
            }
            # Thin ID index is generated only for the node stack path.
            node_log = decisions_dir.parent.parent / "harness/node/.governance/decision-log.md"
            if node_log.is_file():
                expected[node_log] = dr.render_thin_decision_log(payload)
            for path, content in expected.items():
                if not path.is_file():
                    fail.append(f"generated decision index missing: {path.name}")
                    continue
                if path.read_text(encoding="utf-8") != content:
                    fail.append(f"decision index drift: {path.name} (run generate_decision_index.py)")
    if not skill.is_file():
        fail.append(f"governance skill missing: {skill}")
    else:
        s = skill.read_text(encoding="utf-8")
        m = re.search(r"^Reviewed:\s*(\d{4}-\d{2}-\d{2})\s*$", s, re.M)
        if not m:
            fail.append("governance skill has no Reviewed: YYYY-MM-DD")
        else:
            reviewed = dt.date.fromisoformat(m.group(1))
            # UTC anchor: staleness is measured in whole calendar days, so a
            # local-timezone 'today' would move the threshold by a day.
            age = (dt.datetime.now(dt.timezone.utc).date() - reviewed).days
            if age < 0:
                fail.append("governance skill review date is in the future")
            if age > int(p.get("skill_max_age_days", 90)):
                fail.append(f"governance skill review is stale ({age} days)")
        since = re.search(r"^## Decisions since (\d{4}-\d{2}-\d{2})\s*$", s, re.M)
        if not since:
            fail.append("governance skill lacks Decisions since YYYY-MM-DD section")
        else:
            if "docs/decisions" not in s:
                fail.append("governance skill must point at docs/decisions (SoT)")
            fail.extend(dr.skill_duplicates_decision_text(s))
            start = dt.date.fromisoformat(since.group(1))
            missing = []
            for record in records:
                date_raw = record.meta.get("date")
                if not date_raw:
                    continue
                try:
                    rec_date = dt.date.fromisoformat(str(date_raw))
                except ValueError:
                    fail.append(f"{record.id}: invalid date {date_raw!r}")
                    continue
                if rec_date >= start and record.id not in s:
                    # Thin pointers optional when the section cites the index;
                    # require either the id or an explicit index pointer line.
                    missing.append(record.id)
            # If the skill cites the index, per-id pointers are optional.
            cites_index = bool(
                re.search(r"docs/decisions/(index\.(md|json)|)", s) and re.search(r"index\.(md|json)", s)
            )
            if missing and not cites_index:
                fail.append("governance skill is missing recent decisions: " + ", ".join(sorted(set(missing))))
    if fail:
        raise SystemExit("governance-docs: FAILED\n  - " + "\n  - ".join(fail))
    print("governance-docs: passed")


if __name__ == "__main__":
    main()
