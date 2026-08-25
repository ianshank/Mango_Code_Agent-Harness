#!/bin/bash
# Stop hook: force a verification pass before the agent is allowed to end the turn.
# Implements the Plan-Execute-Verify pattern and PreCompletionChecklistMiddleware idea.
INPUT=$(cat)
PROJECT_ROOT="${MANGO_PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-$(pwd)}}"
STATE_DIR="${PROJECT_ROOT}/.mango/.state"
mkdir -p "$STATE_DIR"
FLAG="$STATE_DIR/checklist_ack"

if [ -f "$FLAG" ]; then
  rm -f "$FLAG"
  exit 0
fi

CHECKLIST="Before ending this turn, confirm the following in your final message:
1. Requirement: does the change satisfy the original task as stated?
2. Tests: were relevant tests run? What were the results (pass/fail counts)?
3. Lint/typecheck: any new errors introduced?
4. Diff sanity: does 'git diff' match the stated plan, with no stray/incomplete edits?
5. Follow-ups: list any known gaps or TODOs explicitly.
If you have NOT actually run tests/lint yet, run them now before finishing.
Once you have verified all of this, end your turn normally -- do not re-trigger this checklist by looping."

touch "$FLAG"
jq -n --arg msg "$CHECKLIST" '{decision: "block", reason: $msg}'
exit 0
