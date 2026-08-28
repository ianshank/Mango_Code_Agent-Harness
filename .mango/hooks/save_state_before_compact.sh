#!/bin/bash
# PreCompact hook: put working-tree state on disk before context is summarized.
#
# Dormant by decision DEC-003 (see session_start.sh).
#
# Writes into .mango/.state/, which .gitignore already covers. The previous
# version appended to $PROJECT_DIR/NOTES.md -- a path that is neither tracked
# nor ignored, so the hook would have created an untracked file at the repo
# root and left it showing in every subsequent `git status`.
PROJECT_DIR="${MANGO_PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-$(pwd)}}"
STATE_DIR="$PROJECT_DIR/.mango/.state"
CHECKPOINT="$STATE_DIR/precompact-checkpoint.md"

mkdir -p "$STATE_DIR" || exit 0

{
  echo ""
  echo "## Pre-compaction checkpoint: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "- git status:"
  git -C "$PROJECT_DIR" status --short 2>/dev/null | sed 's/^/  /'
  echo "- git diff stat:"
  git -C "$PROJECT_DIR" diff --stat 2>/dev/null | sed 's/^/  /'
} >> "$CHECKPOINT" 2>/dev/null

exit 0
