#!/bin/bash
# PreToolUse(Bash): deny destructive/irreversible commands outright.
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

DENY=0
case "$COMMAND" in
  *"rm -rf /"*|*"rm -rf ~"*|*"rm -rf ."*|*mkfs*|*"dd if="*"of=/dev/"*|*"> /dev/sd"*)
    DENY=1
    ;;
esac

if [ "$DENY" -eq 1 ]; then
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: "Blocked: command matches a destructive-command pattern. Confirm intent explicitly with the user before retrying with a narrower, scoped command."
    }
  }'
  exit 0
fi

exit 0
