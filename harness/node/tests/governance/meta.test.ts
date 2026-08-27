import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
const root = resolve(import.meta.dirname, '..', '..');
const read = (p: string) => readFileSync(resolve(root, p), 'utf8');
const policy = JSON.parse(read('.governance/policy.json')) as {
  ci_required_targets: string[];
  pre_pr_order: string[];
};
describe('C-GOV-1 repository conformance', () => {
  it('CI invokes every required named Make target', () => {
    const ci = read('.github/workflows/ci.yml');
    for (const g of policy.ci_required_targets)
      expect(ci).toContain(`make ${g}`);
  });
  it('pre-pr order is policy-defined', () => {
    const m = /^pre-pr:\s*(.+?)\s*##/m.exec(read('Makefile'));
    expect(m?.[1]?.trim().split(/\s+/)).toEqual(policy.pre_pr_order);
  });
  it('remotes validates actual configured destinations', () => {
    expect(read('Makefile')).toContain('--check-current-remotes');
  });
});
describe('R-GOV-2 execution enforcement', () => {
  it('pre-push uses the shared remote kernel', () => {
    expect(read('scripts/pre_push_scan.sh')).toContain('remotes.py');
  });
});
