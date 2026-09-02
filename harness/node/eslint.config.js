import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import tseslint from 'typescript-eslint';

// The per-file line budget comes from the governance policy, never from a
// literal here (R-TDH-23). The Python gate (validate_invariants.check_size_budget)
// reads the same key, so the two stacks cannot drift apart; a number restated
// in this file would be exactly the silent divergence CLAUDE.md forbids.
// `test_lint_config_liveness.py` fails if this file stops reading the policy.
const POLICY_PATH = resolve(
  import.meta.dirname,
  '../shared/governance-policy.json',
);

function sizeBudgetLines() {
  // Fail closed: a policy with no budget must stop the lint, not relax it. A
  // fallback default here would let a malformed policy pass any file size while
  // the config still looks like it enforces one.
  const raw = JSON.parse(readFileSync(POLICY_PATH, 'utf-8'));
  const limits = raw.limits;
  if (typeof limits !== 'object' || limits === null) {
    throw new Error(
      `${POLICY_PATH} declares no "limits" block; refusing to lint without a file-size budget`,
    );
  }
  const budget = limits.size_budget_lines;
  if (typeof budget !== 'number') {
    throw new Error(
      `${POLICY_PATH} limits.size_budget_lines is missing or not a number`,
    );
  }
  return budget;
}

const SIZE_BUDGET_LINES = sizeBudgetLines();

export default tseslint.config(
  {
    ignores: ['coverage/**', 'node_modules/**', '.governance/**', 'dist/**'],
  },
  {
    files: ['**/*.ts'],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      'no-unused-vars': 'off',
      'no-undef': 'off',
    },
  },
  {
    files: ['src/**/*.ts'],
    rules: {
      // Every line counts, blank or comment, matching how the Python gate
      // measures a file (len(text.splitlines())); a budget that skips comments
      // would let the two gates disagree about the same file.
      'max-lines': [
        'error',
        {
          max: SIZE_BUDGET_LINES,
          skipBlankLines: false,
          skipComments: false,
        },
      ],
    },
  },
  {
    files: ['**/*.js'],
    rules: {
      'no-unused-vars': 'off',
      'no-undef': 'off',
    },
  },
);
