#!/usr/bin/env bash
set -euo pipefail
# Resolve paths from this script's own location: scripts live one level below
# the stack root (e.g. harness/node/scripts), so the vitest binary and the
# zero-skips verifier are found relative to the script, not the repo top-level.
# NOTE: .sh files are outside check_dedup.py's .py-only shim scan — the shared
# and per-stack copies of this script must be kept in sync manually.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_ROOT="$(dirname "$SELF_DIR")"
OUT=".governance/vitest-results.json"; mkdir -p "$(dirname "$OUT")"; rm -f "$OUT"
"$STACK_ROOT/node_modules/.bin/vitest" run "$@" --reporter=default --reporter=json --outputFile.json="$OUT"
python3 "$SELF_DIR/verify_zero_skips.py" --vitest-json "$OUT"
