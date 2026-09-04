import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { defineConfig } from 'vitest/config';

// Thresholds come from the governance policy, never from literals here. CLAUDE.md
// forbids hard-coded values precisely because a duplicated number drifts silently:
// this block previously restated lines/statements/branches/functions/perFile and
// nothing detected divergence from the policy it was copied from.
// `test_coverage_policy_enforcement.py` and `test_harness.py` fail if this file
// stops reading the policy.
const POLICY_PATH = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '../shared/governance-policy.json',
);

interface CoveragePolicy {
  lines: number;
  statements: number;
  functions: number;
  branches: number;
  per_file: boolean;
}

function coveragePolicy(): CoveragePolicy {
  // Fail closed: an unreadable or malformed policy must not silently degrade the
  // gate to a permissive default, which is how the Python COV_MIN gate used to
  // fall back to 80 while the policy said 90.
  const raw = JSON.parse(readFileSync(POLICY_PATH, 'utf-8')) as {
    coverage?: Partial<CoveragePolicy>;
  };
  const coverage = raw.coverage;
  if (!coverage) {
    throw new Error(
      `${POLICY_PATH} declares no "coverage" block; refusing an ungated run`,
    );
  }
  for (const key of ['lines', 'statements', 'functions', 'branches'] as const) {
    if (typeof coverage[key] !== 'number') {
      throw new Error(
        `${POLICY_PATH} coverage.${key} is missing or not a number`,
      );
    }
  }
  return coverage as CoveragePolicy;
}

const policy = coveragePolicy();

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts', 'src/**/*.test.ts'],
    dangerouslyIgnoreUnhandledErrors: false,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'cobertura'],
      reportsDirectory: './coverage',
      // Vitest 4 removed coverage.all. Explicit include is what causes matching
      // uncovered files to appear at 0%.
      include: ['src/**/*.ts'],
      exclude: ['src/**/*.d.ts'],
      thresholds: {
        lines: policy.lines,
        statements: policy.statements,
        branches: policy.branches,
        functions: policy.functions,
        perFile: policy.per_file === true,
      },
    },
  },
});
