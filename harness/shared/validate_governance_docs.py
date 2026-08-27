#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path


def main(workspace: Path = Path(".")) -> None:
    p = json.loads((workspace / ".governance/policy.json").read_text())
    charter = workspace / "docs/PROJECT-CHARTER.md"
    skill = workspace / p.get("governance_skill_path", "agents/GOVERNANCE_SKILL.md")
    log = workspace / ".governance/decision-log.md"
    fail = []
    version = str(p.get("charter_version", ""))
    if not version:
        fail.append("policy has no charter_version")
    elif not charter.is_file() or f"Charter v{version}" not in charter.read_text():
        fail.append(f"charter is missing or does not declare Charter v{version}")
    if not skill.is_file():
        fail.append(f"governance skill missing: {skill}")
    else:
        s = skill.read_text()
        m = re.search(r"^Reviewed:\s*(\d{4}-\d{2}-\d{2})\s*$", s, re.M)
        if not m:
            fail.append("governance skill has no Reviewed: YYYY-MM-DD")
        else:
            reviewed = dt.date.fromisoformat(m.group(1))
            age = (dt.date.today() - reviewed).days
            if age < 0:
                fail.append("governance skill review date is in the future")
            if age > int(p.get("skill_max_age_days", 90)):
                fail.append(f"governance skill review is stale ({age} days)")
        since = re.search(r"^## Decisions since (\d{4}-\d{2}-\d{2})\s*$", s, re.M)
        if not since:
            fail.append("governance skill lacks Decisions since YYYY-MM-DD section")
        elif not log.is_file():
            fail.append("decision log missing")
        else:
            start = dt.date.fromisoformat(since.group(1))
            missing = []
            entry = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*\|\s*([A-Za-z0-9.-]+)\s*\|", re.M)
            for date, id_ in entry.findall(log.read_text()):
                if dt.date.fromisoformat(date) >= start and id_ not in s:
                    missing.append(id_)
            if missing:
                fail.append("governance skill is missing recent decisions: " + ", ".join(sorted(set(missing))))
    if fail:
        raise SystemExit("governance-docs: FAILED\n  - " + "\n  - ".join(fail))
    print("governance-docs: passed")

if __name__ == "__main__":
    main()
