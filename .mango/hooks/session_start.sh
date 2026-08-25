#!/bin/bash
# SessionStart hook: remind the agent of durable state files.
PROJECT_ROOT="${MANGO_PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-$(pwd)}}"
MSG="Session starting. Check PLAN.md, NOTES.md, and .mango/FAILURE_MEMORY.md for prior context before proceeding. Follow the Plan -> Execute -> Verify loop."
jq -n --arg msg "$MSG" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $msg}}'
exit 0
