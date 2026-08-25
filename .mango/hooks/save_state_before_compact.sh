#!/bin/bash
# PreCompact hook: ensure critical state is on disk before context is summarized/dropped.
PROJECT_DIR="${CLAUDE_PROJECT_DIR}"
NOTES="$PROJECT_DIR/NOTES.md"

{
  echo ""
  echo "## Pre-compaction checkpoint: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "- git status:"
  git -C "$PROJECT_DIR" status --short 2>/dev/null | sed 's/^/  /'
  echo "- git diff stat:"
  git -C "$PROJECT_DIR" diff --stat 2>/dev/null | sed 's/^/  /'
} >> "$NOTES" 2>/dev/null

exit 0
