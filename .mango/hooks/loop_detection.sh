#!/bin/bash
# PreToolUse(Edit|Write): count edits per file this session; warn after 3 repeats on same file.
INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // "unknown"')
PROJECT_ROOT="${MANGO_PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-$(pwd)}}"
STATE_DIR="${PROJECT_ROOT}/.mango/.state"
mkdir -p "$STATE_DIR"
COUNT_FILE="$STATE_DIR/edit_counts.txt"
touch "$COUNT_FILE"

COUNT=$(grep -c "^${FILE}\$" "$COUNT_FILE" 2>/dev/null || echo 0)
echo "$FILE" >> "$COUNT_FILE"
COUNT=$((COUNT + 1))

if [ "$COUNT" -ge 4 ]; then
  jq -n --arg reason "Loop detection: this is edit #$COUNT to $FILE in this session. Stop and reconsider your approach -- re-read the failing test/error output, form a new hypothesis, or ask the user for guidance instead of repeating the same edit pattern." \
    '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "ask", permissionDecisionReason: $reason}}'
  exit 0
fi

exit 0
