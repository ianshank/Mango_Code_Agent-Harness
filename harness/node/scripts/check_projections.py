#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

ID = re.compile(r"\b(DEC-[0-9]+|RB-[0-9]+[a-z]?|G-[A-Z]+|S[0-9]+\.[0-9]+)\b")
ap = argparse.ArgumentParser()
ap.add_argument("--config", default=".governance/projections.json")
ap.add_argument("--decision-log", default=".governance/decision-log.md")
ns = ap.parse_args()
cfg = json.loads(Path(ns.config).read_text())
known = set(ID.findall(Path(ns.decision_log).read_text()))
if not cfg.get("enabled", False):
    d = cfg.get("decision_id", "")
    if d not in known:
        raise SystemExit("projections: disabled without a decision-log entry")
    print(f"projections: explicitly not applicable under {d}")
    raise SystemExit(0)
fail = []
for m in cfg.get("mappings", []):
    a, b = Path(m["source"]), Path(m["projection"])
    if not a.is_file() or not b.is_file():
        fail.append(f"missing mapping endpoint: {a} -> {b}")
        continue
    if a.read_bytes() != b.read_bytes():
        fail.append(f"drift: {a} != {b}")
if not cfg.get("mappings"):
    fail.append("enabled but no mappings configured")
if fail:
    raise SystemExit("projections: FAILED\n  - " + "\n  - ".join(fail))
print("projections: passed")
