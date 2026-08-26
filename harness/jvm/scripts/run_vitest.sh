#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
OUT=".governance/vitest-results.json"; mkdir -p "$(dirname "$OUT")"; rm -f "$OUT"
"$ROOT/node_modules/.bin/vitest" run "$@" --reporter=default --reporter=json --outputFile.json="$OUT"
python3 "$ROOT/scripts/verify_zero_skips.py" --vitest-json "$OUT"
