#!/usr/bin/env python3
"""Reference PDP logic. Deploy the production equivalent outside the governed repo."""
import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--action", required=True)
    ap.add_argument("--human-approved", action="store_true")
    ns = ap.parse_args()

    p = json.loads(Path(ns.policy).read_text())
    roles = {a["id"]: a for a in p["agents"]}
    role = roles.get(ns.agent)
    if role is None:
        raise SystemExit("DENY: unknown agent identity")
    if ns.action not in role["allowed_actions"]:
        raise SystemExit("DENY: action not granted to this agent")
    if ns.action in role.get("human_approval_required_for", []) and not ns.human_approved:
        raise SystemExit("DENY: human approval required for this action")
    print("ALLOW")


if __name__ == "__main__":
    main()
