#!/usr/bin/env python3
from pathlib import Path
import hashlib, json, re
root=Path('.'); fail=[]
ci=root/'.github/workflows/ci.yml'
if not ci.is_file(): fail.append('CI workflow missing')
elif 'PIN_FULL_COMMIT_SHA' in ci.read_text(): fail.append('third-party action SHAs are not pinned yet')
a=root/'.governance/allowed-remotes.txt'
if not a.is_file() or not [x for x in a.read_text().splitlines() if x.strip() and not x.lstrip().startswith('#')]: fail.append('allowed-remotes.txt has no approved destination')
policy=root/'.governance/policy.json'
policy_digest=hashlib.sha256(policy.read_bytes()).hexdigest() if policy.is_file() else ''
rot=root/'.governance/root-of-trust.json'
if not rot.is_file(): fail.append('root-of-trust.json missing (external policy reference/digest required)')
else:
 try:
  d=json.loads(rot.read_text()); declared=d.get('policy_sha256','')
  if not d.get('external_policy_ref') or not re.fullmatch(r'[0-9a-fA-F]{64}',declared): fail.append('root-of-trust.json lacks external policy ref or SHA-256 digest')
  elif not policy_digest: fail.append('.governance/policy.json missing')
  elif declared.lower()!=policy_digest.lower(): fail.append('root-of-trust.json policy_sha256 does not match local policy.json')
 except Exception as e: fail.append(f'root-of-trust.json invalid: {e}')
if (root/'package.json').exists() and not (root/'pnpm-lock.yaml').is_file(): fail.append('pnpm-lock.yaml missing')
if (root/'build.gradle.kts').exists():
 for f in ('gradlew','gradle.lockfile','gradle/verification-metadata.xml'):
  if not (root/f).exists(): fail.append(f'{f} missing')
if fail:
 print('adoption: BLOCKED',file=__import__('sys').stderr)
 for x in fail: print('  - '+x,file=__import__('sys').stderr)
 raise SystemExit(1)
print('adoption: passed')
