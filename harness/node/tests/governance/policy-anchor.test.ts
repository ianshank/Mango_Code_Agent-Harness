import { describe, expect, it } from 'vitest';
import { governanceRequirementCount } from '../../src/governance/policy-anchor';

describe('governance anchors C-GOV-1 R-GOV-2', () => {
  it('publishes both governed requirements', () => { expect(governanceRequirementCount()).toBe(2); });
});
