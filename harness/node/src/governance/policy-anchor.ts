/** Requirement anchors for project traceability. C-GOV-1, R-GOV-2. */
export const GOVERNANCE_REQUIREMENTS = ['C-GOV-1', 'R-GOV-2'] as const;
export function governanceRequirementCount(): number {
  return GOVERNANCE_REQUIREMENTS.length;
}
