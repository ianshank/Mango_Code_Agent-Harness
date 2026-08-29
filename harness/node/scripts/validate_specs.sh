#!/usr/bin/env bash
# Spec gate. Three tiers, in increasing strictness:
#   structural -- always runs; shape rules every plan must satisfy.
#   plan       -- always runs; defect rules over changed plans (validate_plan.py).
#   strict     -- `openspec validate`, when the binary is present.
# Rule logic lives in harness/shared/plan_rules.py. It used to be duplicated here
# as an inline heredoc and again in validate_specs.py, which is the drift shape
# `make check-dedup` exists to catch.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SPEC_DIR="${SPEC_DIR:-$ROOT/docs/specs}"
VALIDATOR="${SPEC_VALIDATOR:-openspec}"
REQUIRE_STRICT="${REQUIRE_STRICT_SPEC_VALIDATOR:-0}"
[ -d "$SPEC_DIR" ] || { echo "specs: $SPEC_DIR does not exist" >&2; exit 1; }
if command -v "$VALIDATOR" >/dev/null 2>&1; then
  "$VALIDATOR" validate "$SPEC_DIR"
elif [ "$REQUIRE_STRICT" = "1" ]; then
  echo "specs: strict validator '$VALIDATOR' is required in this environment; failing closed" >&2
  exit 1
else
  echo "specs: WARNING strict validator '$VALIDATOR' unavailable; structural tier remains mandatory" >&2
fi
python3 - "$SPEC_DIR" "$ROOT" <<'PY2'
import pathlib, sys
spec_dir, root = pathlib.Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, root)
from harness.shared.plan_rules import structural_findings, structural_line

files = sorted(p for p in spec_dir.rglob('*.md') if p.name != 'SPEC_TEMPLATE.md')
if not files:
    raise SystemExit('specs: no markdown specs found')
fail = []
for path in files:
    rel = path.relative_to(spec_dir)
    fail += [structural_line(f) for f in structural_findings(
        path.read_text(encoding='utf-8'), str(rel))]
if fail:
    raise SystemExit('specs: FAILED\n  - ' + '\n  - '.join(fail))
print(f'specs: structural validation passed ({len(files)} documents)')
PY2
# Fails closed when absent, unlike the strict tier above: `openspec` is an
# unpinned external binary an adopter may legitimately not have, whereas
# validate_plan.py ships in this repository beside this script. Its absence means
# the shared kernel is broken, not that an optional tool is missing.
PLAN_TIER="$ROOT/harness/shared/validate_plan.py"
[ -f "$PLAN_TIER" ] || { echo "specs: $PLAN_TIER missing; failing closed" >&2; exit 1; }
python3 "$PLAN_TIER" --repo-root "$ROOT" --spec-dir "$SPEC_DIR"
