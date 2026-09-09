#!/usr/bin/env bash
# verify-tier-a.sh — Tier A enforcement shim
# Called PostToolUse by .mango/agents/hooks.json
# Delegates to the canonical Makefile lint gate (fast; suitable for per-tool-use enforcement).
# Full ci gate is too slow for PostToolUse — lint is the right scope here.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$(cd "$(dirname "$0")/.." && pwd)")"
cd "${REPO_ROOT}"

exec make lint
