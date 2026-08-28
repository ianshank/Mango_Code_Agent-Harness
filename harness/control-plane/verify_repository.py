#!/usr/bin/env python3
"""Independent repository verifier; deploy/run this from the protected control plane."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def require_digest(path: Path, expected: str, label: str) -> None:
    if not path.is_file(): raise SystemExit(f'DENY: required protected file missing: {label}')
    if len(expected) != 64: raise SystemExit(f'DENY: protected bundle has invalid digest for {label}')
    actual=digest(path)
    if actual.lower()!=expected.lower(): raise SystemExit(f'DENY: digest mismatch for {label}: {actual}')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--repo',default='.'); ap.add_argument('--bundle',required=True); ns=ap.parse_args()
    repo=Path(ns.repo).resolve(); bundle=json.loads(Path(ns.bundle).read_text())
    require_digest(repo/'.governance/policy.json',bundle.get('governance_policy_sha256',''),'.governance/policy.json')
    require_digest(repo/'.governance/agent-policy.json',bundle.get('agent_policy_sha256',''),'.governance/agent-policy.json')
    profiles=bundle.get('profiles',{})
    matches=[(name,p) for name,p in profiles.items() if (repo/p.get('marker','__missing__')).is_file()]
    if len(matches)!=1: raise SystemExit(f'DENY: cannot identify exactly one protected stack profile (matched {len(matches)})')
    profile_name,profile=matches[0]
    for rel,expected in profile.get('protected_files',{}).items(): require_digest(repo/rel,expected,rel)
    if not profile.get('protected_files'): raise SystemExit('DENY: protected profile has no file manifest')
    root=repo/'.governance/root-of-trust.json'
    if not root.is_file(): raise SystemExit('DENY: project root-of-trust declaration is missing')
    r=json.loads(root.read_text())
    if r.get('policy_sha256','').lower()!=bundle['governance_policy_sha256'].lower(): raise SystemExit('DENY: project root-of-trust digest does not match protected bundle')
    if not r.get('external_policy_ref'): raise SystemExit('DENY: project root-of-trust declaration has no external_policy_ref')
    print(f'external-governance: protected digests match ({profile_name})')


if __name__ == "__main__":
    main()
