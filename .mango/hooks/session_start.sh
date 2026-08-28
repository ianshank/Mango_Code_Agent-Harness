#!/bin/bash
# SessionStart hook: point the agent at the durable state files that exist.
#
# Dormant by decision DEC-003: declared in .mango/settings.json but not mirrored
# into .claude/settings.json, so Claude Code never runs it. Kept correct anyway
# -- a hook that is wrong while dormant is a hook that fails the day someone
# wakes it, and its previous version named PLAN.md, NOTES.md and
# .mango/FAILURE_MEMORY.md, none of which existed.
PROJECT_ROOT="${MANGO_PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-$(pwd)}}"

# Only tracked, always-present files are named unconditionally. FAILURE_MEMORY
# is a gitignored runtime artifact, so it is mentioned only when it exists.
CONTEXT="Session starting. Read CLAUDE.md for the operating loop and the pre-PR gates, \
NEXT_STEPS.md for the roadmap, and docs/specs/ for the contract behind any \
non-trivial change. Follow the planner -> reasoner -> verifier loop."

if [ -f "$PROJECT_ROOT/.mango/FAILURE_MEMORY.md" ]; then
  CONTEXT="$CONTEXT Prior failures are recorded in .mango/FAILURE_MEMORY.md; read it before retrying anything."
fi

jq -n --arg msg "$CONTEXT" \
  '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $msg}}'
exit 0
